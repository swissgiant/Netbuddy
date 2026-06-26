import uuid

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class UnifiHost(TimestampMixin, Base):
    """Eine UniFi-Konsole/Host aus der Cloud (api.ui.com) — pro Host ein An/Aus-Schalter.

    Die UniFi-„Sites" heißen bei BLS alle „default"; sinnvolle Gruppierung ist daher die
    Konsole/Host (BLS-UniFi-Sulgen, STEELCO-HQ TVCC, …). `enabled=False` → der Host wird beim
    Geräte-Import übersprungen (z.B. Steelco ohne Netzanbindung; später wieder einschaltbar).
    """

    __tablename__ = "unifi_host"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credential.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    host_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
