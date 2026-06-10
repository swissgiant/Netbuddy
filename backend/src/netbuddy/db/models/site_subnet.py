import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import CIDR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class SiteSubnet(TimestampMixin, Base):
    """IP-Segment eines Standorts (mehrere pro Site, z.B. Sulgen = 10.120.0.0/16).

    Macht die Standort-Zuordnung über die IP eindeutig (Geräte, Vorschläge, später VLANs)
    und ist die Basis, um VPN-Tunnel-Selektoren auf Standorte zu mappen.
    """

    __tablename__ = "site_subnet"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cidr: Mapped[str] = mapped_column(CIDR(), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
