import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential, SnmpVersion

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialCreate(BaseModel):
    """Anlage einer Credential (SSH **oder** API). Secrets via `EncryptedString` verschlüsselt.

    SSH: `username` (+ `password`/`enable_password`/`ssh_port`). API (UniFi/Meraki/…):
    `base_url` + `api_token` (+ `extra`, z.B. `{"site": "default"}`).
    """

    name: str
    username: str | None = None
    password: str | None = None
    enable_password: str | None = None
    ssh_port: int = 22
    base_url: str | None = None
    api_token: str | None = None
    snmp_community: str | None = None
    snmp_version: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str | None) -> str | None:
        """`10.0.0.1:10443` → `https://10.0.0.1:10443`; ohne Host/IP → Fehler statt 500 später."""
        if value is None or not value.strip():
            return None
        url = value.strip().rstrip("/")
        if not re.match(r"^https?://", url):
            url = f"https://{url}"
        if not re.match(r"^https?://[\w.\-]+(:\d+)?(/.*)?$", url):
            raise ValueError(f"base_url sieht nicht nach einer URL aus: {value!r}")
        return url


def credential_kind(credential: Credential) -> str:
    """Anzeige-Typ: api (base_url) / telnet (Port 23 oder explizites Flag) / ssh."""
    if credential.base_url:
        return "api"
    explicit = str((credential.extra or {}).get("transport", "")).lower()
    if explicit == "telnet" or (not explicit and credential.ssh_port == 23):
        return "telnet"
    return "ssh"


class CredentialRead(BaseModel):
    """Read-Sicht ohne Geheimnisse (SSH-, Telnet- und API-Credentials)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    username: str | None  # API-Credentials haben keinen Username
    ssh_port: int
    base_url: str | None  # gesetzt = API-Credential
    extra: dict[str, Any] = {}
    snmp_version: str | None = None
    kind: str = "ssh"  # "ssh" | "telnet" | "api" (Anzeige)
    has_password: bool = False
    has_api_token: bool = False
    has_snmp_community: bool = False
    created_at: datetime


def _to_read(credential: Credential) -> CredentialRead:
    read = CredentialRead.model_validate(credential)
    read.kind = credential_kind(credential)
    read.snmp_version = credential.snmp_version.value if credential.snmp_version else None
    read.has_password = credential.password is not None
    read.has_api_token = credential.api_token is not None
    read.has_snmp_community = credential.snmp_community is not None
    return read


class CredentialUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geaendert. Secrets leer lassen = unveraendert."""

    name: str | None = None
    username: str | None = None
    password: str | None = None
    enable_password: str | None = None
    ssh_port: int | None = None
    base_url: str | None = None
    api_token: str | None = None
    snmp_community: str | None = None
    snmp_version: str | None = None
    extra: dict[str, Any] | None = None


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(body: CredentialCreate, session: SessionDep) -> CredentialRead:
    """Legt eine Credential an (SSH/Telnet/API; Geheimnisse verschlüsselt)."""
    credential = Credential(
        name=body.name,
        username=body.username,
        password=body.password,
        enable_password=body.enable_password,
        ssh_port=body.ssh_port,
        base_url=body.base_url,
        api_token=body.api_token,
        snmp_community=body.snmp_community,
        snmp_version=SnmpVersion(body.snmp_version) if body.snmp_version else None,
        extra=body.extra,
    )
    session.add(credential)
    await session.flush()
    return _to_read(credential)


@router.get("", response_model=list[CredentialRead])
async def list_credentials(session: SessionDep) -> list[CredentialRead]:
    """Listet aktive Credentials (ohne Geheimnisse)."""
    stmt = select(Credential).where(Credential.deleted_at.is_(None)).order_by(Credential.name)
    result = await session.execute(stmt)
    return [_to_read(c) for c in result.scalars().all()]


@router.patch("/{credential_id}", response_model=CredentialRead)
async def update_credential(
    credential_id: uuid.UUID, body: CredentialUpdate, session: SessionDep
) -> CredentialRead:
    """Aendert eine Credential (nur gesetzte Felder; leere Secrets bleiben unveraendert)."""
    stmt = select(Credential).where(Credential.id == credential_id, Credential.deleted_at.is_(None))
    credential = (await session.execute(stmt)).scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential nicht gefunden"
        )
    fields = body.model_dump(exclude_unset=True)
    for key in ("password", "enable_password", "api_token", "snmp_community"):
        if key in fields and not fields[key]:
            fields.pop(key)
    if fields.get("base_url"):
        fields["base_url"] = CredentialCreate._normalize_base_url(fields["base_url"])
    if "snmp_version" in fields:
        fields["snmp_version"] = (
            SnmpVersion(fields["snmp_version"]) if fields["snmp_version"] else None
        )
    for key, value in fields.items():
        setattr(credential, key, value)
    await session.flush()
    return _to_read(credential)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(credential_id: uuid.UUID, session: SessionDep) -> None:
    """Entfernt eine Credential (Soft-Delete)."""
    stmt = select(Credential).where(Credential.id == credential_id, Credential.deleted_at.is_(None))
    credential = (await session.execute(stmt)).scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential nicht gefunden"
        )
    credential.deleted_at = datetime.now(UTC)
