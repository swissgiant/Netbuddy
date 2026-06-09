from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters import MockTransport, build_adapter
from netbuddy.db.models import ArpEntry, Device, DeviceType, Host
from netbuddy.services.discovery import run_discovery
from netbuddy.services.hosts import correlate_hosts, normalize_mac
from netbuddy.services.locate import locate

_FIXTURES = Path(__file__).parent.parent / "adapters" / "fixtures" / "dell_os10"
_COMMANDS = {
    "show version": "show_version.txt",
    "show license status": "show_license_status.txt",
    "show interface status": "show_interface_status.txt",
    "show lldp neighbors detail": "show_lldp_neighbors_detail.txt",
    "show mac address-table": "show_mac_address-table.txt",
    "show ip arp": "show_ip_arp.txt",
}

# Reverse-DNS-Fake: IP → Name, deterministisch ohne echtes DNS.
_DNS = {
    "10.0.0.1": "gateway.lab.local",
    "10.0.0.20": "printer-2og.lab.local",
    "10.0.0.21": "nas01.lab.local",
}


async def _fake_resolver(ip: str) -> str | None:
    return _DNS.get(ip)


def _responses() -> dict[str, str]:
    return {cmd: (_FIXTURES / f).read_text() for cmd, f in _COMMANDS.items()}


async def _discovered_device(session: AsyncSession) -> Device:
    device = Device(
        hostname="SW2",
        mgmt_ip="10.123.40.3",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    session.add(device)
    await session.flush()
    adapter = build_adapter("dell_os10", MockTransport(_responses()))
    await run_discovery(session, device, adapter)
    return device


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00:15:c6:ca:49", "000015c6ca49"),
        ("0000.15c6.ca49", "000015c6ca49"),
        ("00-00-15-C6-CA-49", "000015c6ca49"),
        ("zzzz", ""),
        ("00:00:15", ""),
    ],
)
def test_normalize_mac(raw: str, expected: str) -> None:
    assert normalize_mac(raw) == expected


async def test_correlate_hosts_resolves_names(db_session: AsyncSession) -> None:
    await _discovered_device(db_session)

    summary = await correlate_hosts(db_session, _fake_resolver)

    assert summary["hosts"] == 4  # vier ARP-Einträge → vier Hosts
    assert summary["resolved"] == 3  # 192.168.1.5 hat keinen DNS-Namen

    hosts = {h.mac: h for h in (await db_session.execute(select(Host))).scalars()}
    assert hosts["000015c6ca49"].ip_address == "10.0.0.1"
    assert hosts["000015c6ca49"].name == "gateway.lab.local"
    assert hosts["e4f0043e2d86"].name is None  # unaufgelöst, aber Host existiert


async def test_correlate_hosts_is_idempotent(db_session: AsyncSession) -> None:
    await _discovered_device(db_session)
    await correlate_hosts(db_session, _fake_resolver)
    await correlate_hosts(db_session, _fake_resolver)

    hosts = (await db_session.execute(select(Host))).scalars().all()
    assert len(hosts) == 4  # Upsert über MAC, keine Duplikate


async def test_locate_finds_host_by_name(db_session: AsyncSession) -> None:
    await _discovered_device(db_session)
    await correlate_hosts(db_session, _fake_resolver)

    results = await locate(db_session, "nas01")

    host_hits = [r for r in results if r.kind == "host"]
    assert host_hits, "Host per Name nicht gefunden"
    hit = host_hits[0]
    assert hit.name == "nas01.lab.local"
    assert hit.device_hostname == "SW2"
    # MAC 34:17:.. hängt laut MAC-Table an ethernet1/1/1 → normalisiert auf den Interface-Namen
    assert hit.port == "Eth 1/1/1"
    assert hit.ip_address == "10.0.0.21"


async def test_locate_finds_host_by_ip(db_session: AsyncSession) -> None:
    await _discovered_device(db_session)
    await correlate_hosts(db_session, _fake_resolver)

    results = await locate(db_session, "10.0.0.20")
    assert any(r.kind == "host" and r.name == "printer-2og.lab.local" for r in results)


async def test_arp_entries_are_replaced_per_run(db_session: AsyncSession) -> None:
    device = await _discovered_device(db_session)
    adapter = build_adapter("dell_os10", MockTransport(_responses()))
    await run_discovery(db_session, device, adapter)

    arp = (
        (await db_session.execute(select(ArpEntry).where(ArpEntry.device_id == device.id)))
        .scalars()
        .all()
    )
    assert len(arp) == 4  # ersetzt, nicht verdoppelt
