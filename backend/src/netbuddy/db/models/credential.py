import enum
import uuid
from typing import Any

from sqlalchemy import Enum, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import EncryptedString, enum_values


class SnmpVersion(enum.StrEnum):
    V1 = "v1"
    V2C = "v2c"
    V3 = "v3"


class SnmpAuthProtocol(enum.StrEnum):
    MD5 = "md5"
    SHA = "sha"


class SnmpPrivProtocol(enum.StrEnum):
    DES = "des"
    AES = "aes"


class Credential(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "credential"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # SSH/CLI: username Pflicht in der Praxis; nullable, da API-Credentials nur Token nutzen.
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    enable_password: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    ssh_port: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("22"),
    )

    # API-Credentials (UniFi/Meraki/Forti/Cato): Basis-URL + verschlüsseltes Token + Extra
    # (z.B. site/org/vdom). `extra` ist frei nutzbar je API-Adapter.
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_token: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    snmp_community: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    snmp_version: Mapped[SnmpVersion | None] = mapped_column(
        Enum(SnmpVersion, name="snmp_version", values_callable=enum_values),
        nullable=True,
    )
    snmpv3_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snmpv3_auth_protocol: Mapped[SnmpAuthProtocol | None] = mapped_column(
        Enum(SnmpAuthProtocol, name="snmp_auth_protocol", values_callable=enum_values),
        nullable=True,
    )
    snmpv3_auth_key: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    snmpv3_priv_protocol: Mapped[SnmpPrivProtocol | None] = mapped_column(
        Enum(SnmpPrivProtocol, name="snmp_priv_protocol", values_callable=enum_values),
        nullable=True,
    )
    snmpv3_priv_key: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    __table_args__ = (
        Index(
            "uq_credential_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
