import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import HostResolverDep, LiveAdapterDep, SessionDep
from netbuddy.db.models import Credential, Device
from netbuddy.services.crawl import CrawlReport, crawl
from netbuddy.services.hosts import correlate_hosts
from netbuddy.services.suggest import SuggestedDevice, suggest_devices

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/suggestions", response_model=list[SuggestedDevice])
async def list_suggestions(session: SessionDep) -> list[SuggestedDevice]:
    """EINE Vorschlagsliste für alles Gefundene, noch nicht Inventarisierte.

    Kombiniert LLDP-Nachbarn und Infrastruktur-Verdachte aus den MAC-Tabellen (OUI),
    gemerged über die Chassis-/Quell-MAC und angereichert mit IP (LLDP-Mgmt > ARP)
    und DNS-Name. `sources` zeigt, woher der Fund stammt ("lldp", "mac").
    """
    return await suggest_devices(session)


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
