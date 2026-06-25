from typing import Any

from netbuddy.services.vpn_provision import (
    FirewallPlan,
    FortiOp,
    VpnEnd,
    VpnTunnelSpec,
    plan_site_to_site,
)


def _spec(**kw: Any) -> VpnTunnelSpec:
    return VpnTunnelSpec(
        name="GROSU-CUSANO",
        end_a=VpnEnd(
            site="Grosuplje",
            device_id="dev-a",
            wan_interface="wan1",
            peer_public_ip="203.0.113.2",  # öffentliche IP von B
            local_subnets=["10.121.0.0/16"],
            lan_interface="lan",
        ),
        end_b=VpnEnd(
            site="Cusano",
            device_id="dev-b",
            wan_interface="wan1",
            peer_public_ip="203.0.113.1",  # öffentliche IP von A
            local_subnets=["10.123.0.0/16"],
            lan_interface="internal",
        ),
        **kw,
    )


def _phase1(plan_fw: FirewallPlan) -> FortiOp:
    return next(o for o in plan_fw.operations if o.path.endswith("phase1-interface"))


def test_plan_both_firewalls() -> None:
    plan = plan_site_to_site(_spec())
    assert plan.psk_generated is True
    assert [fw.site for fw in plan.firewalls] == ["Grosuplje", "Cusano"]


def test_psk_shared_and_strong() -> None:
    plan = plan_site_to_site(_spec())
    a, b = _phase1(plan.firewalls[0]), _phase1(plan.firewalls[1])
    assert a.body["psksecret"] == b.body["psksecret"]  # identisch auf beiden Enden
    assert len(a.body["psksecret"]) >= 20  # stark


def test_provided_psk_not_regenerated() -> None:
    plan = plan_site_to_site(_spec(psk="my-fixed-secret"))
    assert plan.psk_generated is False
    assert _phase1(plan.firewalls[0]).body["psksecret"] == "my-fixed-secret"


def test_remote_selectors_mirror_peer_local_subnets() -> None:
    plan = plan_site_to_site(_spec())
    # Phase1: remote-gw = peer public IP; Selektoren: A.dst = B.local
    a_fw = plan.firewalls[0]
    assert _phase1(a_fw).body["remote-gw"] == "203.0.113.2"
    p2 = next(o for o in a_fw.operations if o.path.endswith("phase2-interface"))
    assert p2.body["src-subnet"] == "10.121.0.0/16"
    assert p2.body["dst-subnet"] == "10.123.0.0/16"


def test_routes_and_policies_present() -> None:
    plan = plan_site_to_site(_spec())
    a_ops = plan.firewalls[0].operations
    assert any(
        o.path.endswith("router/static") and o.body["device"] == "GROSU-CUSANO" for o in a_ops
    )
    # Policy nur bei gesetztem lan_interface (hier gesetzt) → beide Richtungen
    policies = [o for o in a_ops if o.path.endswith("firewall/policy")]
    assert len(policies) == 2


def test_no_policy_without_lan_interface() -> None:
    spec = _spec()
    spec.end_a.lan_interface = None
    plan = plan_site_to_site(spec)
    a_ops = plan.firewalls[0].operations
    assert not any(o.path.endswith("firewall/policy") for o in a_ops)


def test_phase1_has_rollback_path() -> None:
    plan = plan_site_to_site(_spec())
    p1 = _phase1(plan.firewalls[0])
    assert p1.rollback_path == "/api/v2/cmdb/vpn.ipsec/phase1-interface/GROSU-CUSANO"
