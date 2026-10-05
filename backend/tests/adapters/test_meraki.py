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
        {"lanIp": "10.0.0.7", "name": "ap-01", "model": "MR46E", "serial": "Q2XX-AP01-0000"},
    ],
    "/devices/Q2XX-1111-2222/switch/ports": [
        {"portId": "1", "name": "uplink", "enabled": True, "type": "trunk"},
        {"portId": "2", "name": "", "enabled": False, "type": "access"},
    ],
    # Echtes lldpCdp-Format (S00NSW101, Okt 2026): Nexus mit LLDP+managementAddress,
    # Meraki-Nachbar mit Präfix-Namen + CDP-Adresse, ein Port nur mit CDP.
    "/devices/Q2XX-1111-2222/lldpCdp": {
        "ports": {
            "1": {
                "lldp": {
                    "chassisId": "aa:bb:cc:dd:ee:ff",
                    "portId": "Gi0/1",
                    "systemName": "core",
                    "managementAddress": "10.0.0.1",
                    "portDescription": "to-ms-01",
                }
            },
            "11": {
                "cdp": {"deviceId": "9ce330d9f090", "address": "10.0.21.140", "portId": "Port 49"},
                "lldp": {
                    "chassisId": "9c:e3:30:d9:f0:90",
                    "portId": "49",
                    "systemName": "Meraki MS225-48FP - S00NSW140",
                    "systemDescription": "Meraki MS225-48FP Cloud Managed PoE Switch",
                },
            },
            "12": {
                "cdp": {
                    "deviceId": "bcdb09891d90",
                    "address": "10.0.21.104",
                    "portId": "Port 49",
                    "platform": "MS225-48FP",
                }
            },
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
    assert len(neighbors) == 3
    core = neighbors[0]
    assert (core.local_interface, core.remote_system_name) == ("1", "core")
    assert core.mgmt_address == "10.0.0.1"
    assert core.remote_port_description == "to-ms-01"
    # Meraki-Präfix wird auf den Gerätenamen reduziert, Mgmt-IP kommt aus CDP
    meraki = neighbors[1]
    assert meraki.remote_system_name == "S00NSW140"
    assert meraki.remote_port_id == "49"
    assert meraki.mgmt_address == "10.0.21.140"
    # nur CDP → trotzdem ein Nachbar
    cdp_only = neighbors[2]
    assert cdp_only.remote_chassis_id == "bcdb09891d90"
    assert cdp_only.remote_system_name == "bcdb09891d90"
    assert cdp_only.mgmt_address == "10.0.21.104"
    assert cdp_only.remote_system_description == "MS225-48FP"


async def test_ap_has_no_switch_ports() -> None:
    ap = MerakiAdapter(_FakeClient(), match_ip="10.0.0.7", options={"org_id": "O1"})
    assert (await ap.get_system_info()).device_type.value == "ap"
    assert await ap.get_interfaces() == []


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
