"""
Shared model mixins.
"""
import datetime as dt

from sqlalchemy import Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False
    )


class IntPKMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
