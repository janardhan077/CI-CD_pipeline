"""
The ledger. This is the ONLY table that balances are ever derived from.

Design intent (per project spec section 6 and 17):
  - No table anywhere stores an editable "current_balance" column.
  - Every cash/bank/stock/credit change is a row here.
  - Rows are insert-only from the app's perspective. Corrections are made
    by inserting a REVERSAL row that references the original, never by
    UPDATE or DELETE on a posted row (see AuditLog for the rare
    authorized exception path).
"""
import datetime as dt

from sqlalchemy import String, Numeric, DateTime, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base
from common.models.base import IntPKMixin, TimestampMixin
from common.core.enums import TxnType, Account, Direction, ActorType


class LedgerTransaction(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        Index("ix_ledger_date_account", "txn_datetime", "account"),
        Index("ix_ledger_customer", "customer_id"),
        Index("ix_ledger_stock_type", "stock_type_id"),
    )

    txn_datetime: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)
    txn_type: Mapped[TxnType] = mapped_column(SAEnum(TxnType), nullable=False)
    account: Mapped[Account] = mapped_column(SAEnum(Account), nullable=False)
    direction: Mapped[Direction] = mapped_column(SAEnum(Direction), nullable=False)

    # Amount is always stored positive; `direction` carries the sign.
    # For STOCK account rows, amount is a quantity, not currency.
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    stock_type_id: Mapped[int | None] = mapped_column(ForeignKey("stock_types.id"), nullable=True)

    # Loose link back to the business-facing record that caused this
    # ledger row (a Sale, Expense, CreditPayment, etc.), so the UI can
    # answer "why is cash X" by tracing back to a human-readable record.
    reference_table: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(nullable=True)

    # If this row reverses an earlier one, point at it. The original
    # row is never deleted or edited - it stays for audit purposes,
    # and this reversal cancels its effect in all balance queries.
    reverses_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_transactions.id"), nullable=True
    )

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[ActorType] = mapped_column(SAEnum(ActorType), nullable=False)

    customer = relationship("Customer")
    supplier = relationship("Supplier")
    stock_type = relationship("StockType")
    reverses = relationship("LedgerTransaction", remote_side="LedgerTransaction.id")
