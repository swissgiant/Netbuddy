"""Gezielte Feld-Assertions je Vendor-Profil (über die reine Conformance hinaus).

System-Info ist gegen echte `show version`-Captures validiert; interfaces/lldp/mac gegen
die mitgelieferten (doku-/research-abgeleiteten) Fixtures.
"""

from pathlib import Path

from netbuddy.adapters import MockTransport, SwitchAdapter, build_adapter
from netbuddy.adapters.registry import get_profile

_FIXTURES = Path(__file__).parent / "fixtures"


def _adapter(adapter_id: str) -> SwitchAdapter:
    """Baut den Adapter mit allen Befehl-Fixtures seines Profils."""
    responses: dict[str, str] = {}
    for spec in get_profile(adapter_id).capabilities.values():
        for source in spec.sources:
            fixture = _FIXTURES / adapter_id / f"{source.command.replace(' ', '_')}.txt"
            responses[source.command] = fixture.read_text()
    return build_adapter(adapter_id, MockTransport(responses))


async def test_dell_os10() -> None:
    a = _adapter("dell_os10")
    info = await a.get_system_info()  # validiert (SW2)
    assert (info.vendor, info.model, info.os_version, info.serial_number) == (
        "dell",
        "S5248F-ON",
        "10.5.2.6",
        "9GTP363",
    )
    interfaces = await a.get_interfaces()
    down = next(i for i in interfaces if i.name == "Eth 1/1/2")
    assert down.oper_status.value == "down"
    assert down.description is None
    neighbors = await a.get_lldp_neighbors()
    assert neighbors[0].remote_system_name == "core-sw-01"
    macs = await a.get_mac_table()
    assert any(m.entry_type.value == "static" for m in macs)


async def test_dell_os6() -> None:
    a = _adapter("dell_os6")
    info = await a.get_system_info()  # validiert (BLS-SW-51)
    assert (info.vendor, info.model, info.os_version) == ("dell", "N2248PX-ON", "6.6.3.15")
    assert info.serial_number == "TH08571NCET00183004S"
    interfaces = await a.get_interfaces()
    assert {i.name for i in interfaces} >= {"Gi1/0/1", "Gi1/0/2", "Te1/0/1"}
    assert next(i for i in interfaces if i.name == "Gi1/0/1").oper_status.value == "down"
    assert next(i for i in interfaces if i.name == "Te1/0/1").speed_mbps == 10000
    neighbors = await a.get_lldp_neighbors()
    assert any(n.remote_system_name == "BLS-AP-CU-07" for n in neighbors)


async def test_fs_ruijie() -> None:
    a = _adapter("fs_ruijie")
    info = await a.get_system_info()  # validiert (FS# / N8560-48BC)
    assert (info.vendor, info.model, info.serial_number) == ("fs", "N8560-48BC", "G1S90KY000796")
    assert info.os_version is not None and info.os_version.startswith("N8560_FSOS")
    interfaces = await a.get_interfaces()
    ten = next(i for i in interfaces if i.name.startswith("TenGigabit"))
    assert ten.speed_mbps == 10000
    # FILTER-Zeile ohne Interface wird via drop_when_empty verworfen
    macs = await a.get_mac_table()
    assert len(macs) == 3
    assert all(m.interface for m in macs)


async def test_fs_centec() -> None:
    a = _adapter("fs_centec")
    info = await a.get_system_info()  # validiert (BLS-SW-56 / S5800)
    assert (info.vendor, info.model, info.os_version) == ("fs", "S5800", "7.0.4.21")
    interfaces = await a.get_interfaces()
    admin_down = next(i for i in interfaces if i.name == "eth-0-3")
    assert admin_down.oper_status.value == "down"  # "admin down" → down
    neighbors = await a.get_lldp_neighbors()
    # echtes Centec-Block-Format (Capture bls-sw-53): Filldown-Port, Doppel-Advertisement der PCs
    assert neighbors[0].local_interface == "eth-0-20"
    assert neighbors[1].remote_system_name == "PC-3NRJKX3"
    assert neighbors[1].mgmt_address is None  # "0.0.0.0" wird via ip_or_none verworfen
    sw2 = next(n for n in neighbors if n.remote_system_name == "SW2")
    assert sw2.local_interface == "eth-0-53"
    assert sw2.mgmt_address == "192.168.245.11"
    arp = await a.get_arp()
    assert arp[0].ip_address == "10.120.10.1"
    assert arp[0].mac_address == "649d.992f.0001"
