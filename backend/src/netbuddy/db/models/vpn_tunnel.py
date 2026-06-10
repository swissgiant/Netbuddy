import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class VpnTunnel(TimestampMixin, Base):
    """Site-to-Site-VPN-Tunnel, gelesen von einer Firewall (pro Discovery-Lauf ersetzt).

    `local_subnets`/`remote_subnets` (IPsec-Selektoren) erlauben das Mapping auf Standorte:
    Tunnel der FW in Site A, dessen remote_subnets in Site Bs Segmenten liegen → Kante A↔B.
    """

    __tablename__ = "vpn_tunnel"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    remote_gateway: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_up: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Vom Admin steuerbar: Partner-/Lieferanten-Tunnel auf False → fließen nicht in die
    # Topologie (und später nicht in die VLAN-Orchestrierung) ein. Überlebt Discovery-Läufe.
    relevant: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    local_subnets: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    remote_subnets: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
