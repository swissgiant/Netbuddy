from typing import Any

from netbuddy.services.cato_policies import parse_policy, ref

_WAN: dict[str, Any] = {
    "policy": {
        "wanFirewall": {
            "policy": {
                "enabled": True,
                "audit": {"publishedTime": "2026-10-01T10:00:00Z", "publishedBy": "alex"},
                "rules": [
                    {
                        "rule": {
                            "id": "1",
                            "name": "Alex Kohler",
                            "description": None,
                            "index": 1,
                            "enabled": True,
                            "section": {"name": "Temp"},
                            "direction": "TO",
                            "action": "ALLOW",
                            "connectionOrigin": "ANY",
                            "source": {"site": [{"name": "BLS"}], "user": [{"name": "Alex"}]},
                            "destination": {"systemGroup": [{"name": "All Sites"}]},
                            "application": {},
                            "service": {
                                "standard": [{"name": "HTTP(S)"}],
                                "custom": [{"port": ["4118"], "protocol": "TCP"}],
                            },
                            "tracking": {"event": {"enabled": True}},
                            "exceptions": [{"name": "Ausnahme A"}],
                        }
                    },
                    {
                        "rule": {
                            "id": "233",
                            "name": "log blocked traffic",
                            "index": 233,
                            "enabled": True,
                            "section": {"name": "Block all"},
                            "direction": "BOTH",
                            "action": "BLOCK",
                            "source": {},
                            "destination": {},
                            "application": {},
                            "service": {},
                            "tracking": {"event": {"enabled": True}},
                        }
                    },
                ],
            }
        }
    }
}

_LAN: dict[str, Any] = {
    "policy": {
        "socketLan": {
            "policy": {
                "enabled": True,
                "audit": {},
                "rules": [
                    {
                        "rule": {
                            "id": "l1",
                            "name": "Riese LAN",
                            "index": 1,
                            "enabled": True,
                            "section": {"name": "S00"},
                            "site": {"site": [{"name": "SCO-S00-Riese"}], "group": []},
                            "source": {"vlan": [1062]},
                            "destination": {"subnet": ["10.137.63.0/24"]},
                            "direction": "TO",
                            "service": {},
                            "nat": {"enabled": True, "natType": "MASQUERADE"},
                            "transport": "WAN",
                            "firewall": {
                                "rule": [
                                    {
                                        "id": "f1",
                                        "name": "Mgmt → Switches",
                                        "index": 1,
                                        "enabled": True,
                                        "section": {"name": "x"},
                                        "source": {"ip": ["10.137.62.11"]},
                                        "destination": {"vlan": [1063]},
                                        "direction": "TO",
                                        "application": {},
                                        "service": {"simple": [{"name": "SSH"}]},
                                        "action": "ALLOW",
                                        "tracking": {"event": {"enabled": False}},
                                    }
                                ]
                            },
                        }
                    }
                ],
            }
        }
    }
}

_BYPASS: dict[str, Any] = {
    "policy": {
        "socketBypass": {
            "policy": {
                "enabled": True,
                "audit": {},
                "rules": [
                    {
                        "rule": {
                            "id": "b1",
                            "name": "Teams direkt",
                            "index": 1,
                            "enabled": False,
                            "section": {"name": "Bypass"},
                            "site": {"site": [], "group": [{"name": "Alle Sockets"}]},
                            "source": {},
                            "destination": {"application": [{"name": "Microsoft Teams"}]},
                            "service": {},
                            "action": {"port": "WAN1", "event": {"enabled": True}},
                            "exception": [],
                        }
                    }
                ],
            }
        }
    }
}


def test_ref_renders_compact_lines() -> None:
    assert ref(None) == "any"
    src = {"site": [{"name": "BLS"}], "ip": ["10.1.2.3"], "user": []}
    assert ref(src) == "site:BLS ip:10.1.2.3"
    assert ref({"ipRange": [{"from": "10.0.0.1", "to": "10.0.0.9"}]}) == "ipRange:10.0.0.1-10.0.0.9"


def test_parse_wan_policy() -> None:
    pol = parse_policy("wan", _WAN)
    assert pol.enabled and pol.published_by == "alex" and len(pol.rules) == 2
    first = pol.rules[0]
    assert first.action == "ALLOW" and first.direction == "TO" and first.section == "Temp"
    assert first.source == "site:BLS user:Alex" and first.destination == "systemGroup:All Sites"
    assert first.service == "HTTP(S),TCP/4118" and first.application is None
    assert first.extra == "ausnahmen:Ausnahme A"
    last = pol.rules[1]
    assert last.action == "BLOCK" and last.source == "any" and last.destination == "any"


def test_parse_lan_policy_flattens_firewall_subrules() -> None:
    pol = parse_policy("lan", _LAN)
    assert [r.name for r in pol.rules] == ["Riese LAN", "Riese LAN / Mgmt → Switches"]
    outer, inner = pol.rules
    assert outer.action == "LAN-REGEL" and outer.sites == "site:SCO-S00-Riese"
    assert outer.extra == "nat:MASQUERADE transport:WAN"
    assert inner.action == "ALLOW" and inner.sites == "site:SCO-S00-Riese"
    assert inner.service == "SSH" and inner.extra == "kein-log"


def test_parse_bypass_policy() -> None:
    pol = parse_policy("bypass", _BYPASS)
    rule = pol.rules[0]
    assert rule.action == "BYPASS WAN1" and not rule.enabled
    assert rule.sites == "group:Alle Sockets" and rule.destination == "application:Microsoft Teams"
