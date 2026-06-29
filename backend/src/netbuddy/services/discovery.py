from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import InterfaceData
from netbuddy.db.models import (
    ArpEntry,
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DiscoveryRun,
    DiscoveryStatus,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
    VpnTunnel,
)
from netbuddy.services.hosts import normalize_mac
from netbuddy.services.ifname import normalize_interface_name


async def _interface_cache(session: AsyncSession, device_id: Any) -> dict[str, Interface]:
    """Cache, keyed by normalisiertem Namen, damit LLDP/MAC denselben Port treffen."""
    stmt = select(Interface).where(Interface.device_id == device_id, Interface.deleted_at.is_(None))
    return {
        normalize_interface_name(iface.name): iface
        for iface in (await session.execute(stmt)).scalars()
    }


async def _get_or_create_interface(
    session: AsyncSession, device_id: Any, name: str, cache: dict[str, Interface]
) -> Interface:
    key = normalize_interface_name(name)
    if key in cache:
        return cache[key]
    iface = Interface(device_id=device_id, name=name)
    session.add(iface)
    await session.flush()
    cache[key] = iface
    return iface


def _apply_interface(iface: Interface, data: InterfaceData, now: datetime) -> None:
    iface.if_index = data.if_index
    iface.description = data.description
    iface.admin_status = data.admin_status
    iface.oper_status = data.oper_status
    iface.mac_address = data.mac_address
    iface.speed_mbps = data.speed_mbps
    iface.mtu = data.mtu
    iface.interface_type = data.interface_type
    iface.parent_name = data.parent_name
    iface.vlan_id = data.vlan_id
    iface.last_polled = now


async def persist_interface_snapshot(
    session: AsyncSession,
    device: Device,
    interfaces: list[InterfaceData],
    *,
    triggered_by: str = "manual",
) -> DiscoveryRun:
    """Schreibt eine fertige Interface-Liste (z.B. vom UniFi-Controller) ins Inventar + Run.

    Für Geräte, deren Adapter keine Interfaces liefert (UniFi-Cloud), aber der lokale Controller
    schon. Upsert über ``(device_id, name)`` wie bei :func:`run_discovery`.
    """
    now = datetime.now(UTC)
    run = DiscoveryRun(
        triggered_by=triggered_by,
        seed_devices=[str(device.id)],
        status=DiscoveryStatus.RUNNING,
    )
    session.add(run)
    await session.flush()
    cache = await _interface_cache(session, device.id)
    for data in interfaces:
        iface = await _get_or_create_interface(session, device.id, data.name, cache)
        _apply_interface(iface, data, now)
    device.last_seen = now
    run.status = DiscoveryStatus.SUCCESS
    run.errors = []
    run.devices_found = 1
    run.finished_at = now
    await session.flush()
    return run


async def run_discovery(
    session: AsyncSession,
    device: Device,
    adapter: SwitchAdapter,
    *,
    triggered_by: str = "manual",
) -> DiscoveryRun:
    """Liest read-only aus und schreibt das Inventar in die ORM-Aggregate.

    Interfaces werden ge-upsertet (`(device_id, name)`); LLDP-Nachbarn und MAC-Table sind
    volatil und werden pro Lauf komplett ersetzt. Ein `DiscoveryRun` hält Status + Fehler fest.
    """
    now = datetime.now(UTC)
    run = DiscoveryRun(
        triggered_by=triggered_by,
        seed_devices=[str(device.id)],
        status=DiscoveryStatus.RUNNING,
    )
    session.add(run)
    await session.flush()

    caps = adapter.capabilities()
    errors: list[dict[str, str]] = []
    cache = await _interface_cache(session, device.id)

    if Capability.READ_SYSTEM_INFO in caps:
        try:
            info = await adapter.get_system_info()
            if info.model:
                device.model = info.model
            if info.os_version:
                device.os_version = info.os_version
            if info.serial_number:
                device.serial_number = info.serial_number
            device.last_seen = now
        except Exception as exc:
            errors.append(
                {"capability": "read_system_info", "error": f"{type(exc).__name__}: {exc}"}
            )

    if Capability.READ_INTERFACES in caps:
        try:
            for iface_data in await adapter.get_interfaces():
                iface = await _get_or_create_interface(session, device.id, iface_data.name, cache)
                _apply_interface(iface, iface_data, now)
            await session.flush()
        except Exception as exc:
            errors.append(
                {"capability": "read_interfaces", "error": f"{type(exc).__name__}: {exc}"}
            )

    if Capability.READ_LLDP in caps:
        try:
            neighbors = await adapter.get_lldp_neighbors()
            await session.execute(
                delete(LldpNeighbor).where(LldpNeighbor.local_device_id == device.id)
            )
            for neighbor in neighbors:
                iface = await _get_or_create_interface(
                    session, device.id, neighbor.local_interface, cache
                )
                session.add(
                    LldpNeighbor(
                        local_device_id=device.id,
                        local_interface_id=iface.id,
                        remote_chassis_id=neighbor.remote_chassis_id,
                        remote_port_id=neighbor.remote_port_id,
                        remote_port_description=neighbor.remote_port_description,
                        remote_system_name=neighbor.remote_system_name,
                        remote_system_description=neighbor.remote_system_description,
                        remote_mgmt_address=neighbor.mgmt_address,
                    )
                )
            await session.flush()
        except Exception as exc:
            errors.append({"capability": "read_lldp", "error": f"{type(exc).__name__}: {exc}"})

    if Capability.READ_MAC_TABLE in caps:
        try:
            entries = await adapter.get_mac_table()
            await session.execute(
                delete(MacAddressEntry).where(MacAddressEntry.device_id == device.id)
            )
            for entry in entries:
                iface = await _get_or_create_interface(session, device.id, entry.interface, cache)
                session.add(
                    MacAddressEntry(
                        device_id=device.id,
                        interface_id=iface.id,
                        mac_address=entry.mac_address,
                        vlan_id=entry.vlan_id,
                        entry_type=entry.entry_type,
                    )
                )
            await session.flush()
        except Exception as exc:
            errors.append({"capability": "read_mac_table", "error": f"{type(exc).__name__}: {exc}"})

    if Capability.READ_ARP in caps:
        try:
            arp_entries = await adapter.get_arp()
            await session.execute(delete(ArpEntry).where(ArpEntry.device_id == device.id))
            for arp in arp_entries:
                mac = normalize_mac(arp.mac_address)
                if not mac:
                    continue
                session.add(
                    ArpEntry(
                        device_id=device.id,
                        ip_address=arp.ip_address,
                        mac=mac,
                        vlan_id=arp.vlan_id,
                    )
                )
            await session.flush()
        except Exception as exc:
            errors.append({"capability": "read_arp", "error": f"{type(exc).__name__}: {exc}"})

    if Capability.READ_VPN_TUNNELS in caps:
        try:
            tunnels = await adapter.get_vpn_tunnels()
            # Upsert über (device_id, name): das Admin-Flag `relevant` (Partner-Tunnel
            # ausblenden) muss Discovery-Läufe überleben — kein blindes Ersetzen.
            existing_tunnels = {
                t.name: t
                for t in (
                    await session.execute(select(VpnTunnel).where(VpnTunnel.device_id == device.id))
                ).scalars()
            }
            seen_names = set()
            for tun in tunnels:
                seen_names.add(tun.name)
                row = existing_tunnels.get(tun.name)
                if row is None:
                    row = VpnTunnel(device_id=device.id, name=tun.name)
                    session.add(row)
                row.remote_gateway = tun.remote_gateway
                row.is_up = tun.is_up
                row.local_subnets = tun.local_subnets
                row.remote_subnets = tun.remote_subnets
            for name, row in existing_tunnels.items():
                if name not in seen_names:
                    await session.delete(row)
            await session.flush()
        except Exception as exc:
            errors.append(
                {"capability": "read_vpn_tunnels", "error": f"{type(exc).__name__}: {exc}"}
            )

    attempted = sum(
        1
        for c in (
            Capability.READ_SYSTEM_INFO,
            Capability.READ_INTERFACES,
            Capability.READ_LLDP,
            Capability.READ_MAC_TABLE,
            Capability.READ_ARP,
            Capability.READ_VPN_TUNNELS,
        )
        if c in caps
    )
    if not errors:
        run.status = DiscoveryStatus.SUCCESS
    elif len(errors) >= attempted:
        run.status = DiscoveryStatus.FAILED
    else:
        run.status = DiscoveryStatus.PARTIAL
    run.errors = errors
    run.devices_found = 1
    run.finished_at = now
    await session.flush()
    return run


ScheduledAdapterProvider = Callable[
    [Device, Credential], AbstractAsyncContextManager[SwitchAdapter]
]


async def run_scheduled_discovery(
    session: AsyncSession, adapter_provider: ScheduledAdapterProvider
) -> dict[str, Any]:
    """Discovert alle aktiven Geräte, die eine SSH-Credential haben (für den geplanten Lauf).

    Read-only; pro Gerät wird die verknüpfte SSH-Credential genutzt. Fehler je Gerät werden
    gesammelt, nicht hochgereicht.
    """
    stmt = (
        select(Device, Credential)
        .join(DeviceCredential, DeviceCredential.device_id == Device.id)
        .join(Credential, Credential.id == DeviceCredential.credential_id)
        .where(
            Device.deleted_at.is_(None),
            Device.enabled.is_(True),
            DeviceCredential.protocol == CredentialProtocol.SSH,
            DeviceCredential.deleted_at.is_(None),
            Credential.deleted_at.is_(None),
        )
    )
    pairs = (await session.execute(stmt)).all()
    ok: list[str] = []
    errors: list[dict[str, str]] = []
    for device, credential in pairs:
        try:
            async with adapter_provider(device, credential) as adapter:
                await run_discovery(session, device, adapter, triggered_by="scheduled")
            ok.append(device.hostname)
        except Exception as exc:
            errors.append({"device": device.hostname, "error": f"{type(exc).__name__}: {exc}"})
    return {"devices": len(pairs), "ok": ok, "errors": errors}
