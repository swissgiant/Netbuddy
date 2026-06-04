from typing import Any

import pytest

from netbuddy.adapters import adapter_kind, available_adapters
from netbuddy.adapters.base import CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.fortigate import FortigateAdapter
from netbuddy.db.models import DeviceType

_ROUTES: dict[str, Any] = {
    "/api/v2/monitor/system/status": {
        "hostname": "fw-it-01",
        "version": "v7.2.5",
        "serial": "FGT60FTK1234ABCD",
        "results": {"model": "FortiGate-60F"},
    },
    "/api/v2/monitor/system/interface": {
        "results": {
            "wan1": {
                "name": "wan1",
                "alias": "internet",
                "status": "up",
                "link": True,
                "speed": "1000",
                "mac": "00:11:22:33:44:55",
            },
            "internal1": {"name": "internal1", "status": "down", "link": False, "speed": "0"},
        }
    },
}


class _FakeClient:
    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return _ROUTES[path]


def _adapter() -> FortigateAdapter:
    return FortigateAdapter(_FakeClient())


async def test_system_info_is_firewall() -> None:
    info = await _adapter().get_system_info()
    assert info.vendor == "fortinet"
    assert info.device_type is DeviceType.FIREWALL
    assert info.model == "FortiGate-60F"
    assert info.os_version == "v7.2.5"
    assert info.serial_number == "FGT60FTK1234ABCD"


async def test_interfaces() -> None:
    interfaces = await _adapter().get_interfaces()
    by_name = {i.name: i for i in interfaces}
    assert by_name["wan1"].admin_status.value == "up"
    assert by_name["wan1"].oper_status.value == "up"
    assert by_name["wan1"].speed_mbps == 1000
    assert by_name["internal1"].oper_status.value == "down"


async def test_lldp_mac_not_supported() -> None:
    adapter = _adapter()
    with pytest.raises(CapabilityNotSupportedError):
        await adapter.get_lldp_neighbors()
    with pytest.raises(CapabilityNotSupportedError):
        await adapter.get_mac_table()


def test_registered_as_firewall_api_adapter() -> None:
    assert adapter_kind("fortigate") == "api"
    assert available_adapters()["fortigate"] == frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES}
    )
