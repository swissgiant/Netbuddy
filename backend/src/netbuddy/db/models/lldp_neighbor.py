import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin


class LldpNeighbor(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "lldp_neighbor"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    local_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    local_interface_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interface.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_chassis_id: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_port_id: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_port_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_system_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_system_description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
