import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class ValidationCheck(TimestampMixin, Base):
    """Ergebnis einer read-only Profil-Validierung einer Capability gegen ein echtes Gerät.

    Pro `(device_id, capability)` existiert genau eine Zeile (letzter Lauf gewinnt). `raw_excerpt`
    hält den rohen CLI-Output als Referenz-Capture; `detail` die Feld-Abdeckung + Meldung.
    Status ist ein String (``ok`` / ``empty`` / ``error``) — passend zu
    :class:`netbuddy.services.validation.CapabilityStatus`.
    """

    __tablename__ = "validation_check"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    adapter_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    command: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("device_id", "capability", name="uq_validation_dev_cap"),)
