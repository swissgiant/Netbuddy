import uuid

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class PoeEvent(TimestampMixin, Base):
    """Ein PoE-Recovery-Ereignis (Port-Bounce-Versuch) — für Audit, Rate-Limit und Root-Cause.

    Jeder manuelle oder vom Worker ausgelöste Bounce schreibt eine Zeile. ``action`` hält das
    Ergebnis (``recovered`` / ``no_change`` / ``skipped_ratelimit`` / ``error``). Über die Historie
    je ``(device_id, port)`` greift das Rate-Limit (nicht endlos einen hart-toten Port bouncen) und
    lässt sich später auswerten, ob Vorfälle auf bestimmten Switches/Ports/Zeiten clustern.
    """

    __tablename__ = "poe_event"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device.id", ondelete="CASCADE"), nullable=False, index=True
    )
    port: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ap_mac: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ap_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    status_before: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
