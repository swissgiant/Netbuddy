"""Inventar-Sync für die Server-/Storage-Kategorien (read-only an den Quellen).

Aktuell: vCenter (virtuelle + physische Server + Storage-Datastores). Weitere Quellen
(iDRAC/Redfish, Array-APIs, NAS) kommen als eigene Endpunkte dazu.
"""

from fastapi import APIRouter

from netbuddy.api.deps import SessionDep
from netbuddy.services.cato_nat import NatResolveSummary, resolve_reachable_ips
from netbuddy.services.snmp_enrich import SnmpSummary, snmp_enrich
from netbuddy.services.vcenter_inventory import VcSyncSummary, sync_vcenters

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/vcenter/sync", response_model=list[VcSyncSummary])
async def sync_vcenter(session: SessionDep) -> list[VcSyncSummary]:
    """Ruft alle hinterlegten vCenter ab (Credential mit ``extra.kind == "vcenter"``)."""
    return await sync_vcenters(session)


@router.post("/snmp/enrich", response_model=SnmpSummary)
async def snmp_enrich_devices(session: SessionDep) -> SnmpSummary:
    """Reichert Storage/physische Server per SNMP an (Community aus Passwordstate „B-HQ Switch")."""
    return await snmp_enrich(session)


@router.post("/cato-nat/resolve", response_model=NatResolveSummary)
async def resolve_nat(session: SessionDep) -> NatResolveSummary:
    """Schreibt je Gerät die erreichbare (Cato-übersetzte) Adresse in extra.reachable_ip."""
    return await resolve_reachable_ips(session)
