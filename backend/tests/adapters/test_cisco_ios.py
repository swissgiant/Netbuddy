from pathlib import Path

from netbuddy.adapters import MockTransport, SwitchAdapter, build_adapter
from netbuddy.db.models import AdminStatus, DeviceType, MacEntryType, OperStatus

_FIXTURES = Path(__file__).parent / "fixtures" / "cisco_ios"

# CLI-Befehl → Fixture-Datei mit dem zugehörigen Canned-Output.
_COMMAND_FILES = {
    "show version": "show_version.txt",
    "show interfaces": "show_interfaces.txt",
    "show lldp neighbors detail": "show_lldp_neighbors_detail.txt",
    "show mac address-table": "show_mac_address-table.txt",
}


def _adapter() -> SwitchAdapter:
    responses = {
        command: (_FIXTURES / filename).read_text() for command, filename in _COMMAND_FILES.items()
    }
    return build_adapter("cisco_ios", MockTransport(responses))


async def test_get_system_info() -> None:
    info = await _adapter().get_system_info()
    assert info.hostname == "sw-lab-01"
    assert info.vendor == "cisco"
    assert info.model == "WS-C2960X-48FPD-L"
    assert info.os_version == "15.2(2)E7"
    assert info.serial_number == "FOC2150L0GH"
    assert info.device_type is DeviceType.SWITCH


async def test_get_interfaces() -> None:
    interfaces = await _adapter().get_interfaces()
    assert [i.name for i in interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
    ]

    up = interfaces[0]
    assert up.admin_status is AdminStatus.UP
    assert up.oper_status is OperStatus.UP
    assert up.description == "uplink-to-core"
    assert up.mac_address == "001a.2b3c.4d5e"
    assert up.mtu == 1500
    assert up.speed_mbps == 1000  # 1000000 Kbit → 1000 Mbit/s
    assert up.interface_type == "Gigabit Ethernet"

    down = interfaces[1]
    assert down.admin_status is AdminStatus.DOWN
    assert down.oper_status is OperStatus.DOWN
    assert down.description is None  # leeres ntc-Feld → None


async def test_get_lldp_neighbors() -> None:
    neighbors = await _adapter().get_lldp_neighbors()
    assert len(neighbors) == 2

    core = neighbors[0]
    assert core.local_interface == "Gi1/0/1"
    assert core.remote_chassis_id == "0011.2233.4455"
    assert core.remote_port_id == "Gi0/1"
    assert core.remote_port_description == "uplink-from-core"
    assert core.remote_system_name == "core-sw-01"
    assert core.remote_system_description is not None
    assert "Catalyst" in core.remote_system_description


async def test_get_mac_table_skips_cpu_and_maps_types() -> None:
    entries = await _adapter().get_mac_table()
    # Beide CPU-Einträge bleiben erhalten (interface == "CPU"); nichts wird verworfen.
    assert len(entries) == 5

    by_mac = {e.mac_address: e for e in entries}

    dynamic = by_mac["0011.2233.4455"]
    assert dynamic.interface == "Gi1/0/1"
    assert dynamic.vlan_id == 10
    assert dynamic.entry_type is MacEntryType.DYNAMIC

    static = by_mac["0066.7788.99ab"]
    assert static.entry_type is MacEntryType.STATIC
    assert static.vlan_id == 20

    cpu = by_mac["0100.0ccc.cccc"]
    assert cpu.interface == "CPU"
    assert cpu.vlan_id is None  # "All" ist keine Zahl → None


async def test_empty_output_yields_empty_lists() -> None:
    adapter = build_adapter(
        "cisco_ios",
        MockTransport(
            {
                "show interfaces": "",
                "show lldp neighbors detail": "",
                "show mac address-table": "",
            }
        ),
    )
    assert await adapter.get_interfaces() == []
    assert await adapter.get_lldp_neighbors() == []
    assert await adapter.get_mac_table() == []
