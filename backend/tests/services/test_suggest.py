from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    ArpEntry,
    Device,
    DeviceType,
    Host,
    Interface,
    LldpNeighbor,
    MacAddressEntry,
    MacEntryType,
)
from netbuddy.services.crawl import guess_adapter, guess_device_type
from netbuddy.services.suggest import suggest_devices


async def _core(db_session: AsyncSession) -> tuple[Device, Interface]:
    core = Device(
        hostname="core",
        mgmt_ip="10.0.0.1",
        vendor="dell",
        device_type=DeviceType.SWITCH,
        adapter_id="dell_os10",
    )
    db_session.add(core)
    await db_session.flush()
    iface = Interface(device_id=core.id, name="Eth 1/1/25")
    db_session.add(iface)
    await db_session.flush()
    return core, iface


def _mac_entry(core: Device, iface: Interface, mac: str) -> MacAddressEntry:
    return MacAddressEntry(
        device_id=core.id,
        interface_id=iface.id,
        mac_address=mac,
        vlan_id=10,
        entry_type=MacEntryType.DYNAMIC,
    )


async def test_unified_merges_lldp_and_mac_by_mac(db_session: AsyncSession) -> None:
    core, iface = await _core(db_session)
    # Gerät meldet sich per LLDP UND steht in der MAC-Tabelle → EIN Eintrag, beide Quellen
    db_session.add(
        LldpNeighbor(
            local_device_id=core.id,
            local_interface_id=iface.id,
            remote_chassis_id="64:9d:99:2f:89:66",
            remote_port_id="eth-0-53",
            remote_system_name="bls-sw-56",
            remote_system_description="Fiberstore S5800",
        )
    )
    db_session.add(_mac_entry(core, iface, "64:9d:99:2f:89:66"))
    await db_session.flush()

    suggestions = await suggest_devices(db_session)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert sorted(s.sources) == ["lldp", "mac"]
    assert s.name == "bls-sw-56"
    assert s.vendor is not None and "Fs Com" in s.vendor
    assert s.guessed_adapter == "fs_ruijie"  # aus "Fiberstore"-Beschreibung


async def test_unified_mac_only_with_arp_and_dns(db_session: AsyncSession) -> None:
    core, iface = await _core(db_session)
    db_session.add(_mac_entry(core, iface, "d4:76:a0:00:00:01"))  # Fortinet, kein LLDP
    db_session.add(_mac_entry(core, iface, "b0:4f:13:39:0e:c0"))  # Dell → gefiltert
    db_session.add(
        ArpEntry(device_id=core.id, ip_address="10.120.10.1", mac="d476a0000001", vlan_id=10)
    )
    db_session.add(Host(mac="d476a0000001", ip_address="10.120.10.1", name="fw1.bls.local"))
    await db_session.flush()

    suggestions = await suggest_devices(db_session)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.sources == ["mac"]
    assert s.name == "fw1"  # DNS-Kurzname als Fallback
    assert s.dns_name == "fw1.bls.local"
    assert s.ip_address == "10.120.10.1"
    assert s.guessed_adapter == "fortigate"


async def test_unified_excludes_inventory(db_session: AsyncSession) -> None:
    core, iface = await _core(db_session)
    # LLDP-Nachbar, der schon als Device existiert (per Hostname)
    db_session.add(
        Device(
            hostname="bls-sw-53",
            mgmt_ip="10.120.10.53",
            vendor="fs",
            device_type=DeviceType.SWITCH,
            adapter_id="fs_centec",
        )
    )
    db_session.add(
        LldpNeighbor(
            local_device_id=core.id,
            local_interface_id=iface.id,
            remote_chassis_id="64:9d:99:2f:89:66",
            remote_port_id="eth-0-53",
            remote_system_name="bls-sw-53",
        )
    )
    # MAC-Verdacht, dessen ARP-IP schon als Mgmt-IP existiert
    db_session.add(_mac_entry(core, iface, "d4:76:a0:00:00:01"))
    db_session.add(
        ArpEntry(device_id=core.id, ip_address="10.0.0.1", mac="d476a0000001", vlan_id=10)
    )
    await db_session.flush()

    assert await suggest_devices(db_session) == []


async def test_unified_lldp_ip_fallback_from_arp(db_session: AsyncSession) -> None:
    core, iface = await _core(db_session)
    # LLDP ohne Mgmt-Adresse, aber ARP kennt die Chassis-MAC
    db_session.add(
        LldpNeighbor(
            local_device_id=core.id,
            local_interface_id=iface.id,
            remote_chassis_id="64:9d:99:2f:89:66",
            remote_port_id="eth-0-1",
            remote_system_name="bls-sw-56",
        )
    )
    db_session.add(
        ArpEntry(device_id=core.id, ip_address="10.120.10.56", mac="649d992f8966", vlan_id=10)
    )
    await db_session.flush()

    (s,) = await suggest_devices(db_session)
    assert s.ip_address == "10.120.10.56"


def test_guess_adapter_oui_fallback() -> None:
    # ohne system_description: OUI der chassis_id entscheidet (nur eindeutige Vendor)
    assert guess_adapter(None, None, chassis_id="d4:76:a0:00:00:01") == "fortigate"
    assert guess_adapter(None, None, chassis_id="1c:6a:1b:4a:83:41") == "unifi"
    assert guess_adapter(None, None, chassis_id="64:9d:99:2f:89:66") is None  # FS mehrdeutig
    # system_description gewinnt vor OUI
    assert guess_adapter("Dell EMC Networking OS10", None, chassis_id="d4:76:a0:..") == "dell_os10"


def test_guess_device_type() -> None:
    assert guess_device_type("fortigate", None) is DeviceType.FIREWALL
    assert guess_device_type("unifi", "U7 Pro") is DeviceType.AP
    assert guess_device_type("unifi", "UniFi Access Point AC Pro") is DeviceType.AP
    assert guess_device_type("dell_os10", "Dell EMC Networking OS10") is DeviceType.SWITCH
