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
    # echtes Summary-Format (Live-Capture BLS-SW-52): APs + Core-Uplink
    assert any(n.remote_system_name == "BLS-AP-CH-30" for n in neighbors)
    sw2 = next(n for n in neighbors if n.remote_system_name == "SW2")
    assert sw2.local_interface == "Tw1/0/4"
    assert sw2.remote_port_id == "ethernet1/1/26"


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


async def test_cisco_nxos() -> None:
    a = _adapter("cisco_nxos")
    info = await a.get_system_info()  # validiert (s00ncs101 / N9K-C93180YC-FX3)
    assert (info.hostname, info.vendor, info.model, info.os_version, info.serial_number) == (
        "s00ncs101",
        "cisco",
        "C93180YC-FX3",
        "10.5(3)",
        "FIC30060D4E",
    )
    interfaces = await a.get_interfaces()  # echtes `show interface` (Live-Capture s00ncs101)
    assert {i.name for i in interfaces} == {
        "mgmt0",
        "Ethernet1/1",
        "Ethernet1/5",
        "port-channel54",
        "Vlan1063",
    }
    eth1 = next(i for i in interfaces if i.name == "Ethernet1/1")
    assert (eth1.admin_status.value, eth1.oper_status.value) == ("up", "up")
    assert eth1.description == "esx1-vmnic0"
    assert eth1.speed_mbps == 10000
    assert eth1.mtu == 9216
    absent = next(i for i in interfaces if i.name == "Ethernet1/5")
    assert absent.oper_status.value == "down"  # "down (XCVR not inserted)" → down
    assert absent.admin_status.value == "up"
    svi = next(i for i in interfaces if i.name == "Vlan1063")
    assert svi.admin_status.value == "up"  # "up, autostate enabled" → up
    assert svi.interface_type == "EtherSVI"
    neighbors = await a.get_lldp_neighbors()
    assert len(neighbors) == 2
    assert neighbors[0].remote_system_name == "s00ncs102"
    assert neighbors[0].local_interface == "Eth1/53"
    assert neighbors[0].mgmt_address == "10.137.63.252"
    assert neighbors[1].mgmt_address is None  # "0.0.0.0" wird via ip_or_none verworfen
    macs = await a.get_mac_table()
    assert len(macs) == 6
    assert any(m.entry_type.value == "static" for m in macs)
    assert next(m for m in macs if m.mac_address == "0000.5e00.013a").interface == "Po44"
    arp = await a.get_arp()
    assert arp[0].ip_address == "10.137.63.1"
    assert arp[0].interface == "Vlan1063"


async def test_aruba_procurve() -> None:
    a = _adapter("aruba_procurve")
    info = await a.get_system_info()  # validiert (swi-bhq-011, 2920-Stack bei Belimed)
    assert (info.hostname, info.vendor, info.model) == ("swi-bhq-011", "hp", "J9728A 2920-48G")
    assert (info.os_version, info.serial_number) == ("WB.15.17.0008", "SG55FLYMDF")
    interfaces = await a.get_interfaces()
    assert len(interfaces) == 192 and interfaces[0].name == "1/1"
    assert interfaces[0].admin_status.value == "up" and interfaces[0].oper_status.value == "down"
    neighbors = await a.get_lldp_neighbors()
    uplink = next(n for n in neighbors if n.local_interface == "1/48")
    assert uplink.remote_system_name == "swi-bhq-003"
    assert uplink.remote_chassis_id == "78:57:73:29:7d:a0"  # "78 57 73 29 7d a0" normalisiert
    macs = await a.get_mac_table()
    assert macs[0].mac_address == "00:50:56:84:01:d7" and macs[0].interface == "Trk10"
    arp = await a.get_arp()
    assert arp[0].ip_address == "10.131.63.1" and arp[0].mac_address == "b6:d0:04:02:00:02"


async def test_huawei_vrp() -> None:
    a = _adapter("huawei_vrp")
    info = await a.get_system_info()  # validiert (swi-bhq-001, CE6881 bei Belimed)
    assert (info.vendor, info.model, info.serial_number) == (
        "huawei",
        "CE6881-48S6CQ",
        "DU20C0000219",
    )
    assert info.os_version == "CE6881 V200R019C10SPC800"
    interfaces = await a.get_interfaces()
    assert next(i for i in interfaces if i.name == "10GE1/0/1").oper_status.value == "up"
    assert next(i for i in interfaces if i.name == "100GE1/0/3").oper_status.value == "down"
    neighbors = await a.get_lldp_neighbors()
    peer = next(n for n in neighbors if n.local_interface == "100GE1/0/1")
    assert peer.remote_system_name == "swi-bhq-002" and peer.remote_port_id == "100GE1/0/2"
    assert peer.remote_chassis_id == "a8:2b:cd:b4:74:01" and peer.mgmt_address == "192.168.255.2"
    assert all(n.remote_chassis_id for n in neighbors)  # kein Filldown-Leerrecord am Ende
    macs = await a.get_mac_table()
    assert macs[0].mac_address == "00:07:4d:c0:6b:e8" and macs[0].vlan_id == 1
    arp = await a.get_arp()
    assert any(e.ip_address == "172.16.1.10" and e.interface == "Eth-Trunk0" for e in arp)
    assert all(e.mac_address for e in arp)  # "Incomplete"-Zeilen verworfen


async def test_cisco_sb() -> None:
    a = _adapter("cisco_sb")
    info = await a.get_system_info()  # validiert (swi-bhq-020, CBS350-Stack bei Belimed)
    assert (info.hostname, info.model, info.os_version) == (
        "swi-bhq-020",
        "CBS350-12NP-4X",
        "3.1.1.7",
    )
    assert info.serial_number == "DNI272902LF"
    interfaces = await a.get_interfaces()
    assert next(i for i in interfaces if i.name == "fi1/0/1").oper_status.value == "up"
    assert next(i for i in interfaces if i.name == "fi1/0/4").oper_status.value == "down"
    neighbors = await a.get_lldp_neighbors()
    assert len(neighbors) == 11
    core = next(n for n in neighbors if n.local_interface == "te2/0/4")
    assert core.remote_system_name == "swi-bhq-001" and core.remote_port_id == "10GE1/0/46"
    nameless = next(n for n in neighbors if n.local_interface == "fi1/0/2")
    assert nameless.remote_system_name is None and nameless.remote_chassis_id == "EWP-J4DND43"
    arp = await a.get_arp()
    assert arp[0].vlan_id == 1063 and arp[0].mac_address == "b6:d0:04:02:00:02"


async def test_aruba_cx_live_captures() -> None:
    a = _adapter("aruba_cx")
    info = await a.get_system_info()  # validiert (swbat01, Aruba 6000 bei Belimed)
    assert (info.hostname, info.serial_number) == ("swbat01", "CN34L3J7S3")
    assert info.model == "R8N85A 6000 48G CL4 4SFP Swch" and info.os_version == "PL.10.08.1010"
    interfaces = await a.get_interfaces()
    lag = next(i for i in interfaces if i.name == "lag1")
    assert lag.description == "CATO" and lag.speed_mbps == 1000 and lag.oper_status.value == "up"
    first = next(i for i in interfaces if i.name == "1/1/1")
    assert first.description is None and first.oper_status.value == "down"
    neighbors = await a.get_lldp_neighbors()
    assert len(neighbors) == 1
    assert neighbors[0].remote_system_name == "apbat-001"
    assert neighbors[0].mgmt_address == "10.141.64.11"  # nur die IPv4 aus "v4,v6"
    arp = await a.get_arp()
    assert arp[0].mac_address == "b6:d0:04:04:24:52"
