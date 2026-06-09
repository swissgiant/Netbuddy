from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters import MockTransport, build_adapter
from netbuddy.db.models import (
    ArpEntry,
    Device,
    DeviceType,
    DiscoveryStatus,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
)
from netbuddy.services.discovery import run_discovery

_FIXTURES = Path(__file__).parent.parent / "adapters" / "fixtures" / "dell_os10"
_COMMANDS = {
    "show version": "show_version.txt",
    "show license status": "show_license_status.txt",
    "show interface status": "show_interface_status.txt",
    "show lldp neighbors detail": "show_lldp_neighbors_detail.txt",
    "show mac address-table": "show_mac_address-table.txt",
    "show ip arp": "show_ip_arp.txt",
}


def _responses(overrides: dict[str, str] | None = None) -> dict[str, str]:
    resp = {cmd: (_FIXTURES / f).read_text() for cmd, f in _COMMANDS.items()}
    resp.update(overrides or {})
    return resp


async def _device(session: AsyncSession) -> Device:
    device = Device(
        hostname="SW2",
        mgmt_ip="10.123.40.3",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    session.add(device)
    await session.flush()
    return device


async def test_discovery_persists_inventory(db_session: AsyncSession) -> None:
    device = await _device(db_session)
    adapter = build_adapter("dell_os10", MockTransport(_responses()))

    run = await run_discovery(db_session, device, adapter)

    assert run.status is DiscoveryStatus.SUCCESS
    # system_info aus echten Captures
    assert device.model == "S5248F-ON"
    assert device.os_version == "10.5.2.6"
    assert device.serial_number == "9GTP363"
    assert device.last_seen is not None

    interfaces = (
        (await db_session.execute(select(Interface).where(Interface.device_id == device.id)))
        .scalars()
        .all()
    )
    names = {i.name for i in interfaces}
    assert {"Eth 1/1/1", "Eth 1/1/2", "Eth 1/1/3"} <= names

    neighbors = (
        (
            await db_session.execute(
                select(LldpNeighbor).where(LldpNeighbor.local_device_id == device.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(neighbors) == 2

    macs = (
        (
            await db_session.execute(
                select(MacAddressEntry).where(MacAddressEntry.device_id == device.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(macs) == 4

    arp = (
        (await db_session.execute(select(ArpEntry).where(ArpEntry.device_id == device.id)))
        .scalars()
        .all()
    )
    assert len(arp) == 4
    # MAC kanonisch (12 Hex, kleingeschrieben, keine Trenner) abgelegt
    assert {a.mac for a in arp} >= {"000015c6ca49", "90b11cf4aace"}


async def test_discovery_is_idempotent_and_replaces_volatile(db_session: AsyncSession) -> None:
    device = await _device(db_session)
    adapter = build_adapter("dell_os10", MockTransport(_responses()))
    await run_discovery(db_session, device, adapter)
    # zweiter Lauf darf MAC/LLDP nicht duplizieren
    await run_discovery(db_session, device, adapter)
    macs = (
        (
            await db_session.execute(
                select(MacAddressEntry).where(MacAddressEntry.device_id == device.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(macs) == 4  # ersetzt, nicht verdoppelt


async def test_discovery_partial_on_capability_error(db_session: AsyncSession) -> None:
    device = await _device(db_session)
    # MAC-Befehl fehlt → read_mac_table wirft → PARTIAL
    responses = {k: v for k, v in _responses().items() if k != "show mac address-table"}
    adapter = build_adapter("dell_os10", MockTransport(responses))

    run = await run_discovery(db_session, device, adapter)

    assert run.status is DiscoveryStatus.PARTIAL
    assert any(e["capability"] == "read_mac_table" for e in run.errors)
