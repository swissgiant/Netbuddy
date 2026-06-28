"""AP-Verortung: UniFi-Cloud (welcher AP, online/offline) x switch-seitiges LLDP/MAC (wo hängt
er) -> eine sticky Karte ``AP-MAC -> Switch/Port + Status``.

Quelle für „wo" sind die von der Discovery persistierten Tabellen (:class:`LldpNeighbor`,
:class:`MacAddressEntry`). Die Karte wird in :class:`ApLocation` gespiegelt und ist **sticky**:
geht ein AP offline (kein Strom → kein Link → kein LLDP), behält die Zeile den letzten Port —
genau das braucht die PoE-Recovery, um den richtigen Port zu bouncen. Zugleich Inventar/Topologie.
"""

import re
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    ApLocation,
    Credential,
    Device,
    DeviceType,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
)
from netbuddy.services.unifi_inventory import fetch_device_groups
from netbuddy.services.unifi_local import UnifiDevice

_AP_MODEL_PREFIXES = ("U6", "U7", "UAP")


def _norm_mac(value: str | None) -> str:
    return re.sub(r"[^0-9a-f]", "", (value or "").lower())


class ApLocationInfo(BaseModel):
    """Ein AP mit (sofern bekannt) Switch/Port und Mesh-Verdacht — Read-Model für die API."""

    ap_mac: str
    ap_name: str
    ap_model: str | None = None
    ap_ip: str | None = None
    status: str  # online | offline | unknown (aus der UniFi-Cloud)
    device_id: uuid.UUID | None = None
    device_hostname: str | None = None
    port: str | None = None
    source: str | None = None  # lldp | mac
    mesh: bool = False
    mesh_reason: str | None = None


class _Loc(BaseModel):
    device_id: uuid.UUID
    hostname: str
    port: str | None = None
    source: str


async def _unifi_aps(credential: Credential) -> dict[str, dict[str, str]]:
    """AP-MAC (normalisiert) → {name, status, model, ip} aus der UniFi-Cloud."""
    aps: dict[str, dict[str, str]] = {}
    for group in await fetch_device_groups(credential):
        for dev in group.get("devices", []):
            if dev.get("productLine") != "network":
                continue
            model = str(dev.get("model") or "")
            if not model.upper().startswith(_AP_MODEL_PREFIXES):
                continue
            mac = _norm_mac(dev.get("mac"))
            if not mac:
                continue
            aps[mac] = {
                "name": dev.get("name") or "",
                "status": dev.get("status") or "unknown",
                "model": model,
                "ip": dev.get("ip") or "",
            }
    return aps


async def _switch_locations(
    session: AsyncSession,
) -> tuple[dict[str, _Loc], dict[str, _Loc]]:
    """Aus persistiertem LLDP/MAC: (by_mac, by_name) → Switch/Port. LLDP hat Vorrang vor MAC."""
    by_mac: dict[str, _Loc] = {}
    by_name: dict[str, _Loc] = {}

    lldp_stmt = (
        select(
            LldpNeighbor.remote_chassis_id,
            LldpNeighbor.remote_system_name,
            Device.id,
            Device.hostname,
            Interface.name,
        )
        .join(Device, Device.id == LldpNeighbor.local_device_id)
        .join(Interface, Interface.id == LldpNeighbor.local_interface_id)
    )
    for chassis, sysname, dev_id, hostname, port in (await session.execute(lldp_stmt)).all():
        loc = _Loc(device_id=dev_id, hostname=hostname, port=port, source="lldp")
        mac = _norm_mac(chassis)
        if mac:
            by_mac.setdefault(mac, loc)
        if sysname:
            by_name.setdefault(sysname.upper(), loc)

    mac_stmt = (
        select(
            cast(MacAddressEntry.mac_address, String), Device.id, Device.hostname, Interface.name
        )
        .join(Device, Device.id == MacAddressEntry.device_id)
        .join(Interface, Interface.id == MacAddressEntry.interface_id)
    )
    for mac_raw, dev_id, hostname, port in (await session.execute(mac_stmt)).all():
        mac = _norm_mac(mac_raw)
        if mac:
            by_mac.setdefault(
                mac, _Loc(device_id=dev_id, hostname=hostname, port=port, source="mac")
            )

    return by_mac, by_name


async def _local_ap_index(
    session: AsyncSession, local_devices: list[UnifiDevice]
) -> dict[str, tuple[_Loc | None, bool]]:
    """Aus lokalen Controller-Daten: AP-MAC → (Switch-Location, is_wireless/mesh).

    ``uplink_mac`` (Upstream-Switch) wird über die UniFi-Switch-Liste auf ein NetBuddy-Device
    aufgelöst (per Hostname/IP). APs an Nicht-UniFi-Switches haben ``uplink_mac=None`` → Location
    bleibt der LLDP/MAC-Heuristik überlassen, der Mesh-Status kommt trotzdem aus dem Controller.
    """
    usw = {
        _norm_mac(d.mac): (d.name, d.ip) for d in local_devices if d.type == "usw"
    }
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

    index: dict[str, tuple[_Loc | None, bool]] = {}
    for d in local_devices:
        if d.type != "uap":
            continue
        wireless = d.uplink_type == "wireless"
        loc: _Loc | None = None
        if d.uplink_mac:
            name, ip = usw.get(_norm_mac(d.uplink_mac), (None, None))
            ndev = by_host.get((name or "").upper()) or (by_ip.get(ip) if ip else None)
            if ndev is not None:
                loc = _Loc(device_id=ndev.id, hostname=ndev.hostname, port=None, source="unifi")
        index[_norm_mac(d.mac)] = (loc, wireless)
    return index


async def build_ap_locations(
    session: AsyncSession,
    credential: Credential,
    *,
    local_devices: list[UnifiDevice] | None = None,
    persist: bool = True,
) -> list[ApLocationInfo]:
    """Baut die AP↔Port-Karte und spiegelt sie (sticky) in :class:`ApLocation`.

    Quelle: UniFi-Cloud (welcher AP, online/offline). **Wo** + **Mesh**: der lokale UniFi-Controller
    (``local_devices``, autoritativ — echter Uplink-Typ) wo verfügbar, sonst die LLDP/MAC-Heuristik
    (für APs an Nicht-UniFi-Switches, die der Controller nicht sieht).
    """
    aps = await _unifi_aps(credential)
    by_mac, by_name = await _switch_locations(session)
    local_idx = await _local_ap_index(session, local_devices) if local_devices else {}

    # Heuristik-Location (LLDP/MAC) als Basis bzw. Fallback.
    raw: dict[str, _Loc | None] = {
        mac: (by_mac.get(mac) or by_name.get(meta["name"].upper())) for mac, meta in aps.items()
    }
    per_port: dict[tuple[uuid.UUID, str | None], int] = {}
    for loc in raw.values():
        if loc is not None:
            per_port[(loc.device_id, loc.port)] = per_port.get((loc.device_id, loc.port), 0) + 1

    infos: list[ApLocationInfo] = []
    now = datetime.now(UTC)
    existing = {
        row.ap_mac: row for row in (await session.execute(select(ApLocation))).scalars().all()
    }
    hostnames = {
        did: hn for did, hn in (await session.execute(select(Device.id, Device.hostname))).all()
    }

    for mac, meta in aps.items():
        row = existing.get(mac)
        mesh = False
        mesh_reason: str | None = None

        if mac in local_idx:
            # Autoritativ: lokaler Controller kennt den AP.
            lloc, wireless = local_idx[mac]
            if wireless:
                mesh, mesh_reason, loc = True, "Uplink wireless (Mesh) laut Controller", None
            else:
                loc = lloc or raw[mac]  # UniFi-Switch direkt, sonst LLDP (AP an Nicht-UniFi-Switch)
        else:
            loc = raw[mac]
            if loc is not None and per_port[(loc.device_id, loc.port)] > 1:
                mesh = True
                mesh_reason = "mehrere APs an einem Port (gemesht/daisy-chained)"
            elif loc is None and meta["status"] == "online":
                mesh = True
                mesh_reason = "online, aber an keinem Wired-Port gesehen (Wireless-Uplink/Mesh?)"

        # Anzeige-Position: live-LLDP/MAC; für offline-APs ohne Live-Treffer der letzte bekannte
        # (sticky) Port — damit Topologie/Anzeige weiß, wo der AP zuletzt hing.
        disp_dev = loc.device_id if loc else None
        disp_host = loc.hostname if loc else None
        disp_port = loc.port if loc else None
        disp_src = loc.source if loc else None
        if loc is None and meta["status"] == "offline" and row is not None and row.device_id:
            disp_dev, disp_port, disp_src = row.device_id, row.port, row.source
            disp_host = hostnames.get(row.device_id)

        infos.append(
            ApLocationInfo(
                ap_mac=mac,
                ap_name=meta["name"],
                ap_model=meta["model"] or None,
                ap_ip=meta["ip"] or None,
                status=meta["status"],
                device_id=disp_dev,
                device_hostname=disp_host,
                port=disp_port,
                source=disp_src,
                mesh=mesh,
                mesh_reason=mesh_reason,
            )
        )

        if persist:
            if row is None:
                row = ApLocation(ap_mac=mac)
                session.add(row)
            row.ap_name = meta["name"]
            row.ap_model = meta["model"] or None
            row.ap_ip = meta["ip"] or None
            row.status = meta["status"]
            row.mesh = mesh
            row.synced_at = now
            if loc is not None:  # nur überschreiben, wenn neu verortet (sonst sticky behalten)
                row.device_id = loc.device_id
                row.port = loc.port
                row.source = loc.source
                row.located_at = now

    if persist:
        if local_devices:
            await _persist_switch_uplinks(session, local_devices, existing, now)
        await session.commit()

    infos.sort(key=lambda i: (i.status != "offline", i.ap_name))
    return infos


async def _persist_switch_uplinks(
    session: AsyncSession,
    local_devices: list[UnifiDevice],
    existing: dict[str, ApLocation],
    now: datetime,
) -> None:
    """UniFi-Switch→Upstream-Switch-Uplinks (Backbone) als sticky Zeilen ablegen (port=None),
    damit die Topologie an UniFi-Standorten Switch↔Core-Linien zeigt (kein CLI-LLDP dort).
    """
    usw = {_norm_mac(d.mac): (d.name, d.ip) for d in local_devices if d.type == "usw"}
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

    def resolve(name: str | None, ip: str | None) -> Device | None:
        return by_host.get((name or "").upper()) or (by_ip.get(ip) if ip else None)

    for d in local_devices:
        if d.type != "usw" or not d.uplink_mac:
            continue
        up_name, up_ip = usw.get(_norm_mac(d.uplink_mac), (None, None))
        upstream = resolve(up_name, up_ip)
        selfdev = resolve(d.name, d.ip)
        if upstream is None or selfdev is None or upstream.id == selfdev.id:
            continue
        mac = _norm_mac(d.mac)
        row = existing.get(mac)
        if row is None:
            row = ApLocation(ap_mac=mac)
            session.add(row)
            existing[mac] = row
        row.ap_name = d.name or selfdev.hostname
        row.device_id = upstream.id
        row.port = None
        row.source = "unifi-switch"
        row.status = "online"
        row.synced_at = now
        row.located_at = now
