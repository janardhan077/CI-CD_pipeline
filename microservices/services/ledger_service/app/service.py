"""
The Ledger Engine - now its own microservice.

THIS IS THE ONLY CODE PATH ALLOWED TO CREATE LedgerTransaction ROWS,
now enforced at a process/network boundary rather than just by
convention: no other service imports this module or touches the
ledger_transactions table directly - they call this service's HTTP
API via common.ledger_client.LedgerClient.

Business logic below is unchanged from the monolith's LedgerService.
"""
import datetime as dt

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from common.core.enums import TxnType, Account, Direction, ActorType
from common.core.exceptions import ValidationError, NotFoundError
from common.models.ledger import LedgerTransaction
from common.models.master import Customer, StockType


class LedgerService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def post_transaction(
        self,
        *,
        txn_datetime: dt.datetime,
        txn_type: TxnType,
        account: Account,
        direction: Direction,
        amount: float,
        customer_id: int | None = None,
        supplier_id: int | None = None,
        stock_type_id: int | None = None,
        reference_table: str | None = None,
        reference_id: int | None = None,
        description: str | None = None,
        created_by: ActorType = ActorType.USER,
    ) -> LedgerTransaction:
        if amount is None or amount < 0:
            raise ValidationError(f"Ledger amount must be >= 0, got {amount!r}")
        if amount == 0:
            raise ValidationError("Refusing to post a zero-amount ledger transaction")

        if customer_id is not None and self.db.get(Customer, customer_id) is None:
            raise NotFoundError(f"Customer {customer_id} does not exist")
        if stock_type_id is not None and self.db.get(StockType, stock_type_id) is None:
            raise NotFoundError(f"StockType {stock_type_id} does not exist")

        row = LedgerTransaction(
            txn_datetime=txn_datetime,
            txn_type=txn_type,
            account=account,
            direction=direction,
            amount=amount,
            customer_id=customer_id,
            supplier_id=supplier_id,
            stock_type_id=stock_type_id,
            reference_table=reference_table,
            reference_id=reference_id,
            description=description,
            created_by=created_by,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def reverse_transaction(
        self, original_id: int, *, reason: str, created_by: ActorType = ActorType.USER
    ) -> LedgerTransaction:
        original = self.db.get(LedgerTransaction, original_id)
        if original is None:
            raise NotFoundError(f"LedgerTransaction {original_id} does not exist")

        opposite_direction = Direction.OUT if original.direction == Direction.IN else Direction.IN

        reversal = LedgerTransaction(
            txn_datetime=dt.datetime.now(dt.timezone.utc),
            txn_type=TxnType.REVERSAL,
            account=original.account,
            direction=opposite_direction,
            amount=original.amount,
            customer_id=original.customer_id,
            supplier_id=original.supplier_id,
            stock_type_id=original.stock_type_id,
            reference_table=original.reference_table,
            reference_id=original.reference_id,
            reverses_txn_id=original.id,
            description=f"Reversal of txn #{original.id}: {reason}",
            created_by=created_by,
        )
        self.db.add(reversal)
        self.db.commit()
        self.db.refresh(reversal)
        return reversal

    # ------------------------------------------------------------------
    # Reading / derivation
    # ------------------------------------------------------------------
    def _account_balance(
        self, account: Account, *, as_of: dt.date | None = None, since: dt.date | None = None
    ) -> float:
        in_sum = select(func.coalesce(func.sum(LedgerTransaction.amount), 0)).where(
            LedgerTransaction.account == account, LedgerTransaction.direction == Direction.IN
        )
        out_sum = select(func.coalesce(func.sum(LedgerTransaction.amount), 0)).where(
            LedgerTransaction.account == account, LedgerTransaction.direction == Direction.OUT
        )
        if as_of is not None:
            end = dt.datetime.combine(as_of, dt.time.max)
            in_sum = in_sum.where(LedgerTransaction.txn_datetime <= end)
            out_sum = out_sum.where(LedgerTransaction.txn_datetime <= end)
        if since is not None:
            start = dt.datetime.combine(since, dt.time.min)
            in_sum = in_sum.where(LedgerTransaction.txn_datetime >= start)
            out_sum = out_sum.where(LedgerTransaction.txn_datetime >= start)

        total_in = self.db.scalar(in_sum) or 0
        total_out = self.db.scalar(out_sum) or 0
        return float(total_in) - float(total_out)

    def get_cash_balance(self, as_of: dt.date | None = None) -> float:
        return self._account_balance(Account.CASH, as_of=as_of)

    def get_bank_balance(self, as_of: dt.date | None = None) -> float:
        return self._account_balance(Account.BANK, as_of=as_of)

    def get_total_stock(self, as_of: dt.date | None = None) -> float:
        return self._account_balance(Account.STOCK, as_of=as_of)

    def get_stock_by_type(self, stock_type_id: int, as_of: dt.date | None = None) -> float:
        in_sum = select(func.coalesce(func.sum(LedgerTransaction.amount), 0)).where(
            LedgerTransaction.account == Account.STOCK,
            LedgerTransaction.direction == Direction.IN,
            LedgerTransaction.stock_type_id == stock_type_id,
        )
        out_sum = select(func.coalesce(func.sum(LedgerTransaction.amount), 0)).where(
            LedgerTransaction.account == Account.STOCK,
            LedgerTransaction.direction == Direction.OUT,
            LedgerTransaction.stock_type_id == stock_type_id,
        )
        if as_of is not None:
            end = dt.datetime.combine(as_of, dt.time.max)
            in_sum = in_sum.where(LedgerTransaction.txn_datetime <= end)
            out_sum = out_sum.where(LedgerTransaction.txn_datetime <= end)
        total_in = self.db.scalar(in_sum) or 0
        total_out = self.db.scalar(out_sum) or 0
        return float(total_in) - float(total_out)

    def get_customer_outstanding(self, customer_id: int, as_of: dt.date | None = None) -> float:
        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} does not exist")

        in_sum = select(func.coalesce(func.sum(LedgerTransaction.amount), 0)).where(
            LedgerTransaction.account == Account.CUSTOMER_CREDIT,
            LedgerTransaction.direction == Direction.IN,
            LedgerTransaction.customer_id == customer_id,
        )
        out_sum = select(func.coalesce(func.sum(LedgerTransaction.amount), 0)).where(
            LedgerTransaction.account == Account.CUSTOMER_CREDIT,
            LedgerTransaction.direction == Direction.OUT,
            LedgerTransaction.customer_id == customer_id,
        )
        if as_of is not None:
            end = dt.datetime.combine(as_of, dt.time.max)
            in_sum = in_sum.where(LedgerTransaction.txn_datetime <= end)
            out_sum = out_sum.where(LedgerTransaction.txn_datetime <= end)

        total_in = self.db.scalar(in_sum) or 0
        total_out = self.db.scalar(out_sum) or 0
        return float(customer.opening_balance) + float(total_in) - float(total_out)

    def get_transaction(self, transaction_id: int) -> LedgerTransaction:
        txn = self.db.get(LedgerTransaction, transaction_id)
        if txn is None:
            raise NotFoundError(f"LedgerTransaction {transaction_id} does not exist")
        return txn

    def get_transactions_for(
        self, *, reference_table: str, reference_id: int
    ) -> list[LedgerTransaction]:
        stmt = select(LedgerTransaction).where(
            LedgerTransaction.reference_table == reference_table,
            LedgerTransaction.reference_id == reference_id,
        )
        return list(self.db.scalars(stmt))

    def get_transactions_between(
        self, start: dt.date, end: dt.date, account: Account | None = None
    ) -> list[LedgerTransaction]:
        stmt = select(LedgerTransaction).where(
            LedgerTransaction.txn_datetime >= dt.datetime.combine(start, dt.time.min),
            LedgerTransaction.txn_datetime <= dt.datetime.combine(end, dt.time.max),
        )
        if account is not None:
            stmt = stmt.where(LedgerTransaction.account == account)
        stmt = stmt.order_by(LedgerTransaction.txn_datetime)
        return list(self.db.scalars(stmt))
