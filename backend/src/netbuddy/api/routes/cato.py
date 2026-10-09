"""Cato-Networks-Anbindung: Sites/Netze lesen, Standorte+Segmente syncen, Geräte-Inventar."""

from collections.abc import Coroutine
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from netbuddy.adapters.base import AdapterError
from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Credential
from netbuddy.services.cato_inventory import (
    CatoApi,
    CatoSite,
    InfraCandidate,
    SyncSummary,
    fetch_devices,
    fetch_known_hosts,
    fetch_sites,
    infra_candidates,
    sync_sites,
)
from netbuddy.services.cato_policies import CatoPolicy, PolicyKind, fetch_policy

router = APIRouter(prefix="/cato", tags=["cato"])


async def _cato_credential(session: SessionDep) -> Credential:
    """Die Cato-Credential (per base_url catonetworks.com)."""
    stmt = select(Credential).where(
        Credential.base_url.ilike("%catonetworks%"), Credential.deleted_at.is_(None)
    )
    cred = (await session.execute(stmt)).scalars().first()
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Cato-Credential (base_url api.catonetworks.com, extra.account_id)",
        )
    return cred


def _api(cred: Credential) -> CatoApi:
    try:
        return CatoApi(cred)
    except AdapterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _guard[T](coro: Coroutine[Any, Any, T]) -> T:
    """Cato-API-Fehler (Key/Account/Netz) als 502 statt 500 melden."""
    try:
        return await coro
    except AdapterError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/sites", response_model=list[CatoSite])
async def list_sites(session: SessionDep) -> list[CatoSite]:
    """Alle Cato-Sites mit Sockets und Netzbereichen (live aus der Cato-API)."""
    cred = await _cato_credential(session)
    async with _api(cred) as api:
        return await _guard(fetch_sites(api))


@router.post("/sync", response_model=SyncSummary)
async def sync(session: SessionDep, dry_run: bool = True) -> SyncSummary:
    """Cato-Sites → NetBuddy-Standorte + Segmente + Socket-Devices (Standard: nur Vorschau)."""
    cred = await _cato_credential(session)
    async with _api(cred) as api:
        sites = await _guard(fetch_sites(api))
    return await sync_sites(session, cred, sites, dry_run=dry_run)


@router.get("/devices", response_model=list[InfraCandidate])
async def list_devices(session: SessionDep, infra_only: bool = True) -> list[InfraCandidate]:
    """Cato-Geräte-Inventar (Assets), gefiltert auf Netz-Infrastruktur-Verdacht."""
    cred = await _cato_credential(session)
    async with _api(cred) as api:
        devices = await _guard(fetch_devices(api))
    return await infra_candidates(session, devices, infra_only=infra_only)


@router.get("/hosts", response_model=list[InfraCandidate])
async def list_known_hosts(session: SessionDep, infra_only: bool = True) -> list[InfraCandidate]:
    """Known Hosts aller Cato-Sites (Socket-Sicht), Ersatz für das unlizenzierte Geräte-Inventar."""
    cred = await _cato_credential(session)
    async with _api(cred) as api:
        sites = await _guard(fetch_sites(api, with_ranges=False))
        hosts = await _guard(fetch_known_hosts(api, sites))
    return await infra_candidates(session, hosts, infra_only=infra_only)


@router.get("/policies/{kind}", response_model=CatoPolicy)
async def get_policy(kind: PolicyKind, session: SessionDep) -> CatoPolicy:
    """Eine Cato-Policy lesen: internet, wan, lan (Socket-LAN), bypass, wan_network."""
    cred = await _cato_credential(session)
    async with _api(cred) as api:
        return await _guard(fetch_policy(api, kind))
