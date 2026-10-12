"""Inventar-Sync für die Server-/Storage-Kategorien (read-only an den Quellen).

Aktuell: vCenter (virtuelle + physische Server + Storage-Datastores). Weitere Quellen
(iDRAC/Redfish, Array-APIs, NAS) kommen als eigene Endpunkte dazu.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from netbuddy.api.deps import SessionDep
from netbuddy.services.cato_nat import NatResolveSummary, resolve_reachable_ips
from netbuddy.services.snmp_enrich import SnmpSummary, snmp_enrich
from netbuddy.services.storage_api import (
    StorageApiSummary,
    enrich_storage_apis,
    import_storage_credentials,
)
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
    """Schreibt je Gerät die erreichbare (Cato-übersetzte) Adresse in reachable_ip."""
    return await resolve_reachable_ips(session)


@router.post("/storage-api/enrich", response_model=StorageApiSummary)
async def storage_api_enrich(
    session: SessionDep,
    enable_snmp: bool = False,
    sites: Annotated[list[str] | None, Query()] = None,
) -> StorageApiSummary:
    """Storage via Hersteller-API (Synology/NetApp/IBM Storwize) lesen inkl. Hardware-Status;
    optional SNMP (Community PRTG) setzen. ``sites`` grenzt auf Standort-Namen ein."""
    return await enrich_storage_apis(session, enable_snmp=enable_snmp, sites=sites)


@router.post("/storage-creds/import", response_model=list[str])
async def storage_creds_import(session: SessionDep, dry_run: bool = False) -> list[str]:
    """Storage-Logins einmal aus Passwordstate ziehen und als NetBuddy-Credentials ablegen
    (``source=passwordstate-storage``). Danach liest der Enrich-Lauf daraus statt live."""
    return await import_storage_credentials(session, dry_run=dry_run)
