"""
Master/reference data.

These tables hold "who/what" - they never hold running balances.
Balances are always derived from app.models.ledger.LedgerTransaction.
"""
import datetime as dt

from sqlalchemy import String, Boolean, Numeric, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base
from common.models.base import IntPKMixin, TimestampMixin


class Customer(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # NOTE (ambiguity #7 from discovery doc): two customers can share a
    # display name (e.g. "Jai", "Subhan" appeared twice in sample data).
    # We do NOT deduplicate by name. Until the owner confirms whether
    # duplicates are the same person, each is a distinct customer row;
    # `disambiguator` lets the owner tell them apart in the UI/AI
    # (e.g. "Jai - Market Street" vs "Jai - Transport").
    disambiguator: Mapped[str | None] = mapped_column(String(60), nullable=True)

    opening_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    opening_balance_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sales = relationship("Sale", back_populates="customer")
    credit_payments = relationship("CreditPayment", back_populates="customer")


class Supplier(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    purchases = relationship("Purchase", back_populates="supplier")


class StockType(Base, IntPKMixin, TimestampMixin):
    """A product/grade of onion - e.g. Mayur, MK, MR.

    NOTE (ambiguity #5): we do not yet know whether these represent
    brand, grade, or variety. Modeling them as a flat, owner-managed
    lookup table means it doesn't matter for the schema - the owner
    can name them whatever makes sense, and we can add a `category`
    field later without a breaking migration if a second dimension
    (e.g. supplier brand vs. size grade) turns out to be needed.
    """
    __tablename__ = "stock_types"

    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="bag", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Set true whenever a physical recount is skipped for this type on a
    # given day (discovery ambiguity #6: "MR: not counted"). This is
    # about the LAST COUNT DATE, not the running derived balance -
    # it just flags "the owner hasn't visually verified this recently"
    # so the dashboard can show a staleness warning instead of quietly
    # trusting a number nobody actually checked.
    last_physical_count_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class ExpenseCategory(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
