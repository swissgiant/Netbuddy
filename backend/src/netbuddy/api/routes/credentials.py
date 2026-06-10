import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential

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


class CredentialRead(BaseModel):
    """Read-Sicht ohne Geheimnisse (SSH- und API-Credentials)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    username: str | None  # API-Credentials haben keinen Username
    ssh_port: int
    base_url: str | None  # gesetzt = API-Credential
    created_at: datetime


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(body: CredentialCreate, session: SessionDep) -> Credential:
    """Legt eine SSH-Credential an (Passwörter verschlüsselt)."""
    credential = Credential(
        name=body.name,
        username=body.username,
        password=body.password,
        enable_password=body.enable_password,
        ssh_port=body.ssh_port,
        base_url=body.base_url,
        api_token=body.api_token,
        extra=body.extra,
    )
    session.add(credential)
    await session.flush()
    return credential


@router.get("", response_model=list[CredentialRead])
async def list_credentials(session: SessionDep) -> Sequence[Credential]:
    """Listet aktive Credentials (ohne Geheimnisse)."""
    stmt = select(Credential).where(Credential.deleted_at.is_(None)).order_by(Credential.name)
    result = await session.execute(stmt)
    return result.scalars().all()


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
