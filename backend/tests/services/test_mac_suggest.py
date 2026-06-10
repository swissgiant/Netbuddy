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
from netbuddy.services.mac_suggest import suggest_devices_from_mac_table


async def _core_with_macs(db_session: AsyncSession) -> tuple[Device, Interface]:
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
    macs = [
        "64:9d:99:2f:89:66",  # FS.com → Infrastruktur-Verdacht
        "d4:76:a0:00:00:01",  # Fortinet → Verdacht + adapter fortigate
        "b4:96:91:db:fa:17",  # Intel (Server-NIC) → kein Infra-Vendor
        "b0:4f:13:39:0e:c0",  # Dell → bewusst NICHT vorgeschlagen (Server/Laptops)
    ]
    for m in macs:
        db_session.add(
            MacAddressEntry(
                device_id=core.id,
                interface_id=iface.id,
                mac_address=m,
                vlan_id=10,
                entry_type=MacEntryType.DYNAMIC,
            )
        )
    await db_session.flush()
    return core, iface


async def test_mac_suggestions_filter_to_infra_vendors(db_session: AsyncSession) -> None:
    core, _ = await _core_with_macs(db_session)
    # ARP + Host liefern IP/Name für den FS-Verdacht
    db_session.add(
        ArpEntry(device_id=core.id, ip_address="10.120.10.53", mac="649d992f8966", vlan_id=10)
    )
    db_session.add(Host(mac="649d992f8966", ip_address="10.120.10.53", name="bls-sw-53.bls.local"))
    await db_session.flush()

    suggestions = await suggest_devices_from_mac_table(db_session)
    vendors = {s.vendor for s in suggestions}
    assert any("Fs Com" in v for v in vendors)
    assert any("Fortinet" in v for v in vendors)
    assert not any("Dell" in v for v in vendors)  # Server/Laptop-Vendor gefiltert
    assert not any("Intel" in v for v in vendors)

    fs = next(s for s in suggestions if "Fs Com" in s.vendor)
    assert fs.ip_address == "10.120.10.53"
    assert fs.name == "bls-sw-53.bls.local"
    assert fs.seen_on == ["core / Eth 1/1/25"]

    forti = next(s for s in suggestions if "Fortinet" in s.vendor)
    assert forti.guessed_adapter == "fortigate"


async def test_mac_suggestions_exclude_inventory_and_lldp(db_session: AsyncSession) -> None:
    core, iface = await _core_with_macs(db_session)
    # FS-MAC gehört zu einem Gerät, das schon im Inventar ist (per ARP-IP gematcht)
    db_session.add(
        ArpEntry(device_id=core.id, ip_address="10.120.10.53", mac="649d992f8966", vlan_id=10)
    )
    db_session.add(
        Device(
            hostname="bls-sw-53",
            mgmt_ip="10.120.10.53",
            vendor="fs",
            device_type=DeviceType.SWITCH,
            adapter_id="fs_centec",
        )
    )
    # Fortinet-Chassis ist schon als LLDP-Nachbar bekannt → läuft über LLDP-Vorschläge
    db_session.add(
        LldpNeighbor(
            local_device_id=core.id,
            local_interface_id=iface.id,
            remote_chassis_id="d4:76:a0:00:00:01",
            remote_port_id="wan1",
            remote_system_name="BLS-FW1",
        )
    )
    await db_session.flush()

    suggestions = await suggest_devices_from_mac_table(db_session)
    assert suggestions == []


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
