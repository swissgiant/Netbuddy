from netbuddy.services.vlan_survey import (
    DeviceVlanInfo,
    SviInfo,
    VlanTransition,
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


def test_aggregate_collects_transitions_per_site() -> None:
    fw = DeviceVlanInfo(
        hostname="FW1",
        site="Sulgen",
        kind="firewall",
        vlans={130: "Gaestenetz"},
        transitions=[
            VlanTransition(vlan_id=130, to="internet", detail="x3", policy="Gaestenetz-Internet"),
            VlanTransition(vlan_id=101, to="vpn", detail="BLS-SLO", policy="Testnetz01-Mesh"),
        ],
    )
    out = aggregate_survey([fw], {})
    ts = out["transitions"]["Sulgen"]
    assert {t["to"] for t in ts} == {"internet", "vpn"}
    assert ts[0]["device"] == "FW1"


def test_parse_meraki_switch_ports() -> None:
    from netbuddy.services.vlan_survey import parse_meraki_switch_ports

    ports = [
        {"portId": "1", "type": "access", "vlan": 4, "voiceVlan": 60},
        {"portId": "2", "type": "access", "vlan": 4},
        {"portId": "3", "type": "trunk", "vlan": 1, "allowedVlans": "1,20,30-32"},
        {"portId": "4", "type": "trunk", "vlan": 1, "allowedVlans": "all"},  # ignoriert
        {"portId": "5", "type": "access", "vlan": None},  # ohne VLAN
    ]
    info = parse_meraki_switch_ports("S00NSW104", "S00 - Steelco HQ", ports)
    assert info.access_ports[4] == 2
    assert 60 in info.vlans  # voiceVlan registriert
    assert set(info.trunk_vlans) == {1, 20, 30, 31, 32}
    assert info.site == "S00 - Steelco HQ"


_PROCURVE_CFG = """hostname "swi-bhq-011"
trunk 1/48,2/48,3/48,4/48 trk10 lacp
vlan 1
   name "DEFAULT_VLAN"
   untagged 1/1-1/47,2/1-2/47
   ip address 10.131.63.211 255.255.255.0
   exit
vlan 1011
   name "Guest LAN"
   tagged 1/1-1/3,Trk10
   exit
vlan 1027
   name "Printers"
   untagged 1/31,1/41
   tagged Trk10
   exit
"""

_HUAWEI_CFG = """sysname swi-bhq-003
#
vlan batch 666 1000 1011 to 1013
#
vlan 666
 name Nirvana
vlan 1011
 description Guest LAN
#
interface Vlanif1063
 ip address 10.131.63.203 255.255.255.0
 dhcp select relay
 dhcp relay server-ip 10.131.11.10
#
interface Eth-Trunk1
 port link-type trunk
 port trunk allow-pass vlan 2 to 4094
#
interface XGigabitEthernet0/0/5
 port link-type access
 port default vlan 1011
#
interface XGigabitEthernet0/0/6
 port link-type trunk
 port trunk allow-pass vlan 666 1000 1011
#
"""

_CX_CFG = """hostname swbat01
vlan 1
vlan 500
    description Legacy
vlan 1064
    description AP Management
interface lag 1
    vlan trunk native 1
    vlan trunk allowed 1,1011,1027,1031-1033,1063-1064
interface 1/1/1
    vlan access 500
interface 1/1/46
    vlan access 1064
interface vlan 1063
    ip address 10.141.63.201/24
    ip helper-address 10.141.11.10
"""


def test_parse_procurve_vlan_blocks() -> None:
    info = parse_cli_config("swi-bhq-011", _PROCURVE_CFG)
    assert info.vlans == {1: "DEFAULT_VLAN", 1011: "Guest LAN", 1027: "Printers"}
    assert info.access_ports == {1: 94, 1027: 2}
    assert info.trunk_vlans == [1011, 1027]
    assert [(s.vlan_id, s.ip) for s in info.svis] == [(1, "10.131.63.211")]


def test_parse_huawei_vrp_config() -> None:
    info = parse_cli_config("swi-bhq-003", _HUAWEI_CFG)
    assert set(info.vlans) == {666, 1000, 1011, 1012, 1013, 1063}
    assert info.vlans[666] == "Nirvana" and info.vlans[1011] == "Guest LAN"
    assert info.access_ports == {1011: 1}
    assert info.trunk_vlans == [666, 1000, 1011]  # "2 to 4094" = Catch-all, zählt nicht
    svi = info.svis[0]
    assert (svi.vlan_id, svi.ip, svi.helpers) == (1063, "10.131.63.203", ["10.131.11.10"])


def test_parse_aruba_cx_config() -> None:
    info = parse_cli_config("swbat01", _CX_CFG)
    assert info.vlans[500] == "Legacy" and info.vlans[1064] == "AP Management"
    assert info.access_ports == {500: 1, 1064: 1}
    assert info.trunk_vlans == [1, 1011, 1027, 1031, 1032, 1033, 1063, 1064]
    svi = info.svis[0]
    assert (svi.vlan_id, svi.ip, svi.helpers) == (1063, "10.141.63.201", ["10.141.11.10"])
