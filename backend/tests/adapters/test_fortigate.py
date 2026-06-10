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
            "VLAN-120": {"name": "VLAN-120", "status": "up", "link": True, "speed": "0"},
        }
    },
    "/api/v2/monitor/network/arp": {
        "results": [
            {"ip": "10.120.10.51", "mac": "b0:4f:13:39:0e:c0", "interface": "internal1"},
            {"ip": "10.120.10.53", "mac": "64:9d:99:2f:89:66", "interface": "internal1"},
            {"ip": "10.120.10.99", "mac": ""},  # unvollständig → verworfen
        ]
    },
    "/api/v2/cmdb/system/interface": {
        "results": [
            {"name": "wan1", "type": "physical"},
            {"name": "internal1", "type": "physical"},
            {"name": "VLAN-120", "type": "vlan", "interface": "internal1", "vlanid": 120},
        ]
    },
    "/api/v2/monitor/vpn/ipsec": {
        "results": [
            {
                "name": "to-grosuplje",
                "rgwy": "203.0.113.7",
                "proxyid": [
                    {
                        "status": "up",
                        "proxy_src": [{"subnet": "10.120.0.0/16"}],
                        "proxy_dst": [{"subnet": "10.121.0.0/16"}],
                    }
                ],
            },
            {"name": "to-partner-x", "rgwy": "198.51.100.9", "proxyid": []},
        ]
    },
    "/api/v2/monitor/network/lldp/neighbors": {
        "results": [
            {
                "port": "internal1",
                "chassis_id": "8c:47:be:bf:f6:c1",
                "port_id": "ethernet1/1/40",
                "system_name": "SW2",
                "system_description": "Dell EMC Networking OS10",
                "mgmt_address": "10.120.10.48",
            }
        ]
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


async def test_arp_from_gateway() -> None:
    arp = await _adapter().get_arp()
    assert len(arp) == 2  # Zeile ohne MAC verworfen
    assert arp[0].ip_address == "10.120.10.51"
    assert arp[0].mac_address == "b0:4f:13:39:0e:c0"
    assert arp[0].interface == "internal1"


async def test_lldp_neighbors() -> None:
    neighbors = await _adapter().get_lldp_neighbors()
    assert len(neighbors) == 1
    assert neighbors[0].remote_system_name == "SW2"
    assert neighbors[0].mgmt_address == "10.120.10.48"


async def test_mac_table_not_supported() -> None:
    with pytest.raises(CapabilityNotSupportedError):
        await _adapter().get_mac_table()


def test_registered_as_firewall_api_adapter() -> None:
    assert adapter_kind("fortigate") == "api"
    assert available_adapters()["fortigate"] == frozenset(
        {
            Capability.READ_SYSTEM_INFO,
            Capability.READ_INTERFACES,
            Capability.READ_ARP,
            Capability.READ_LLDP,
            Capability.READ_VPN_TUNNELS,
        }
    )


async def test_vpn_tunnels() -> None:
    tunnels = await _adapter().get_vpn_tunnels()
    by_name = {t.name: t for t in tunnels}
    assert by_name["to-grosuplje"].is_up is True
    assert by_name["to-grosuplje"].remote_subnets == ["10.121.0.0/16"]
    assert by_name["to-grosuplje"].local_subnets == ["10.120.0.0/16"]
    assert by_name["to-partner-x"].is_up is False  # keine Phase 2 up


async def test_interface_tree_from_cmdb() -> None:
    interfaces = await _adapter().get_interfaces()
    by_name = {i.name: i for i in interfaces}
    vlan = by_name["VLAN-120"]
    assert vlan.parent_name == "internal1"  # hängt unter dem physischen Port
    assert vlan.vlan_id == 120
    assert vlan.interface_type == "vlan"
    assert by_name["wan1"].parent_name is None
    assert by_name["wan1"].interface_type == "physical"
