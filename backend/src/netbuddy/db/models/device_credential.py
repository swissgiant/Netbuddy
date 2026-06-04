import enum
import uuid

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class CredentialProtocol(enum.StrEnum):
    SSH = "ssh"
    SNMP = "snmp"
    API = "api"  # HTTP/JSON-API-Adapter (UniFi/Meraki/Forti/Cato)


class DeviceCredential(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "device_credential"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device.id", ondelete="CASCADE"),
        primary_key=True,
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credential.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    protocol: Mapped[CredentialProtocol] = mapped_column(
        Enum(CredentialProtocol, name="credential_protocol", values_callable=enum_values),
        primary_key=True,
    )
