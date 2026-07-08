import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin


class VlanSurveyRun(TimestampMixin, Base):
    """Ein VLAN-Survey-Lauf (Feature S63): das aggregierte Ergebnis als JSON-Blob.

    ``data`` = Ausgabe von :func:`netbuddy.services.vlan_survey.aggregate_survey`
    (pro Site die VLAN-Liste mit Namen/Gateways/DHCP/Trägern). Ein Lauf pro Zeile —
    der jüngste ist der angezeigte Stand; Historie bleibt für Vergleiche erhalten.
    """

    __tablename__ = "vlan_survey_run"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
