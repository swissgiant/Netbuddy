from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import InterfaceData
from netbuddy.db.models import (
    Device,
    DiscoveryRun,
    DiscoveryStatus,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
)


async def _interface_cache(session: AsyncSession, device_id: Any) -> dict[str, Interface]:
    stmt = select(Interface).where(Interface.device_id == device_id, Interface.deleted_at.is_(None))
    return {iface.name: iface for iface in (await session.execute(stmt)).scalars()}


async def _get_or_create_interface(
    session: AsyncSession, device_id: Any, name: str, cache: dict[str, Interface]
) -> Interface:
    if name in cache:
        return cache[name]
    iface = Interface(device_id=device_id, name=name)
    session.add(iface)
    await session.flush()
    cache[name] = iface
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
    iface.last_polled = now


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

    attempted = sum(
        1
        for c in (
            Capability.READ_SYSTEM_INFO,
            Capability.READ_INTERFACES,
            Capability.READ_LLDP,
            Capability.READ_MAC_TABLE,
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
