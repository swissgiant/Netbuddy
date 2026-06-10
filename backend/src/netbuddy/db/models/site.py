import uuid

from sqlalchemy import Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin


class Site(TimestampMixin, SoftDeleteMixin, Base):
    """Standort/Lokation (z.B. Cusano, Slovenia, Sulgen). Geräte gehören optional zu einem Site."""

    __tablename__ = "site"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Namens→IP-Regel des Standorts, z.B. "10.120.10.{n}": {n} = Endnummer des Gerätenamens
    # (BLS-SW-51 → 10.120.10.51). Optional — nur wo der Kunde diese Logik wirklich lebt.
    mgmt_ip_template: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index(
            "uq_site_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
