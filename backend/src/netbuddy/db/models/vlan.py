import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CIDR, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class Vlan(TimestampMixin, Base):
    """Eine zentral definierte VLAN (z.B. eines der 16 Test-Netze).

    Die VLAN-ID ist unternehmensweit eindeutig und an ALLEN Standorten gleich (z.B. VLAN 101 =
    Testnetz 1 überall) — das pro-Standort unterschiedliche Subnetz steht in :class:`VlanSubnet`.
    Basis für VLAN-Generierung (Switch-Ausrollen), Port-Zuweisung, FW-Kopplung und
    vCenter-Portgruppen.
    """

    __tablename__ = "vlan"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vlan_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class VlanSubnet(TimestampMixin, Base):
    """Das pro-Standort-Subnetz einer VLAN (gleiche VLAN-ID, je Site eigenes Netz + Gateway).

    Ein Eintrag je ``(vlan, site)``. Das Gateway liegt typischerweise auf der Standort-Firewall —
    Grundlage, um die Test-VLANs site-übergreifend über die FW zu koppeln.
    """

    __tablename__ = "vlan_subnet"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vlan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vlan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cidr: Mapped[str] = mapped_column(CIDR(), nullable=False)
    gateway: Mapped[str | None] = mapped_column(INET(), nullable=True)

    __table_args__ = (UniqueConstraint("vlan_id", "site_id", name="uq_vlan_subnet_vlan_site"),)
