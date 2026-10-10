"""Kategorie „Storage" — filter-/sortierbare Liste (CRUD).

Befüllt netzweit über :mod:`netbuddy.services.server_inventory` (Array-APIs, vCenter-Datastores,
NAS). Enthält nutzbaren und belegten Speicher, Disks, Anbindungen und Garantie.
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import HardwareStatus, Site, StorageDevice, StorageType, WarrantyStatus

router = APIRouter(prefix="/storage-devices", tags=["storage-devices"])


class StorageDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    dns_name: str | None
    site_id: uuid.UUID | None
    site_name: str | None = None
    storage_type: StorageType
    vendor: str | None
    model: str | None
    service_tag: str | None
    firmware: str | None
    hardware_status: HardwareStatus
    hardware_detail: str | None
    disk_count: int | None
    disks: list[dict[str, object]]
    capacity_raw_gb: int | None
    capacity_usable_gb: int | None
    capacity_used_gb: int | None
    mgmt_ip: str | None
    ip_addresses: list[str]
    protocols: list[str]
    connections: list[dict[str, object]]
    warranty_provider: str | None
    warranty_start: date | None
    warranty_end: date | None
    warranty_status: WarrantyStatus
    warranty_checked_at: datetime | None
    source: str | None
    last_seen: datetime | None
    notes: str | None
    created_at: datetime


class StorageDeviceCreate(BaseModel):
    name: str
    storage_type: StorageType = StorageType.UNKNOWN
    site_id: uuid.UUID | None = None
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    mgmt_ip: str | None = None
    notes: str | None = None


class StorageDeviceUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geändert."""

    name: str | None = None
    dns_name: str | None = None
    site_id: uuid.UUID | None = None
    storage_type: StorageType | None = None
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    firmware: str | None = None
    hardware_status: HardwareStatus | None = None
    hardware_detail: str | None = None
    disk_count: int | None = None
    capacity_raw_gb: int | None = None
    capacity_usable_gb: int | None = None
    capacity_used_gb: int | None = None
    mgmt_ip: str | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_status: WarrantyStatus | None = None
    notes: str | None = None


async def _site_names(session: SessionDep) -> dict[uuid.UUID, str]:
    return {sid: name for sid, name in (await session.execute(select(Site.id, Site.name))).all()}


def _read(row: StorageDevice, names: dict[uuid.UUID, str]) -> StorageDeviceRead:
    out = StorageDeviceRead.model_validate(row)
    out.mgmt_ip = str(row.mgmt_ip) if row.mgmt_ip else None
    out.site_name = names.get(row.site_id) if row.site_id else None
    return out


async def _get_or_404(session: SessionDep, row_id: uuid.UUID) -> StorageDevice:
    row = await session.get(StorageDevice, row_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storage nicht gefunden")
    return row


@router.get("", response_model=list[StorageDeviceRead])
async def list_storage_devices(session: SessionDep) -> list[StorageDeviceRead]:
    rows = (
        (
            await session.execute(
                select(StorageDevice)
                .where(StorageDevice.deleted_at.is_(None))
                .order_by(StorageDevice.name)
            )
        )
        .scalars()
        .all()
    )
    names = await _site_names(session)
    return [_read(r, names) for r in rows]


@router.post("", response_model=StorageDeviceRead, status_code=status.HTTP_201_CREATED)
async def create_storage_device(
    body: StorageDeviceCreate, session: SessionDep
) -> StorageDeviceRead:
    row = StorageDevice(**body.model_dump(), source="manual")
    session.add(row)
    await session.flush()
    return _read(row, await _site_names(session))


@router.patch("/{row_id}", response_model=StorageDeviceRead)
async def update_storage_device(
    row_id: uuid.UUID, body: StorageDeviceUpdate, session: SessionDep
) -> StorageDeviceRead:
    row = await _get_or_404(session, row_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    return _read(row, await _site_names(session))


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage_device(row_id: uuid.UUID, session: SessionDep) -> None:
    row = await _get_or_404(session, row_id)
    row.deleted_at = datetime.now().astimezone()
