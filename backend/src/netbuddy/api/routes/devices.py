import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, IPvAnyAddress
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Device, DeviceType

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceRead(BaseModel):
    """Read-Schema für ein Gerät — entspricht der DB-Sicht ohne interne Soft-Delete-Felder."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    mgmt_ip: IPvAnyAddress
    vendor: str
    model: str | None
    os_version: str | None
    serial_number: str | None
    device_type: DeviceType
    adapter_id: str
    capabilities: list[str]
    enabled: bool
    first_seen: datetime
    last_seen: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Sequence[Device]:
    """Listet aktive (nicht soft-gelöschte) Geräte, alphabetisch nach Hostname."""
    stmt = (
        select(Device)
        .where(Device.deleted_at.is_(None))
        .order_by(Device.hostname)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(device_id: uuid.UUID, session: SessionDep) -> Device:
    """Liefert ein einzelnes aktives Gerät oder 404, wenn es nicht existiert."""
    stmt = select(Device).where(
        Device.id == device_id,
        Device.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gerät nicht gefunden",
        )
    return device
