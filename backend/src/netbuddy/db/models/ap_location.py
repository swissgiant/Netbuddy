import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class ApLocation(TimestampMixin, Base):
    """Letzter bekannter Aufenthaltsort eines UniFi-APs (Switch + Port) — **sticky**.

    Korreliert die UniFi-Cloud (welcher AP, online/offline) mit der switch-seitigen
    LLDP-/MAC-Sicht (an welchem Switch-Port hängt er). Bewusst persistent und sticky: geht ein
    AP offline (kein Strom → kein Link → kein LLDP), verlieren die Discovery-Tabellen seinen
    Port — diese Zeile behält ihn, damit die PoE-Recovery weiß, **welchen** Port sie bouncen
    muss. Dient zugleich der Topologie/Inventar-Anzeige ("was hängt wo"). Ein Eintrag je AP-MAC.
    """

    __tablename__ = "ap_location"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    ap_mac: Mapped[str] = mapped_column(String(12), nullable=False, unique=True, index=True)
    ap_name: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    ap_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ap_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")

    # Switch + Port, an dem der AP gesehen wurde (null, solange nie verortet, z.B. reiner Mesh-AP).
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device.id", ondelete="SET NULL"), nullable=True, index=True
    )
    port: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # lldp | mac

    # Mesh-Verdacht: online, aber an keinem Wired-Port gesehen, ODER mehrere APs an einem Port.
    mesh: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    located_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
