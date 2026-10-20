"""
StockService - owns `stock_types` (master data), `purchases`, and
`stock_adjustments`.

Handles stock coming IN via purchases, and manual STOCK_ADJUSTMENT
corrections after a physical recount. Sale-driven STOCK_OUT rows are
posted by the Sales service (they're part of the sale transaction, not
a separate stock operation) - this service intentionally does not
duplicate that path, same as in the monolith.

NOTE (carried over from the monolith, discovery ambiguity #9): the
sample reports contain no purchase records at all, so `record_purchase`
here is a best-effort design based on the spec's generic "Inventory /
Purchases" fields. Supplier creation itself has no endpoint in this
codebase (it didn't in the monolith either) - suppliers are assumed to
be seeded some other way.

Same consistency model as the other business services (see
sales_service.py's module docstring): commit the local row first, then
post to the Ledger, and delete the local row if the ledger post fails.
"""
import datetime as dt

from sqlalchemy.orm import Session

from common.core.enums import TxnType, Account, Direction, ActorType, PaymentMethod
from common.core.exceptions import ValidationError, NotFoundError
from common.ledger_client import LedgerClient
from common.models.business import Purchase, StockAdjustment
from common.models.master import StockType, Supplier


class StockService:
    def __init__(self, db: Session, ledger: LedgerClient | None = None):
        self.db = db
        self.ledger = ledger or LedgerClient()

    # ------------------------------------------------------------------
    # Stock types (master data)
    # ------------------------------------------------------------------
    def create_stock_type(self, *, name: str, unit: str = "bag") -> StockType:
        stock_type = StockType(name=name, unit=unit)
        self.db.add(stock_type)
        self.db.commit()
        self.db.refresh(stock_type)
        return stock_type

    def list_stock_types(self) -> list[StockType]:
        return self.db.query(StockType).filter(StockType.is_active.is_(True)).all()

    # ------------------------------------------------------------------
    # Purchases
    # ------------------------------------------------------------------
    def record_purchase(
        self,
        *,
        purchase_date: dt.date,
        stock_type_id: int,
        quantity: float,
        rate: float,
        amount_paid: float | None = None,
        supplier_id: int | None = None,
        payment_method: PaymentMethod = PaymentMethod.CASH,
        notes: str | None = None,
        created_by: ActorType = ActorType.USER,
    ) -> Purchase:
        if quantity <= 0:
            raise ValidationError("Purchase quantity must be > 0")
        if rate < 0:
            raise ValidationError("Purchase rate cannot be negative")

        stock_type = self.db.get(StockType, stock_type_id)
        if stock_type is None:
            raise NotFoundError(f"StockType {stock_type_id} does not exist")
        if supplier_id is not None and self.db.get(Supplier, supplier_id) is None:
            raise NotFoundError(f"Supplier {supplier_id} does not exist")

        total_amount = round(float(quantity) * float(rate), 2)
        if amount_paid is None:
            amount_paid = total_amount
        if amount_paid < 0 or amount_paid > total_amount:
            raise ValidationError("amount_paid must be between 0 and the purchase total")

        purchase = Purchase(
            purchase_date=purchase_date,
            supplier_id=supplier_id,
            stock_type_id=stock_type_id,
            quantity=quantity,
            rate=rate,
            total_amount=total_amount,
            amount_paid=amount_paid,
            payment_method=payment_method,
            notes=notes,
            created_by=created_by,
        )
        self.db.add(purchase)
        self.db.commit()
        self.db.refresh(purchase)

        txn_dt = dt.datetime.combine(purchase_date, dt.datetime.now().time())
        posted_txn_ids: list[int] = []

        try:
            row = self.ledger.post_transaction(
                txn_datetime=txn_dt,
                txn_type=TxnType.PURCHASE,
                account=Account.STOCK,
                direction=Direction.IN,
                amount=quantity,
                stock_type_id=stock_type_id,
                supplier_id=supplier_id,
                reference_table="purchases",
                reference_id=purchase.id,
                description=f"Stock in: {quantity} {stock_type.unit}(s) {stock_type.name}",
                created_by=created_by,
            )
            posted_txn_ids.append(row["id"])

            if amount_paid > 0:
                account = Account.CASH if payment_method == PaymentMethod.CASH else Account.BANK
                row = self.ledger.post_transaction(
                    txn_datetime=txn_dt,
                    txn_type=TxnType.PURCHASE,
                    account=account,
                    direction=Direction.OUT,
                    amount=amount_paid,
                    stock_type_id=stock_type_id,
                    supplier_id=supplier_id,
                    reference_table="purchases",
                    reference_id=purchase.id,
                    description=f"Payment for purchase of {stock_type.name}",
                    created_by=created_by,
                )
                posted_txn_ids.append(row["id"])

            unpaid = round(total_amount - amount_paid, 2)
            if unpaid > 0:
                row = self.ledger.post_transaction(
                    txn_datetime=txn_dt,
                    txn_type=TxnType.PURCHASE,
                    account=Account.SUPPLIER_PAYABLE,
                    direction=Direction.IN,
                    amount=unpaid,
                    stock_type_id=stock_type_id,
                    supplier_id=supplier_id,
                    reference_table="purchases",
                    reference_id=purchase.id,
                    description=f"Amount owed to supplier for {stock_type.name}",
                    created_by=created_by,
                )
                posted_txn_ids.append(row["id"])
        except Exception:
            self.ledger.reverse_many(
                posted_txn_ids, reason=f"Compensating rollback: purchase of {stock_type.name} failed mid-post"
            )
            self.db.delete(purchase)
            self.db.commit()
            raise

        return purchase

    # ------------------------------------------------------------------
    # Adjustments
    # ------------------------------------------------------------------
    def record_adjustment(
        self,
        *,
        adjustment_date: dt.date,
        stock_type_id: int,
        quantity_delta: float,
        reason: str,
        notes: str | None = None,
        created_by: ActorType = ActorType.USER,
    ) -> StockAdjustment:
        if quantity_delta == 0:
            raise ValidationError("Adjustment quantity_delta cannot be zero")

        stock_type = self.db.get(StockType, stock_type_id)
        if stock_type is None:
            raise NotFoundError(f"StockType {stock_type_id} does not exist")

        adjustment = StockAdjustment(
            adjustment_date=adjustment_date,
            stock_type_id=stock_type_id,
            quantity_delta=quantity_delta,
            reason=reason,
            notes=notes,
            created_by=created_by,
        )
        self.db.add(adjustment)
        self.db.commit()
        self.db.refresh(adjustment)

        txn_dt = dt.datetime.combine(adjustment_date, dt.datetime.now().time())
        direction = Direction.IN if quantity_delta > 0 else Direction.OUT

        try:
            self.ledger.post_transaction(
                txn_datetime=txn_dt,
                txn_type=TxnType.STOCK_ADJUSTMENT,
                account=Account.STOCK,
                direction=direction,
                amount=abs(quantity_delta),
                stock_type_id=stock_type_id,
                reference_table="stock_adjustments",
                reference_id=adjustment.id,
                description=f"Stock adjustment ({reason}): {quantity_delta:+} {stock_type.unit}(s)",
                created_by=created_by,
            )
        except Exception:
            self.db.delete(adjustment)
            self.db.commit()
            raise

        # A recount adjustment is a signal the owner just physically
        # verified this stock type - clear the "stale count" flag.
        if reason.lower() in ("recount", "physical count", "stocktake"):
            stock_type.last_physical_count_date = adjustment_date
            self.db.commit()

        return adjustment

    def get_stock_snapshot(self, as_of: dt.date | None = None) -> list[dict]:
        stock_types = self.db.query(StockType).filter(StockType.is_active.is_(True)).all()
        return [
            {
                "stock_type_id": st.id,
                "name": st.name,
                "unit": st.unit,
                "quantity": self.ledger.get_stock_by_type(st.id, as_of=as_of),
                "last_physical_count_date": st.last_physical_count_date,
            }
            for st in stock_types
        ]
