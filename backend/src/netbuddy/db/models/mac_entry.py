import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import MACADDR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class MacEntryType(enum.StrEnum):
    DYNAMIC = "dynamic"
    STATIC = "static"
    SECURE = "secure"


class MacAddressEntry(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "mac_address_entry"

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
    interface_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interface.id", ondelete="CASCADE"),
        nullable=False,
    )
    mac_address: Mapped[str] = mapped_column(MACADDR(), nullable=False, index=True)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_type: Mapped[MacEntryType] = mapped_column(
        Enum(MacEntryType, name="mac_entry_type", values_callable=enum_values),
        nullable=False,
        server_default=text("'dynamic'"),
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
