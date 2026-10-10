"""Storage-/NAS-Gerät (Kategorie, als filter-/sortierbare Liste).

Umfasst Enterprise-Arrays (z.B. Huawei Dorado, Dell), NAS (Synology/QNAP/TrueNAS) und
Backup-Targets im ganzen Netz. Felder nach Alex' Vorgabe: Hersteller, Modell, Service-Tag,
Hardware-Status, Anzahl/Art der Disks, nutzbarer + belegter Speicher, IP-Adressen und
Anbindungen (Protokolle/Targets). Teilt die Enums :class:`HardwareStatus` und
:class:`WarrantyStatus` mit dem physischen Server.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.models.physical_server import HardwareStatus, WarrantyStatus
from netbuddy.db.types import enum_values


class StorageType(enum.StrEnum):
    ENTERPRISE_ARRAY = "enterprise_array"
    NAS = "nas"
    BACKUP_TARGET = "backup_target"
    SAN_SWITCH = "san_switch"
    UNKNOWN = "unknown"


class StorageDevice(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "storage_device"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dns_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id", ondelete="SET NULL"), nullable=True, index=True
    )
    storage_type: Mapped[StorageType] = mapped_column(
        Enum(StorageType, name="storage_type", values_callable=enum_values),
        nullable=False,
        server_default=StorageType.UNKNOWN.value,
    )

    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_tag: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    firmware: Mapped[str | None] = mapped_column(String(128), nullable=True)

    hardware_status: Mapped[HardwareStatus] = mapped_column(
        Enum(HardwareStatus, name="hardware_status", values_callable=enum_values),
        nullable=False,
        server_default=HardwareStatus.UNKNOWN.value,
    )
    hardware_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    disk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    capacity_raw_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_usable_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)  # nutzbar
    capacity_used_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)  # belegt

    mgmt_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    ip_addresses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    protocols: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    connections: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

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
            "uq_storage_device_service_tag_active",
            "service_tag",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND service_tag IS NOT NULL"),
        ),
    )
