"""PoE-Status, AP-Verortung und PoE-Recovery.

- ``GET  /endpoints/aps``            — Karte AP -> Switch/Port + online/offline + Mesh (Topologie).
- ``GET  /poe/devices/{id}``         — Live-PoE-Status aller Ports eines (PoE-fähigen) Switches.
- ``GET  /poe/stuck``                — fleet-weite Liste „hängender" AP-Ports (Kandidaten).
- ``POST /poe/devices/{id}/recover`` — ⚠️ EINEN Port bouncen (shut/no shut), rate-limitiert+Audit.
- ``POST /poe/recover``              — ⚠️ ALLE aktuell hängenden Ports bouncen.
- ``GET  /poe/events``               — Historie der Recovery-Ereignisse.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from netbuddy.api.deps import CurrentUserDep, LiveConnectionDep, SessionDep
from netbuddy.db.models import ApLocation, Credential, Device, DeviceType, PoeEvent
from netbuddy.services import unifi_local
from netbuddy.services.audit import audit
from netbuddy.services.endpoint_location import ApLocationInfo, build_ap_locations
from netbuddy.services.poe import PoePort, StuckCandidate, recover_with_policy, scan_poe
from netbuddy.services.poe_recover import (
    cloud_credential,
    collect_stuck,
    collect_unifi_stuck,
    device_credential,
    local_credential,
    poe_spec,
    recover_hits,
    recover_unifi,
)
from netbuddy.services.unifi_local import ClientLocation, UnifiDevice

router = APIRouter(tags=["poe"])


async def _local_devices(session: SessionDep) -> list[UnifiDevice] | None:
    """Geräte der lokalen UniFi-Controller (None, wenn kein `UnifiLocal`-Credential existiert)."""
    cred = await local_credential(session)
    if cred is None:
        return None
    devices, _clients = await unifi_local.fetch_all(cred)
    return devices


def _is_unifi_switch(device: Device) -> bool:
    return device.device_type == DeviceType.SWITCH and (device.vendor or "").lower().startswith(
        "ubiq"
    )


async def _cloud_credential(session: SessionDep) -> Credential:
    cred = await cloud_credential(session)
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine UniFi-Cloud-Credential (base_url api.ui.com) angelegt",
        )
    return cred


async def _device(device_id: uuid.UUID, session: SessionDep) -> Device:
    device = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gerät nicht gefunden")
    return device


@router.get("/endpoints/aps", response_model=list[ApLocationInfo])
async def list_ap_locations(session: SessionDep, refresh: bool = True) -> list[ApLocationInfo]:
    """AP-Switch/Port-Karte. Mesh/Uplink autoritativ vom lokalen Controller, sonst LLDP/MAC."""
    cred = await _cloud_credential(session)
    return await build_ap_locations(
        session, cred, local_devices=await _local_devices(session), persist=refresh
    )


@router.get("/endpoints/clients", response_model=list[ClientLocation])
async def list_clients(session: SessionDep) -> list[ClientLocation]:
    """Welcher Client hängt wo: wired am Switch-Port, wireless am AP (lokaler UniFi-Controller)."""
    cred = await local_credential(session)
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kein UnifiLocal-Credential — Client-Detection braucht den lokalen Controller",
        )
    devices, clients = await unifi_local.fetch_all(cred)
    return unifi_local.locate_clients(devices, clients)


@router.get("/poe/devices/{device_id}", response_model=list[PoePort])
async def poe_device_status(
    device_id: uuid.UUID, session: SessionDep, connection: LiveConnectionDep
) -> list[PoePort]:
    """Live-PoE-Status (read-only) eines Switches; leer, wenn das Modell kein PoE hat."""
    device = await _device(device_id, session)
    spec = poe_spec(device.adapter_id)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Adapter {device.adapter_id!r} kennt keinen PoE-Pfad",
        )
    credential = await device_credential(session, device)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Keine Credential verknüpft"
        )
    async with connection(device, credential) as (_adapter, transport):
        return await scan_poe(transport, spec)


@router.get("/poe/stuck", response_model=list[StuckCandidate])
async def poe_stuck(
    session: SessionDep, connection: LiveConnectionDep, refresh: bool = True
) -> list[StuckCandidate]:
    """Fleet-weit „hängende" Ports: Dell-CLI (Bounce) + UniFi-Switches (power-cycle)."""
    cred = await _cloud_credential(session)
    hits = await collect_stuck(session, connection, cred, refresh=refresh)
    candidates = [
        StuckCandidate(
            device_id=h.device.id,
            hostname=h.device.hostname,
            port=h.port.port,
            poe_status=h.port.poe_status,
            poe_state=h.port.poe_state,
            link_up=h.port.link_up,
            ap_mac=h.ap.ap_mac,
            ap_name=h.ap.ap_name,
            reason=f"PoE {h.port.poe_status} + Link down + UniFi offline ({h.ap.ap_name})",
        )
        for h in hits
    ]
    local = await local_credential(session)
    if local is not None:
        candidates += await collect_unifi_stuck(session, local)
    return candidates


# --- Recovery (Write) ------------------------------------------------------------------------


class RecoverRequest(BaseModel):
    port: str


class RecoverResult(BaseModel):
    device_id: uuid.UUID
    hostname: str
    port: str
    action: str  # recovered | no_change | skipped_ratelimit | error
    status_before: str | None = None
    status_after: str | None = None
    ap_name: str | None = None
    detail: str = ""


def _result(device_id: uuid.UUID, hostname: str, event: PoeEvent) -> RecoverResult:
    return RecoverResult(
        device_id=device_id,
        hostname=hostname,
        port=event.port,
        action=event.action,
        status_before=event.status_before,
        status_after=event.status_after,
        ap_name=event.ap_name,
        detail=event.detail or "",
    )


async def _recover_unifi_one(
    device: Device, body: RecoverRequest, session: SessionDep, actor: str
) -> PoeEvent:
    """Manueller UniFi-Port-Recover: Switch im Controller finden (mac/site) → power-cycle."""
    local = await local_credential(session)
    if local is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Kein UnifiLocal-Credential"
        )
    devices, _clients = await unifi_local.fetch_all(local)
    usw = next(
        (
            d
            for d in devices
            if d.type == "usw"
            and (d.ip == str(device.mgmt_ip) or (d.name or "").upper() == device.hostname.upper())
        ),
        None,
    )
    if usw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Switch im Controller nicht gefunden"
        )
    try:
        port_idx = int(body.port)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Port muss ein Port-Index sein"
        ) from None
    cand = StuckCandidate(
        device_id=device.id,
        hostname=device.hostname,
        port=body.port,
        poe_status="manual",
        reason="manueller UniFi-Port-Recover",
        source="unifi",
        switch_mac=usw.mac,
        site=usw.site,
        port_idx=port_idx,
    )
    return await recover_unifi(session, local, cand, actor=actor)


@router.post("/poe/devices/{device_id}/recover", response_model=RecoverResult)
async def recover_one(
    device_id: uuid.UUID,
    body: RecoverRequest,
    session: SessionDep,
    connection: LiveConnectionDep,
    user: CurrentUserDep,
) -> RecoverResult:
    """⚠️ Schreibzugriff: erholt EINEN PoE-Port (Dell: shut/no shut · UniFi: power-cycle)."""
    device = await _device(device_id, session)
    actor = user.username if user else "api"

    if _is_unifi_switch(device):
        event = await _recover_unifi_one(device, body, session, actor)
    else:
        spec = poe_spec(device.adapter_id)
        if spec is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Adapter {device.adapter_id!r} kennt keinen PoE-Pfad",
            )
        credential = await device_credential(session, device)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Keine Credential verknüpft"
            )
        ap = (
            await session.execute(
                select(ApLocation).where(
                    ApLocation.device_id == device.id, ApLocation.port == body.port
                )
            )
        ).scalar_one_or_none()
        async with connection(device, credential) as (_adapter, transport):
            event = await recover_with_policy(
                session,
                device.id,
                transport,
                spec,
                body.port,
                ap_mac=ap.ap_mac if ap else None,
                ap_name=ap.ap_name if ap else None,
                actor=actor,
            )
    await audit(
        session, user, "poe.recover", device.hostname, {"port": body.port, "action": event.action}
    )
    await session.commit()
    return _result(device.id, device.hostname, event)


@router.post("/poe/recover", response_model=list[RecoverResult])
async def recover_all_stuck(
    session: SessionDep, connection: LiveConnectionDep, user: CurrentUserDep, refresh: bool = True
) -> list[RecoverResult]:
    """⚠️ Schreibzugriff: erholt ALLE aktuell „hängenden" Ports (Dell-CLI + UniFi-API)."""
    cred = await _cloud_credential(session)
    actor = user.username if user else "api"
    results: list[RecoverResult] = []

    hits = await collect_stuck(session, connection, cred, refresh=refresh)
    cli_events = await recover_hits(session, connection, hits, actor=actor)
    devices_by_id = {h.device.id: h.device for h in hits}
    results += [_result(e.device_id, devices_by_id[e.device_id].hostname, e) for e in cli_events]

    local = await local_credential(session)
    if local is not None:
        for cand in await collect_unifi_stuck(session, local):
            event = await recover_unifi(session, local, cand, actor=actor)
            results.append(_result(cand.device_id, cand.hostname, event))

    if results:
        await audit(session, user, "poe.recover_all", "", {"recovered": len(results)})
        await session.commit()
    return results


class PoeEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: uuid.UUID
    port: str
    ap_name: str | None
    action: str
    status_before: str | None
    status_after: str | None
    actor: str | None
    detail: str | None
    created_at: datetime


@router.get("/poe/events", response_model=list[PoeEventRead])
async def poe_events(session: SessionDep, limit: int = 100) -> list[PoeEvent]:
    """Letzte PoE-Recovery-Ereignisse (Audit/Historie, Root-Cause-Auswertung)."""
    rows = (
        (
            await session.execute(
                select(PoeEvent).order_by(PoeEvent.created_at.desc()).limit(min(limit, 500))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
