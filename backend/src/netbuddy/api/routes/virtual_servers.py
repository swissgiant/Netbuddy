"""Kategorie „Virtuelle Server" — filter-/sortierbare Liste (CRUD).

Befüllt netzweit aus allen vCentern über :mod:`netbuddy.services.server_inventory`.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import PowerState, Site, VirtualServer

router = APIRouter(prefix="/virtual-servers", tags=["virtual-servers"])


class VirtualServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    dns_name: str | None
    site_id: uuid.UUID | None
    site_name: str | None = None
    power_state: PowerState
    vcpu: int | None
    ram_mb: int | None
    cluster: str | None
    esxi_host: str | None
    physical_server_id: uuid.UUID | None
    vcenter: str | None
    guest_os: str | None
    vmware_tools: str | None
    disk_count: int | None
    disk_total_gb: int | None
    disks: list[dict[str, object]]
    datastores: list[str]
    ip_addresses: list[str]
    networks: list[str]
    source: str | None
    last_seen: datetime | None
    notes: str | None
    created_at: datetime


class VirtualServerCreate(BaseModel):
    name: str
    site_id: uuid.UUID | None = None
    cluster: str | None = None
    esxi_host: str | None = None
    notes: str | None = None


class VirtualServerUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geändert."""

    name: str | None = None
    dns_name: str | None = None
    site_id: uuid.UUID | None = None
    power_state: PowerState | None = None
    vcpu: int | None = None
    ram_mb: int | None = None
    cluster: str | None = None
    esxi_host: str | None = None
    guest_os: str | None = None
    notes: str | None = None


async def _site_names(session: SessionDep) -> dict[uuid.UUID, str]:
    return {sid: name for sid, name in (await session.execute(select(Site.id, Site.name))).all()}


def _read(row: VirtualServer, names: dict[uuid.UUID, str]) -> VirtualServerRead:
    out = VirtualServerRead.model_validate(row)
    out.site_name = names.get(row.site_id) if row.site_id else None
    return out


async def _get_or_404(session: SessionDep, row_id: uuid.UUID) -> VirtualServer:
    row = await session.get(VirtualServer, row_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM nicht gefunden")
    return row


@router.get("", response_model=list[VirtualServerRead])
async def list_virtual_servers(session: SessionDep) -> list[VirtualServerRead]:
    rows = (
        (
            await session.execute(
                select(VirtualServer)
                .where(VirtualServer.deleted_at.is_(None))
                .order_by(VirtualServer.name)
            )
        )
        .scalars()
        .all()
    )
    names = await _site_names(session)
    return [_read(r, names) for r in rows]


@router.post("", response_model=VirtualServerRead, status_code=status.HTTP_201_CREATED)
async def create_virtual_server(
    body: VirtualServerCreate, session: SessionDep
) -> VirtualServerRead:
    row = VirtualServer(**body.model_dump(), source="manual")
    session.add(row)
    await session.flush()
    return _read(row, await _site_names(session))


@router.patch("/{row_id}", response_model=VirtualServerRead)
async def update_virtual_server(
    row_id: uuid.UUID, body: VirtualServerUpdate, session: SessionDep
) -> VirtualServerRead:
    row = await _get_or_404(session, row_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    return _read(row, await _site_names(session))


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_virtual_server(row_id: uuid.UUID, session: SessionDep) -> None:
    row = await _get_or_404(session, row_id)
    row.deleted_at = datetime.now().astimezone()
