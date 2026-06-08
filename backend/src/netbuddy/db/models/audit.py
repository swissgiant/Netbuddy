import uuid
from typing import Any

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class AuditLog(TimestampMixin, Base):
    """Audit-Eintrag: wer hat was getan (verändernde Aktionen)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)  # Username
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # z.B. "device.create"
    target: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
