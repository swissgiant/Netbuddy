"""vCenter-Server (Kategorie): Liste der vCenter mit Hosts/Clustern.

Ein Eintrag je vCenter (Version, Datacenter, Cluster inkl. Host-Zahl, Host-/VM-Zähler). Die
Detailinfos je Host/VM stehen in den Kategorien :class:`PhysicalServer`/:class:`VirtualServer`
(Feld ``vcenter``/``cluster``/``esxi_host``), sodass sich aus dieser Liste wieder dorthin
springen lässt. Befüllt aus :mod:`netbuddy.services.vcenter_inventory`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin


class Vcenter(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "vcenter"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credential.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    datacenters: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    clusters: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    hosts: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    host_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vm_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_vcenter_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
