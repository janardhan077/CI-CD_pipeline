"""
Business-facing records.

These are the human-readable "documents" (a sale, an expense, a
purchase...) that a user or the AI creates. Each one, when posted,
generates one or more LedgerTransaction rows - the business record
itself is NEVER treated as authoritative for balances. It exists so
the UI has something friendlier than raw ledger rows to display and
edit (within the append-only rules enforced by the service layer).
"""
import datetime as dt

from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, Enum as SAEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base
from common.models.base import IntPKMixin, TimestampMixin
from common.core.enums import PaymentMethod, ActorType


class Sale(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "sales"

    sale_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    stock_type_id: Mapped[int] = mapped_column(ForeignKey("stock_types.id"), nullable=False)

    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="bag", nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # NOTE (ambiguity #8 from discovery doc): can the paid portion of a
    # single sale be split across cash and bank? Answered here with the
    # more general/safer default: yes. cash_received and bank_received
    # are independent; amount_received is always their sum (enforced
    # by SalesService, never accepted as raw input). If it later turns
    # out splits never happen in practice, this still works fine with
    # one of the two always being zero - no migration needed either way.
    cash_received: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    bank_received: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    amount_received: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    # Stored (not just derived) for fast listing/reporting, but it is
    # ALWAYS recomputed as total_amount - amount_received by the
    # service layer - never accepted as raw input. See SalesService.
    credit_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    payment_method: Mapped[PaymentMethod] = mapped_column(SAEnum(PaymentMethod), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[ActorType] = mapped_column(SAEnum(ActorType), default=ActorType.USER, nullable=False)

    customer = relationship("Customer", back_populates="sales")
    stock_type = relationship("StockType")


class Purchase(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "purchases"

    purchase_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    stock_type_id: Mapped[int] = mapped_column(ForeignKey("stock_types.id"), nullable=False)

    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="bag", nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    amount_paid: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(SAEnum(PaymentMethod), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[ActorType] = mapped_column(SAEnum(ActorType), default=ActorType.USER, nullable=False)

    supplier = relationship("Supplier", back_populates="purchases")
    stock_type = relationship("StockType")


class Expense(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "expenses"

    expense_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(SAEnum(PaymentMethod), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[ActorType] = mapped_column(SAEnum(ActorType), default=ActorType.USER, nullable=False)
    # Set when this expense is superseded by a correction (see
    # ExpenseService.correct_expense). The row is NEVER edited in
    # place or deleted after that point - it stays as the audit trail
    # for what was originally entered and why it changed.
    voided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    voided_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    category = relationship("ExpenseCategory")


class CreditPayment(Base, IntPKMixin, TimestampMixin):
    """A customer paying down existing credit - separate from a Sale."""
    __tablename__ = "credit_payments"

    payment_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(SAEnum(PaymentMethod), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[ActorType] = mapped_column(SAEnum(ActorType), default=ActorType.USER, nullable=False)

    customer = relationship("Customer", back_populates="credit_payments")


class StockAdjustment(Base, IntPKMixin, TimestampMixin):
    """Manual correction after a physical recount, damage, etc."""
    __tablename__ = "stock_adjustments"

    adjustment_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    stock_type_id: Mapped[int] = mapped_column(ForeignKey("stock_types.id"), nullable=False)
    quantity_delta: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # signed
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[ActorType] = mapped_column(SAEnum(ActorType), default=ActorType.USER, nullable=False)

    stock_type = relationship("StockType")
