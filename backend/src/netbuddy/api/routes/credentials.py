import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialCreate(BaseModel):
    """Anlage einer SSH-Credential. Secrets werden via `EncryptedString` verschlüsselt abgelegt."""

    name: str
    username: str
    password: str | None = None
    enable_password: str | None = None
    ssh_port: int = 22


class CredentialRead(BaseModel):
    """Read-Sicht ohne Geheimnisse."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    username: str
    ssh_port: int
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
