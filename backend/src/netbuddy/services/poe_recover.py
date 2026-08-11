"""Fleet-weite PoE-Recovery-Orchestrierung — gemeinsam von API-Endpoint und ARQ-Worker genutzt.

``collect_stuck`` scannt alle PoE-fähigen Switches live und kreuzt sie mit der sticky AP-Karte;
``recover_hits`` bounct die Treffer (gruppiert je Switch, mit Rate-Limit + Audit). ``auto_recover``
ist der Einzeiler für den Worker. Read-only Teile sind read-only; Recovery schreibt nur über den
expliziten Pfad.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters import UnknownAdapterError, get_profile
from netbuddy.adapters.profile import PoeControlSpec
from netbuddy.db.models import (
    ApLocation,
    Credential,
    Device,
    DeviceCredential,
    DeviceType,
    PoeEvent,
)
from netbuddy.services import unifi_local
from netbuddy.services.endpoint_location import build_ap_locations
from netbuddy.services.poe import (
    RECOVER_MAX_ATTEMPTS,
    PoePort,
    StuckCandidate,
    WriteTransport,
    is_stuck,
    recent_attempts,
    recover_with_policy,
    scan_poe,
)

# Verbindungs-Factory (wie api.deps.LiveConnection, aber ohne API-Abhängigkeit im Service-Layer).
LiveConnection = Callable[
    [Device, Credential], AbstractAsyncContextManager[tuple[Any, WriteTransport]]
]


async def cloud_credential(session: AsyncSession) -> Credential | None:
    return (
        (
            await session.execute(
                select(Credential).where(
                    Credential.base_url.ilike("%api.ui.com%"), Credential.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .first()
    )


async def device_credential(session: AsyncSession, device: Device) -> Credential | None:
    return (
        (
            await session.execute(
                select(Credential)
                .join(DeviceCredential, DeviceCredential.credential_id == Credential.id)
                .where(
                    DeviceCredential.device_id == device.id,
                    DeviceCredential.deleted_at.is_(None),
                    Credential.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )


def poe_spec(adapter_id: str | None) -> PoeControlSpec | None:
    if not adapter_id:
        return None
    try:
        return get_profile(adapter_id).poe_control
    except UnknownAdapterError:
        return None


class StuckHit:
    """Ein „hängender" AP-Port samt Verbindungs-Kontext (für die anschließende Recovery)."""

    def __init__(
        self, device: Device, cred: Credential, spec: PoeControlSpec, port: PoePort, ap: ApLocation
    ) -> None:
        self.device = device
        self.cred = cred
        self.spec = spec
        self.port = port
        self.ap = ap


async def collect_stuck(
    session: AsyncSession,
    connection: LiveConnection,
    cloud_cred: Credential,
    *,
    refresh: bool,
) -> list[StuckHit]:
    """Alle PoE-Switches live scannen + gegen die (ggf. frisch gespiegelte) AP-Karte kreuzen."""
    if refresh:
        await build_ap_locations(session, cloud_cred, persist=True)

    ap_rows = (
        (await session.execute(select(ApLocation).where(ApLocation.device_id.is_not(None))))
        .scalars()
        .all()
    )
    port_to_ap: dict[tuple[uuid.UUID, str], ApLocation] = {
        (r.device_id, r.port): r for r in ap_rows if r.device_id and r.port
    }

    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    jobs: list[tuple[Device, Credential, PoeControlSpec]] = []
    for d in devices:
        spec = poe_spec(d.adapter_id)
        if spec is None:
            continue
        cred = await device_credential(session, d)
        if cred is not None:
            jobs.append((d, cred, spec))

    hits: list[StuckHit] = []
    for device, cred, spec in jobs:
        try:
            async with connection(device, cred) as (_adapter, transport):
                ports = await scan_poe(transport, spec)
        except Exception as exc:
            logger.warning("PoE-Scan {} übersprungen: {}", device.hostname, exc)
            continue
        for port in ports:
            ap = port_to_ap.get((device.id, port.port))
            if ap is not None and is_stuck(port, ap.status):
                hits.append(StuckHit(device, cred, spec, port, ap))
    return hits


async def recover_hits(
    session: AsyncSession,
    connection: LiveConnection,
    hits: list[StuckHit],
    *,
    actor: str,
) -> list[PoeEvent]:
    """Bouncet alle Treffer, eine SSH-Verbindung je Switch (mehrere Ports nacheinander)."""
    by_device: dict[uuid.UUID, list[StuckHit]] = {}
    for h in hits:
        by_device.setdefault(h.device.id, []).append(h)

    events: list[PoeEvent] = []
    for device_hits in by_device.values():
        device, cred, spec = device_hits[0].device, device_hits[0].cred, device_hits[0].spec
        async with connection(device, cred) as (_adapter, transport):
            for h in device_hits:
                events.append(
                    await recover_with_policy(
                        session,
                        device.id,
                        transport,
                        spec,
                        h.port.port,
                        ap_mac=h.ap.ap_mac,
                        ap_name=h.ap.ap_name,
                        actor=actor,
                    )
                )
    return events


# --- UniFi-Switches (lokale API) -------------------------------------------------------------


async def local_credential(session: AsyncSession) -> Credential | None:
    return (
        (
            await session.execute(
                select(Credential).where(
                    Credential.name == "UnifiLocal", Credential.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .first()
    )


async def collect_unifi_stuck(
    session: AsyncSession,
    local_cred: Credential,
    *,
    fetch: Callable[..., Any] = unifi_local.fetch_all,
) -> list[StuckCandidate]:
    """Stuck-Ports an UniFi-Switches (PoE freigegeben, aber kein sauberer Strom) → Kandidaten."""
    devices, _clients = await fetch(local_cred)
    faults = unifi_local.find_poe_faults(devices)
    if not faults:
        return []
    sdevs = (
        (
            await session.execute(
                select(Device).where(
                    Device.device_type == DeviceType.SWITCH, Device.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    by_host = {(d.hostname or "").upper(): d for d in sdevs}
    by_ip = {str(d.mgmt_ip): d for d in sdevs}

    out: list[StuckCandidate] = []
    for f in faults:
        ndev = by_host.get((f.switch_name or "").upper()) or (
            by_ip.get(f.switch_ip) if f.switch_ip else None
        )
        if ndev is None:
            continue
        out.append(
            StuckCandidate(
                device_id=ndev.id,
                hostname=ndev.hostname,
                port=str(f.port_idx),
                poe_status="poe_fault",
                link_up=False,
                reason=f"UniFi PoE-Fault Port {f.port_idx} ({f.port_name or '-'})",
                source="unifi",
                switch_mac=f.switch_mac,
                site=f.site,
                port_idx=f.port_idx,
            )
        )
    return out


async def recover_unifi(
    session: AsyncSession,
    local_cred: Credential,
    cand: StuckCandidate,
    *,
    actor: str,
    power_cycle: Callable[..., Any] = unifi_local.power_cycle_port,
) -> PoeEvent:
    """⚠️ UniFi-Port per ``power-cycle`` erholen — mit Rate-Limit + PoeEvent (wie der CLI-Pfad)."""
    if await recent_attempts(session, cand.device_id, cand.port) >= RECOVER_MAX_ATTEMPTS:
        event = PoeEvent(
            device_id=cand.device_id,
            port=cand.port,
            ap_name=cand.ap_name,
            action="skipped_ratelimit",
            actor=actor,
            detail=f"Rate-Limit: >= {RECOVER_MAX_ATTEMPTS} Versuche",
        )
        session.add(event)
        return event
    try:
        await power_cycle(local_cred, cand.site or "", cand.switch_mac or "", cand.port_idx or 0)
        event = PoeEvent(
            device_id=cand.device_id,
            port=cand.port,
            ap_name=cand.ap_name,
            action="recovered",
            status_before="poe_fault",
            actor=actor,
            detail="UniFi power-cycle",
        )
    except Exception as exc:
        event = PoeEvent(
            device_id=cand.device_id,
            port=cand.port,
            action="error",
            actor=actor,
            detail=str(exc)[:500],
        )
    session.add(event)
    return event


async def auto_recover(
    session: AsyncSession, connection: LiveConnection, *, actor: str = "worker"
) -> list[PoeEvent]:
    """Worker-Einstieg: Stuck-Ports (Dell-CLI + UniFi) finden + erholen."""
    events: list[PoeEvent] = []
    cred = await cloud_credential(session)
    if cred is not None:
        hits = await collect_stuck(session, connection, cred, refresh=True)
        events += await recover_hits(session, connection, hits, actor=actor)
    local = await local_credential(session)
    if local is not None:
        for cand in await collect_unifi_stuck(session, local):
            events.append(await recover_unifi(session, local, cand, actor=actor))
    return events
