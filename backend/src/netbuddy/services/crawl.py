from collections import deque
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.db.models import (
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
    LldpNeighbor,
)
from netbuddy.services.discovery import run_discovery
from netbuddy.services.oui import vendor_for_mac

# system_description-Schlüsselwort → adapter_id (für die Adapter-Schätzung beim Auto-Anlegen).
_ADAPTER_HINTS: list[tuple[str, str]] = [
    ("os10", "dell_os10"),
    ("powerconnect", "dell_os6"),
    ("n-series", "dell_os6"),
    ("aruba", "aruba_cx"),
    ("fortigate", "fortigate"),
    ("fortinet", "fortigate"),
    ("fiberstore", "fs_ruijie"),
    ("fsos", "fs_ruijie"),
    ("cisco ios", "cisco_ios"),
    ("catalyst", "cisco_ios"),
    ("meraki", "meraki"),
    ("ubiquiti", "unifi"),
    ("unifi", "unifi"),
]

# OUI-Hersteller (aus der chassis_id-MAC) → adapter_id. Nur eindeutige Zuordnungen —
# FS (Centec vs. Ruijie) und Dell (OS10 vs. OS6) sind per MAC nicht unterscheidbar.
_OUI_ADAPTER_HINTS: list[tuple[str, str]] = [
    ("fortinet", "fortigate"),
    ("ubiquiti", "unifi"),
]

# adapter_id → Gerätetyp; alles andere bleibt SWITCH.
_DEVICE_TYPE_FOR_ADAPTER: dict[str, DeviceType] = {"fortigate": DeviceType.FIREWALL}

AdapterProvider = Callable[[Device, Credential], AbstractAsyncContextManager[SwitchAdapter]]


def guess_adapter(
    system_description: str | None, default: str | None, *, chassis_id: str | None = None
) -> str | None:
    """Rät das Profil aus der LLDP-system_description, sonst aus dem MAC-OUI der chassis_id."""
    desc = (system_description or "").lower()
    for needle, adapter_id in _ADAPTER_HINTS:
        if needle in desc:
            return adapter_id
    if chassis_id:
        vendor = (vendor_for_mac(chassis_id) or "").lower()
        for needle, adapter_id in _OUI_ADAPTER_HINTS:
            if needle in vendor:
                return adapter_id
    return default


def guess_device_type(adapter_id: str | None, system_description: str | None) -> DeviceType:
    """Gerätetyp fürs Auto-Anlegen: Firewalls/APs nicht mehr pauschal als Switch eintragen."""
    if adapter_id in _DEVICE_TYPE_FOR_ADAPTER:
        return _DEVICE_TYPE_FOR_ADAPTER[adapter_id]
    desc = (system_description or "").lower()
    if "access point" in desc or desc.startswith(("u6", "u7", "uap")):
        return DeviceType.AP
    return DeviceType.SWITCH


class CrawlAdded(BaseModel):
    hostname: str
    mgmt_ip: str
    adapter_id: str


class CrawlReport(BaseModel):
    """Ergebnis eines Autodiscovery-Crawls (BFS über LLDP, read-only)."""

    seeds: int
    discovered: list[str]  # Hostnames, die ausgelesen wurden
    added: list[CrawlAdded]  # neu ins Inventar aufgenommene Nachbarn
    errors: list[dict[str, str]]


async def _new_neighbors(
    session: AsyncSession, device_id: object, known_ips: set[str]
) -> Sequence[LldpNeighbor]:
    stmt = select(LldpNeighbor).where(
        LldpNeighbor.local_device_id == device_id,
        LldpNeighbor.remote_mgmt_address.is_not(None),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [n for n in rows if n.remote_mgmt_address not in known_ips]


async def crawl(
    session: AsyncSession,
    seeds: Sequence[Device],
    credential: Credential,
    adapter_provider: AdapterProvider,
    *,
    max_depth: int = 2,
    default_adapter_id: str | None = None,
) -> CrawlReport:
    """Discovern + LLDP-Nachbarn mit Management-IP automatisch aufnehmen und weiter crawlen.

    Read-only auf den Geräten; neu gefundene Nachbarn werden als Inventar-Eintrag angelegt und mit
    der übergebenen Credential verknüpft (eine fleet-weite Discovery-Credential). Tiefenbegrenzt.
    """
    existing = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    known_ips: set[str] = {d.mgmt_ip for d in existing}

    report = CrawlReport(seeds=len(seeds), discovered=[], added=[], errors=[])
    queue: deque[tuple[Device, int]] = deque((d, 0) for d in seeds)
    seen_devices: set[object] = {d.id for d in seeds}

    while queue:
        device, depth = queue.popleft()
        try:
            async with adapter_provider(device, credential) as adapter:
                await run_discovery(session, device, adapter, triggered_by="crawl")
            report.discovered.append(device.hostname)
        except Exception as exc:
            report.errors.append(
                {"device": device.hostname, "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        if depth >= max_depth:
            continue

        for neighbor in await _new_neighbors(session, device.id, known_ips):
            mgmt = neighbor.remote_mgmt_address
            assert mgmt is not None  # durch _new_neighbors gefiltert
            adapter_id = guess_adapter(
                neighbor.remote_system_description,
                default_adapter_id,
                chassis_id=neighbor.remote_chassis_id,
            )
            if adapter_id is None:
                continue  # ohne Adapter-Zuordnung nicht erreichbar → überspringen
            new_device = Device(
                hostname=neighbor.remote_system_name or mgmt,
                mgmt_ip=mgmt,
                vendor=adapter_id.split("_")[0],
                adapter_id=adapter_id,
                device_type=guess_device_type(adapter_id, neighbor.remote_system_description),
                site_id=device.site_id,
            )
            session.add(new_device)
            await session.flush()
            session.add(
                DeviceCredential(
                    device_id=new_device.id,
                    credential_id=credential.id,
                    protocol=CredentialProtocol.SSH,
                )
            )
            await session.flush()
            known_ips.add(mgmt)
            report.added.append(
                CrawlAdded(hostname=new_device.hostname, mgmt_ip=mgmt, adapter_id=adapter_id)
            )
            if new_device.id not in seen_devices:
                seen_devices.add(new_device.id)
                queue.append((new_device, depth + 1))

    return report
