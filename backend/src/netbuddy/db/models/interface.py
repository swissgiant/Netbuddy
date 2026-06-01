import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import MACADDR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class AdminStatus(enum.StrEnum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class OperStatus(enum.StrEnum):
    UP = "up"
    DOWN = "down"
    TESTING = "testing"
    UNKNOWN = "unknown"


class Interface(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "interface"

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
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    if_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_status: Mapped[AdminStatus] = mapped_column(
        Enum(AdminStatus, name="if_admin_status", values_callable=enum_values),
        nullable=False,
        server_default=text("'unknown'"),
    )
    oper_status: Mapped[OperStatus] = mapped_column(
        Enum(OperStatus, name="if_oper_status", values_callable=enum_values),
        nullable=False,
        server_default=text("'unknown'"),
    )
    mac_address: Mapped[str | None] = mapped_column(MACADDR(), nullable=True)
    speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mtu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interface_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_polled: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "uq_interface_device_name_active",
            "device_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
