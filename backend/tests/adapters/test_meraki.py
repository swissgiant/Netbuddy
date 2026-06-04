from typing import Any

import pytest

from netbuddy.adapters import adapter_kind, available_adapters
from netbuddy.adapters.base import CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.meraki import MerakiAdapter, MerakiDeviceNotFoundError

_ROUTES: dict[str, Any] = {
    "/organizations/O1/devices": [
        {
            "lanIp": "10.0.0.5",
            "name": "ms-01",
            "model": "MS225-48",
            "firmware": "switch-15-21",
            "serial": "Q2XX-1111-2222",
        },
        {"lanIp": "10.0.0.6", "name": "other"},
    ],
    "/devices/Q2XX-1111-2222/switch/ports": [
        {"portId": "1", "name": "uplink", "enabled": True, "type": "trunk"},
        {"portId": "2", "name": "", "enabled": False, "type": "access"},
    ],
    "/devices/Q2XX-1111-2222/lldpCdp": {
        "ports": {
            "1": {
                "lldp": {"chassisId": "aa:bb:cc:dd:ee:ff", "portId": "Gi0/1", "systemName": "core"}
            }
        }
    },
}


class _FakeClient:
    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return _ROUTES[path]


def _adapter() -> MerakiAdapter:
    return MerakiAdapter(_FakeClient(), match_ip="10.0.0.5", options={"org_id": "O1"})


async def test_system_info() -> None:
    info = await _adapter().get_system_info()
    assert info.vendor == "cisco-meraki"
    assert info.model == "MS225-48"
    assert info.serial_number == "Q2XX-1111-2222"
    assert info.os_version == "switch-15-21"


async def test_interfaces() -> None:
    interfaces = await _adapter().get_interfaces()
    assert [i.name for i in interfaces] == ["uplink", "Port 2"]
    assert interfaces[0].admin_status.value == "up"
    assert interfaces[1].admin_status.value == "down"


async def test_lldp() -> None:
    neighbors = await _adapter().get_lldp_neighbors()
    assert len(neighbors) == 1
    assert neighbors[0].local_interface == "1"
    assert neighbors[0].remote_system_name == "core"


async def test_mac_not_supported() -> None:
    with pytest.raises(CapabilityNotSupportedError):
        await _adapter().get_mac_table()


async def test_device_not_found() -> None:
    with pytest.raises(MerakiDeviceNotFoundError):
        await MerakiAdapter(
            _FakeClient(), match_ip="9.9.9.9", options={"org_id": "O1"}
        ).get_system_info()


def test_registered_with_three_capabilities() -> None:
    assert adapter_kind("meraki") == "api"
    assert available_adapters()["meraki"] == frozenset(
        {Capability.READ_SYSTEM_INFO, Capability.READ_INTERFACES, Capability.READ_LLDP}
    )
