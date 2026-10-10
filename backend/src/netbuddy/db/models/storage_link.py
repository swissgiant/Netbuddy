"""Verknüpfung Server ↔ Storage (Datenbasis für die 4. Kategorie: grafische Ansicht).

Jetzt angelegt, damit die spätere grafische Storage-Netz-Ansicht nur noch aus diesen Kanten
zeichnet. Ein Eintrag beschreibt, dass ein physischer **oder** virtueller Server ein Storage über
ein Protokoll (iSCSI/NFS/CIFS/FC/NVMe-oF) nutzt — mit optionalen Endpunkten/Pfaden.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class ServerKind(enum.StrEnum):
    PHYSICAL = "physical"
    VIRTUAL = "virtual"


class StorageLink(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "storage_link"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    server_kind: Mapped[ServerKind] = mapped_column(
        Enum(ServerKind, name="storage_server_kind", values_callable=enum_values), nullable=False
    )
    physical_server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("physical_server.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    virtual_server_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_server.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    storage_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("storage_device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    protocol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    server_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
