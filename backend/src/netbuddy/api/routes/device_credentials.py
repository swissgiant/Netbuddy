import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential, CredentialProtocol, DeviceCredential

router = APIRouter(prefix="/device-credentials", tags=["device-credentials"])


class DeviceCredentialRow(BaseModel):
    device_id: uuid.UUID
    credential_id: uuid.UUID
    protocol: CredentialProtocol
    credential_name: str


@router.get("", response_model=list[DeviceCredentialRow])
async def list_device_credentials(session: SessionDep) -> list[DeviceCredentialRow]:
    """Alle aktiven Gerät↔Credential-Verknüpfungen (für die Geräte-Ansicht im GUI)."""
    stmt = (
        select(DeviceCredential, Credential.name)
        .join(Credential, Credential.id == DeviceCredential.credential_id)
        .where(DeviceCredential.deleted_at.is_(None), Credential.deleted_at.is_(None))
    )
    rows = (await session.execute(stmt)).all()
    return [
        DeviceCredentialRow(
            device_id=link.device_id,
            credential_id=link.credential_id,
            protocol=link.protocol,
            credential_name=name,
        )
        for link, name in rows
    ]
