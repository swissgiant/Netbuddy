"""Inventar-Sync für die Server-/Storage-Kategorien (read-only an den Quellen).

Aktuell: vCenter (virtuelle + physische Server + Storage-Datastores). Weitere Quellen
(iDRAC/Redfish, Array-APIs, NAS) kommen als eigene Endpunkte dazu.
"""

from fastapi import APIRouter

from netbuddy.api.deps import SessionDep
from netbuddy.services.vcenter_inventory import VcSyncSummary, sync_vcenters

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/vcenter/sync", response_model=list[VcSyncSummary])
async def sync_vcenter(session: SessionDep) -> list[VcSyncSummary]:
    """Ruft alle hinterlegten vCenter ab (Credential mit ``extra.kind == "vcenter"``)."""
    return await sync_vcenters(session)
