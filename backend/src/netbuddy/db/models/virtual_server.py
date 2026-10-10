"""Virtueller Server (Kategorie, als filter-/sortierbare Liste).

Befüllt netzweit aus allen erreichbaren vCentern (BLS, Belimed, B-SAG, Steelco). Hält die von
Alex gewünschten Felder: RAM, CPU, Virtualisierungs-Cluster/-Host, Disks, Netzwerkadressen.
Die Zuordnung zum physischen Host (ESXi) ist über :attr:`physical_server_id` referenzierbar; die
Datastores (:attr:`datastores`) sind die Brücke zur späteren grafischen Server-Storage-Ansicht.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class PowerState(enum.StrEnum):
    ON = "on"
    OFF = "off"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class VirtualServer(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "virtual_server"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dns_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id", ondelete="SET NULL"), nullable=True, index=True
    )
    power_state: Mapped[PowerState] = mapped_column(
        Enum(PowerState, name="power_state", values_callable=enum_values),
        nullable=False,
        server_default=PowerState.UNKNOWN.value,
    )

    vcpu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cluster: Mapped[str | None] = mapped_column(String(255), nullable=True)
    esxi_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    physical_server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("physical_server.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vcenter: Mapped[str | None] = mapped_column(String(255), nullable=True)

    guest_os: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vmware_tools: Mapped[str | None] = mapped_column(String(64), nullable=True)

    disk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_total_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    datastores: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    ip_addresses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    networks: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    vm_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_virtual_server_vm_uuid_active",
            "vm_uuid",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND vm_uuid IS NOT NULL"),
        ),
    )
