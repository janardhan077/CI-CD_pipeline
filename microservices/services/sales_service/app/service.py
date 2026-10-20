"""
SalesService - owns the `sales` table exclusively.

Business rule (unchanged from the monolith, project spec section 5,
"Sales"):
    Credit = Total Sale - Amount Received
This is enforced here, in exactly one place, and is NEVER accepted as
raw input - callers provide total_amount inputs and what was actually
received; credit_amount is always computed, never trusted.

A sale produces up to three ledger rows, posted through the Ledger
service (this service never touches ledger_transactions directly):
    1. STOCK_OUT              (always - stock leaves regardless of payment)
    2. SALE_CASH  (CASH IN)   (if any cash was received)
       and/or (BANK IN)       (if any bank portion was received)
    3. SALE_CREDIT (CUSTOMER_CREDIT IN)  (if total > received)

Consistency note: this service and the Ledger service each manage their
own database transaction (see common/ledger_client.py's docstring), so
there is no way to hold both open at once and commit them together -
and holding a LOCAL transaction open while making a blocking network
call to another service is a bad idea regardless (it ties up a DB lock
for the duration of an HTTP round trip). So the order here is:
    1. Commit the local Sale row FIRST (fast, releases the lock).
    2. Post the ledger rows that reference it.
    3. If any ledger post fails, reverse whichever ledger rows DID
       post, then delete the local Sale row - so a failed sale never
       lingers half-recorded in either place.
"""
import datetime as dt

from sqlalchemy.orm import Session

from common.core.enums import TxnType, Account, Direction, ActorType, PaymentMethod
from common.core.exceptions import ValidationError, NotFoundError, InsufficientStockError
from common.ledger_client import LedgerClient
from common.models.business import Sale
from common.models.master import Customer, StockType


class SalesService:
    def __init__(self, db: Session, ledger: LedgerClient | None = None):
        self.db = db
        self.ledger = ledger or LedgerClient()

    def record_sale(
        self,
        *,
        sale_date: dt.date,
        customer_id: int,
        stock_type_id: int,
        quantity: float,
        rate: float,
        cash_received: float = 0,
        bank_received: float = 0,
        unit: str = "bag",
        notes: str | None = None,
        allow_negative_stock: bool = False,
        created_by: ActorType = ActorType.USER,
    ) -> Sale:
        # --- validation ---------------------------------------------------
        if quantity <= 0:
            raise ValidationError("Sale quantity must be > 0")
        if rate < 0:
            raise ValidationError("Sale rate cannot be negative")
        if cash_received < 0 or bank_received < 0:
            raise ValidationError("Received amounts cannot be negative")

        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} does not exist")
        stock_type = self.db.get(StockType, stock_type_id)
        if stock_type is None:
            raise NotFoundError(f"StockType {stock_type_id} does not exist")

        total_amount = round(float(quantity) * float(rate), 2)
        amount_received = round(float(cash_received) + float(bank_received), 2)

        if amount_received > total_amount:
            raise ValidationError(
                f"Amount received ({amount_received}) cannot exceed sale total ({total_amount})"
            )

        # Business rule - the ONE place this formula is allowed to exist.
        credit_amount = round(total_amount - amount_received, 2)

        if not allow_negative_stock:
            current_stock = self.ledger.get_stock_by_type(stock_type_id)
            if current_stock - float(quantity) < 0:
                raise InsufficientStockError(
                    f"Selling {quantity} {unit}(s) of {stock_type.name} would take stock "
                    f"below zero (current: {current_stock}). Pass allow_negative_stock=True "
                    f"to override (e.g. stock count is known to be stale)."
                )

        if amount_received == total_amount:
            payment_method = PaymentMethod.BANK if cash_received == 0 else (
                PaymentMethod.CASH if bank_received == 0 else PaymentMethod.MIXED
            )
        elif amount_received == 0:
            payment_method = PaymentMethod.CREDIT
        else:
            payment_method = PaymentMethod.MIXED

        sale = Sale(
            sale_date=sale_date,
            customer_id=customer_id,
            stock_type_id=stock_type_id,
            quantity=quantity,
            unit=unit,
            rate=rate,
            total_amount=total_amount,
            cash_received=cash_received,
            bank_received=bank_received,
            amount_received=amount_received,
            credit_amount=credit_amount,
            payment_method=payment_method,
            notes=notes,
            created_by=created_by,
        )
        self.db.add(sale)
        self.db.commit()  # commit fast, before making any network calls
        self.db.refresh(sale)

        txn_dt = dt.datetime.combine(sale_date, dt.datetime.now().time())
        posted_txn_ids: list[int] = []

        try:
            # 1. Stock always leaves, regardless of payment status.
            row = self.ledger.post_transaction(
                txn_datetime=txn_dt,
                txn_type=TxnType.SALE_CASH if amount_received > 0 else TxnType.SALE_CREDIT,
                account=Account.STOCK,
                direction=Direction.OUT,
                amount=quantity,
                stock_type_id=stock_type_id,
                customer_id=customer_id,
                reference_table="sales",
                reference_id=sale.id,
                description=f"Stock out: {quantity} {unit}(s) {stock_type.name} sold to {customer.name}",
                created_by=created_by,
            )
            posted_txn_ids.append(row["id"])

            # 2. Cash / bank received.
            if cash_received > 0:
                row = self.ledger.post_transaction(
                    txn_datetime=txn_dt,
                    txn_type=TxnType.SALE_CASH,
                    account=Account.CASH,
                    direction=Direction.IN,
                    amount=cash_received,
                    customer_id=customer_id,
                    stock_type_id=stock_type_id,
                    reference_table="sales",
                    reference_id=sale.id,
                    description=f"Cash received for sale to {customer.name}",
                    created_by=created_by,
                )
                posted_txn_ids.append(row["id"])
            if bank_received > 0:
                row = self.ledger.post_transaction(
                    txn_datetime=txn_dt,
                    txn_type=TxnType.SALE_CASH,
                    account=Account.BANK,
                    direction=Direction.IN,
                    amount=bank_received,
                    customer_id=customer_id,
                    stock_type_id=stock_type_id,
                    reference_table="sales",
                    reference_id=sale.id,
                    description=f"Bank amount received for sale to {customer.name}",
                    created_by=created_by,
                )
                posted_txn_ids.append(row["id"])

            # 3. Any shortfall becomes customer credit.
            if credit_amount > 0:
                row = self.ledger.post_transaction(
                    txn_datetime=txn_dt,
                    txn_type=TxnType.SALE_CREDIT,
                    account=Account.CUSTOMER_CREDIT,
                    direction=Direction.IN,
                    amount=credit_amount,
                    customer_id=customer_id,
                    stock_type_id=stock_type_id,
                    reference_table="sales",
                    reference_id=sale.id,
                    description=f"Credit extended to {customer.name}",
                    created_by=created_by,
                )
                posted_txn_ids.append(row["id"])
        except Exception:
            # A ledger call failed partway through - undo whichever
            # ledger rows we DID manage to post, then delete the
            # already-committed local Sale row so it doesn't linger
            # as a sale with no corresponding stock/money movement.
            self.ledger.reverse_many(
                posted_txn_ids, reason=f"Compensating rollback: sale for {customer.name} failed mid-post"
            )
            self.db.delete(sale)
            self.db.commit()
            raise

        return sale

    def list_sales(self, *, sale_date: dt.date | None = None) -> list[Sale]:
        """Read-only listing, used by the Report service (daily
        aggregation) and the Assistant service (query_sales_total) -
        neither of which touches this service's database directly."""
        query = self.db.query(Sale)
        if sale_date is not None:
            query = query.filter(Sale.sale_date == sale_date)
        return query.order_by(Sale.sale_date, Sale.id).all()
