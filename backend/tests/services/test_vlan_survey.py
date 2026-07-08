from netbuddy.services.vlan_survey import (
    DeviceVlanInfo,
    SviInfo,
    _expand_vlan_list,
    aggregate_survey,
    parse_cli_config,
)

_OS6 = """\
!Current Configuration:
vlan 90,101-116,120,130
vlan 90
name "MGMT"
exit
interface vlan 1
ip address 10.120.10.51 255.255.0.0
exit
interface vlan 90
ip address 10.120.90.1 255.255.255.0
ip helper-address 10.120.20.10
ip helper-address 10.120.20.11
exit
interface Gi1/0/25
switchport access vlan 101
exit
interface Tw1/0/1
switchport mode trunk
exit
"""

_FS = """\
vlan database
 vlan 101-116,120,130
!
interface eth-0-24
 switchport mode trunk
 switchport trunk allowed vlan add 101-116,120,130
!
"""


def test_expand_vlan_list() -> None:
    assert _expand_vlan_list("90,101-103,120") == [90, 101, 102, 103, 120]
    assert _expand_vlan_list("add") == []


def test_parse_os6_config_names_svis_helpers_access() -> None:
    info = parse_cli_config("BLS-SW-51", _OS6)
    assert info.vlans[90] == "MGMT"  # Name erkannt
    assert 101 in info.vlans and 130 in info.vlans
    svi90 = next(s for s in info.svis if s.vlan_id == 90)
    assert svi90.ip == "10.120.90.1"
    assert svi90.helpers == ["10.120.20.10", "10.120.20.11"]  # DHCP-Relay!
    svi1 = next(s for s in info.svis if s.vlan_id == 1)
    assert svi1.ip == "10.120.10.51"
    assert info.access_ports[101] == 1


def test_parse_fs_trunk_lists() -> None:
    info = parse_cli_config("BLS-SW-55", _FS)
    assert 101 in info.vlans and 120 in info.vlans
    assert 116 in info.trunk_vlans and 130 in info.trunk_vlans


def test_aggregate_merges_names_gateways_dhcp() -> None:
    sw = parse_cli_config("SW1", _OS6)
    sw.site = "Sulgen"
    fw = DeviceVlanInfo(
        hostname="FW1",
        site="Sulgen",
        kind="firewall",
        vlans={90: "Mgmt-Netz", 101: "Testnetz01"},
        svis=[SviInfo(vlan_id=101, ip="10.220.101.1")],
        dhcp_server_vlans=[101],
    )
    out = aggregate_survey([sw, fw], {})
    vlans = {e["vlan_id"]: e for e in out["sites"]["Sulgen"]}
    v90 = vlans[90]
    assert sorted(v90["names"]) == ["MGMT", "Mgmt-Netz"]  # Namens-Konflikt sichtbar
    assert {g["device"] for g in v90["gateways"]} == {"SW1"}
    assert v90["dhcp_helpers"][0]["helpers"] == ["10.120.20.10", "10.120.20.11"]
    v101 = vlans[101]
    assert v101["dhcp_servers"] == ["FW1"]
    assert v101["gateways"][0]["ip"] == "10.220.101.1"
    assert v101["access_ports"] == 1
