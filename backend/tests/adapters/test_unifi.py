from typing import Any

import pytest

from netbuddy.adapters import available_adapters
from netbuddy.adapters.unifi import DeviceNotFoundError, UnifiAdapter

_PAYLOAD: dict[str, Any] = {
    "data": [
        {
            "ip": "10.123.40.3",
            "name": "BLS-SW-CU-01",
            "model": "USL48",
            "version": "6.6.55",
            "serial": "F4E2C6AABBCC",
            "port_table": [
                {
                    "port_idx": 1,
                    "name": "uplink",
                    "enable": True,
                    "up": True,
                    "speed": 1000,
                    "media": "GE",
                },
                {
                    "port_idx": 2,
                    "name": "ap-1",
                    "enable": True,
                    "up": False,
                    "speed": 0,
                    "media": "GE",
                },
            ],
            "lldp_table": [
                {
                    "local_port_name": "Port 1",
                    "chassis_id": "aa:bb:cc:dd:ee:ff",
                    "port_id": "Gi0/1",
                    "system_name": "core-sw",
                    "system_descr": "Dell OS10",
                    "port_descr": "downlink",
                }
            ],
            "mac_table": [{"mac": "aa:bb:cc:00:11:22", "port_name": "uplink", "vlan": 10}],
        },
        {"ip": "10.123.40.99", "name": "other"},
    ]
}


def _adapter() -> UnifiAdapter:
    class _FakeClient:
        async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
            return _PAYLOAD

    return UnifiAdapter(_FakeClient(), match_ip="10.123.40.3", options={"site": "default"})


async def test_system_info() -> None:
    info = await _adapter().get_system_info()
    assert info.vendor == "ubiquiti"
    assert info.model == "USL48"
    assert info.os_version == "6.6.55"
    assert info.serial_number == "F4E2C6AABBCC"


async def test_interfaces_and_status() -> None:
    interfaces = await _adapter().get_interfaces()
    assert [i.name for i in interfaces] == ["uplink", "ap-1"]
    assert interfaces[0].oper_status.value == "up"
    assert interfaces[1].oper_status.value == "down"
    assert interfaces[0].speed_mbps == 1000


async def test_lldp_and_mac() -> None:
    adapter = _adapter()
    neighbors = await adapter.get_lldp_neighbors()
    assert neighbors[0].remote_system_name == "core-sw"
    macs = await adapter.get_mac_table()
    assert macs[0].mac_address == "aa:bb:cc:00:11:22"
    assert macs[0].interface == "uplink"
    assert macs[0].vlan_id == 10


async def test_device_not_found() -> None:
    class _FakeClient:
        async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
            return {"data": []}

    with pytest.raises(DeviceNotFoundError):
        await UnifiAdapter(
            _FakeClient(), match_ip="1.2.3.4", options={"site": "default"}
        ).get_system_info()


def test_unifi_deregistered_replaced_by_unifi_local() -> None:
    # Der alte `unifi`-API-Adapter (Token/HttpxApiClient) ist deregistriert — der lokale
    # UniFi-Zugriff läuft jetzt über `unifi_local` (UnifiConsole, Cookie-Login).
    catalogue = available_adapters()
    assert "unifi" not in catalogue
    assert "unifi_local" in catalogue
