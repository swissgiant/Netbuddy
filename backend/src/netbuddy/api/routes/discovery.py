import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import HostResolverDep, LiveAdapterDep, SessionDep
from netbuddy.db.models import Credential, Device, Interface, LldpNeighbor
from netbuddy.services.crawl import CrawlReport, crawl
from netbuddy.services.hosts import correlate_hosts

router = APIRouter(prefix="/discovery", tags=["discovery"])


class SuggestedDevice(BaseModel):
    """Ein über LLDP gesehener Nachbar, der noch nicht im Inventar ist (Add-Vorschlag)."""

    system_name: str | None
    chassis_id: str
    remote_port_id: str
    system_description: str | None
    seen_on: list[str]  # "<hostname> / <local-interface>"


@router.get("/suggestions", response_model=list[SuggestedDevice])
async def list_suggestions(session: SessionDep) -> list[SuggestedDevice]:
    """Schlägt naheliegende Geräte vor: LLDP-Nachbarn bekannter Geräte, die selbst noch
    nicht als `Device` erfasst sind (gematcht über `remote_system_name == hostname`)."""
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    known_hostnames = {d.hostname for d in devices}
    device_by_id = {d.id: d for d in devices}
    iface_by_id = {i.id: i for i in (await session.execute(select(Interface))).scalars()}

    by_chassis: dict[str, SuggestedDevice] = {}
    for n in (await session.execute(select(LldpNeighbor))).scalars():
        if n.remote_system_name and n.remote_system_name in known_hostnames:
            continue  # schon im Inventar
        local_dev = device_by_id.get(n.local_device_id)
        local_iface = iface_by_id.get(n.local_interface_id)
        seen = (
            f"{local_dev.hostname if local_dev else '?'} / "
            f"{local_iface.name if local_iface else '?'}"
        )
        existing = by_chassis.get(n.remote_chassis_id)
        if existing is None:
            by_chassis[n.remote_chassis_id] = SuggestedDevice(
                system_name=n.remote_system_name,
                chassis_id=n.remote_chassis_id,
                remote_port_id=n.remote_port_id,
                system_description=n.remote_system_description,
                seen_on=[seen],
            )
        elif seen not in existing.seen_on:
            existing.seen_on.append(seen)

    return list(by_chassis.values())


class CrawlRequest(BaseModel):
    seed_device_ids: list[uuid.UUID]
    credential_id: uuid.UUID
    max_depth: int = 2
    default_adapter_id: str | None = None


@router.post("/crawl", response_model=CrawlReport)
async def crawl_endpoint(
    body: CrawlRequest, session: SessionDep, live_adapter: LiveAdapterDep
) -> CrawlReport:
    """Autodiscovery-Crawl (read-only): ab den Seed-Geräten über LLDP rekursiv aufnehmen.

    Nutzt fleet-weit die angegebene Credential für neu gefundene Geräte. ⚠️ echter Geräte-Zugriff.
    """
    seeds = (
        (
            await session.execute(
                select(Device).where(
                    Device.id.in_(body.seed_device_ids), Device.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not seeds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Keine Seed-Geräte gefunden"
        )
    credential = await session.get(Credential, body.credential_id)
    if credential is None or credential.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Credential nicht gefunden"
        )
    return await crawl(
        session,
        seeds,
        credential,
        live_adapter,
        max_depth=body.max_depth,
        default_adapter_id=body.default_adapter_id,
    )


@router.post("/resolve-hosts")
async def resolve_hosts(session: SessionDep, resolver: HostResolverDep) -> dict[str, int]:
    """Korreliert die gesammelten ARP-Einträge zu Hosts (MAC↔IP) und löst Namen per Reverse-DNS.

    Macht Endgeräte per Name/IP über `/search` auffindbar. Read-only gegenüber Geräten — es werden
    nur die schon discoverten ARP-Daten plus DNS genutzt.
    """
    return await correlate_hosts(session, resolver)
