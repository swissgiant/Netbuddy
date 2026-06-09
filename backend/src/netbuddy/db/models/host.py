import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class ArpEntry(TimestampMixin, Base):
    """ARP-Eintrag (IP↔MAC), je Gerät pro Discovery-Lauf ersetzt. Basis für Namensauflösung."""

    __tablename__ = "arp_entry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # kanonisch (12 hex)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Host(TimestampMixin, Base):
    """Korreliertes Endgerät: MAC ↔ IP (aus ARP) ↔ Name (aus DNS). Keyed per kanonischer MAC."""

    __tablename__ = "host"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    mac: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
