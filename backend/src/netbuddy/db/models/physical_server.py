"""Physischer Server (Kategorie, als filter-/sortierbare Liste).

Umfasst **alle** physischen Server im ganzen Netz (nicht nur BLS): ESXi-/Hypervisor-Hosts ebenso
wie Bare-Metal und Appliances. Befüllt wird netzweit aus mehreren Quellen (vCenter-Hosts,
iDRAC/iLO via Redfish, Discovery/ARP/DNS); Hardware-/Garantie-Felder werden angereichert.
Die Garantie (Service-Beginn/-Ende) kommt über den Service-Tag von der Hersteller-API
(Dell/HPE), siehe :mod:`netbuddy.services.warranty`.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class ServerRole(enum.StrEnum):
    ESXI_HOST = "esxi_host"
    HYPERV_HOST = "hyperv_host"
    BARE_METAL = "bare_metal"
    APPLIANCE = "appliance"
    UNKNOWN = "unknown"


class HardwareStatus(enum.StrEnum):
    """Hardware-Gesundheit (Defekt-Spalte); auch von Storage genutzt."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class WarrantyStatus(enum.StrEnum):
    """Garantie-/Service-Status aus dem Hersteller-Lookup; auch von Storage genutzt."""

    ACTIVE = "active"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class PhysicalServer(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "physical_server"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    dns_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id", ondelete="SET NULL"), nullable=True, index=True
    )
    server_role: Mapped[ServerRole] = mapped_column(
        Enum(ServerRole, name="server_role", values_callable=enum_values),
        nullable=False,
        server_default=ServerRole.UNKNOWN.value,
    )

    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_tag: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    cpu_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cpu_sockets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_threads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    os_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(128), nullable=True)

    mgmt_ip: Mapped[str | None] = mapped_column(INET, nullable=True)  # iDRAC/iLO/BMC
    oob_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reachable_ip: Mapped[str | None] = mapped_column(INET, nullable=True)  # Cato-erreichbar
    ip_addresses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    hardware_status: Mapped[HardwareStatus] = mapped_column(
        Enum(HardwareStatus, name="hardware_status", values_callable=enum_values),
        nullable=False,
        server_default=HardwareStatus.UNKNOWN.value,
    )
    hardware_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    warranty_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warranty_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_status: Mapped[WarrantyStatus] = mapped_column(
        Enum(WarrantyStatus, name="warranty_status", values_callable=enum_values),
        nullable=False,
        server_default=WarrantyStatus.UNKNOWN.value,
    )
    warranty_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_physical_server_service_tag_active",
            "service_tag",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND service_tag IS NOT NULL"),
        ),
    )
