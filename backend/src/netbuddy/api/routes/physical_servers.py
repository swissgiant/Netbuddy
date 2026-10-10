"""Kategorie „Physische Server" — filter-/sortierbare Liste (CRUD).

Befüllt netzweit über :mod:`netbuddy.services.server_inventory`; hier das Datenmodell-CRUD plus
manuelle Korrekturen (Hardware-Defekt markieren, Notizen, Standort, Garantie-Override).
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import (
    HardwareStatus,
    PhysicalServer,
    ServerRole,
    Site,
    WarrantyStatus,
)

router = APIRouter(prefix="/physical-servers", tags=["physical-servers"])


class PhysicalServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    dns_name: str | None
    site_id: uuid.UUID | None
    site_name: str | None = None
    server_role: ServerRole
    vendor: str | None
    model: str | None
    service_tag: str | None
    cpu_model: str | None
    cpu_sockets: int | None
    cpu_cores: int | None
    cpu_threads: int | None
    ram_mb: int | None
    os_name: str | None
    os_version: str | None
    mgmt_ip: str | None
    oob_type: str | None
    ip_addresses: list[str]
    hardware_status: HardwareStatus
    hardware_detail: str | None
    warranty_provider: str | None
    warranty_start: date | None
    warranty_end: date | None
    warranty_status: WarrantyStatus
    warranty_checked_at: datetime | None
    source: str | None
    last_seen: datetime | None
    notes: str | None
    created_at: datetime


class PhysicalServerCreate(BaseModel):
    hostname: str
    server_role: ServerRole = ServerRole.UNKNOWN
    site_id: uuid.UUID | None = None
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    mgmt_ip: str | None = None
    notes: str | None = None


class PhysicalServerUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geändert."""

    hostname: str | None = None
    dns_name: str | None = None
    site_id: uuid.UUID | None = None
    server_role: ServerRole | None = None
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    cpu_model: str | None = None
    cpu_sockets: int | None = None
    cpu_cores: int | None = None
    ram_mb: int | None = None
    os_name: str | None = None
    mgmt_ip: str | None = None
    hardware_status: HardwareStatus | None = None
    hardware_detail: str | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_status: WarrantyStatus | None = None
    notes: str | None = None


async def _site_names(session: SessionDep) -> dict[uuid.UUID, str]:
    return {sid: name for sid, name in (await session.execute(select(Site.id, Site.name))).all()}


def _read(row: PhysicalServer, names: dict[uuid.UUID, str]) -> PhysicalServerRead:
    out = PhysicalServerRead.model_validate(row)
    out.mgmt_ip = str(row.mgmt_ip) if row.mgmt_ip else None
    out.site_name = names.get(row.site_id) if row.site_id else None
    return out


async def _get_or_404(session: SessionDep, row_id: uuid.UUID) -> PhysicalServer:
    row = await session.get(PhysicalServer, row_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")
    return row


@router.get("", response_model=list[PhysicalServerRead])
async def list_physical_servers(session: SessionDep) -> list[PhysicalServerRead]:
    rows = (
        (
            await session.execute(
                select(PhysicalServer)
                .where(PhysicalServer.deleted_at.is_(None))
                .order_by(PhysicalServer.hostname)
            )
        )
        .scalars()
        .all()
    )
    names = await _site_names(session)
    return [_read(r, names) for r in rows]


@router.post("", response_model=PhysicalServerRead, status_code=status.HTTP_201_CREATED)
async def create_physical_server(
    body: PhysicalServerCreate, session: SessionDep
) -> PhysicalServerRead:
    row = PhysicalServer(**body.model_dump(), source="manual")
    session.add(row)
    await session.flush()
    return _read(row, await _site_names(session))


@router.patch("/{row_id}", response_model=PhysicalServerRead)
async def update_physical_server(
    row_id: uuid.UUID, body: PhysicalServerUpdate, session: SessionDep
) -> PhysicalServerRead:
    row = await _get_or_404(session, row_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    return _read(row, await _site_names(session))


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_physical_server(row_id: uuid.UUID, session: SessionDep) -> None:
    row = await _get_or_404(session, row_id)
    row.deleted_at = datetime.now().astimezone()
