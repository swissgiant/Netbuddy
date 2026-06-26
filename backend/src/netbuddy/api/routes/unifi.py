"""UniFi-Cloud-Verwaltung: Hosts (Konsolen) syncen + an/aus schalten, Geräte importieren."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential, UnifiHost
from netbuddy.services.unifi_inventory import (
    ImportSummary,
    fetch_device_groups,
    import_devices,
    sync_hosts,
)

router = APIRouter(prefix="/unifi", tags=["unifi"])


class UnifiHostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: str
    name: str
    enabled: bool


class HostToggle(BaseModel):
    enabled: bool


async def _cloud_credential(session: SessionDep) -> Credential:
    """Die UniFi-Cloud-Credential (per base_url api.ui.com)."""
    stmt = select(Credential).where(
        Credential.base_url.ilike("%api.ui.com%"), Credential.deleted_at.is_(None)
    )
    cred = (await session.execute(stmt)).scalars().first()
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine UniFi-Cloud-Credential (base_url api.ui.com) angelegt",
        )
    return cred


@router.get("/hosts", response_model=list[UnifiHostRead])
async def list_hosts(session: SessionDep) -> list[UnifiHost]:
    """Bekannte UniFi-Hosts/Konsolen mit An/Aus-Status."""
    stmt = select(UnifiHost).order_by(UnifiHost.name)
    return list((await session.execute(stmt)).scalars().all())


@router.post("/sync", response_model=list[UnifiHostRead])
async def sync(session: SessionDep) -> list[UnifiHost]:
    """Hosts aus der Cloud holen/aktualisieren (enabled bleibt erhalten)."""
    cred = await _cloud_credential(session)
    groups = await fetch_device_groups(cred)
    hosts = await sync_hosts(session, cred, groups)
    return hosts


@router.patch("/hosts/{host_id}", response_model=UnifiHostRead)
async def toggle_host(host_id: str, body: HostToggle, session: SessionDep) -> UnifiHost:
    """Einen UniFi-Host ein-/ausschalten (deaktiviert → beim Import übersprungen)."""
    host = (
        await session.execute(select(UnifiHost).where(UnifiHost.host_id == host_id))
    ).scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Host nicht gefunden")
    host.enabled = body.enabled
    await session.flush()
    return host


@router.post("/import", response_model=ImportSummary)
async def run_import(session: SessionDep) -> ImportSummary:
    """Switches + APs aus den AKTIVEN Hosts als Devices anlegen/aktualisieren."""
    cred = await _cloud_credential(session)
    groups = await fetch_device_groups(cred)
    await sync_hosts(session, cred, groups)  # neue Hosts zuerst sichtbar machen
    return await import_devices(session, cred, groups)
