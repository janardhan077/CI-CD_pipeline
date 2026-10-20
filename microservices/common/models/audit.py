"""
Audit log - records every create/update/delete/reverse action taken by
a user, the AI, or an import job, with enough detail to answer
"who changed what, when, and why."
"""
from sqlalchemy import String, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base
from common.models.base import IntPKMixin, TimestampMixin
from common.core.enums import ActorType, AuditAction


class AuditLog(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "audit_log"

    entity_table: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[AuditAction] = mapped_column(SAEnum(AuditAction), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(SAEnum(ActorType), nullable=False)
    actor_label: Mapped[str | None] = mapped_column(String(80), nullable=True)  # e.g. username, "ollama"
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
