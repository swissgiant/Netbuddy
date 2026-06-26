from typing import Any

from netbuddy.services.vpn_provision import (
    FirewallPlan,
    FortiOp,
    VpnEnd,
    VpnTunnelSpec,
    plan_full_mesh,
    plan_site_to_site,
)


def _mesh_ends() -> list[VpnEnd]:
    sites = [
        ("Sulgen", "SUL", "10.120.0.0/16", "10.120.10.1"),
        ("Grosuplje", "GRO", "10.121.0.0/16", "10.121.10.1"),
        ("USA", "USA", "10.122.0.0/16", "10.122.10.1"),
        ("Cusano", "CUS", "10.123.0.0/16", "10.123.10.1"),
    ]
    return [
        VpnEnd(
            site=name,
            code=code,
            device_id=f"dev-{code}",
            wan_interface="wan1",
            public_ip=ip,  # eigene öffentliche IP (Platzhalter)
            local_subnets=[subnet],
        )
        for name, code, subnet, ip in sites
    ]


def test_full_mesh_pair_count_and_per_fw_tunnels() -> None:
    plan = plan_full_mesh(_mesh_ends())
    # 4 Standorte → 6 Tunnel
    assert len(plan.tunnels) == 6
    # jede FW hat 3 Tunnel (= 3 phase1-interfaces)
    for fw in plan.firewalls:
        p1 = [o for o in fw.operations if o.path.endswith("phase1-interface")]
        assert len(p1) == 3


def test_full_mesh_distinct_psk_per_pair() -> None:
    plan = plan_full_mesh(_mesh_ends())
    psks = {
        o.body["psksecret"]
        for fw in plan.firewalls
        for o in fw.operations
        if o.path.endswith("phase1-interface")
    }
    assert len(psks) == 6  # je Paar ein eigenes PSK


def test_full_mesh_needs_two_firewalls() -> None:
    import pytest

    with pytest.raises(ValueError):
        plan_full_mesh([_mesh_ends()[0]])


def _spec(**kw: Any) -> VpnTunnelSpec:
    return VpnTunnelSpec(
        name="GROSU-CUSANO",
        end_a=VpnEnd(
            site="Grosuplje",
            device_id="dev-a",
            wan_interface="wan1",
            public_ip="203.0.113.1",  # eigene öffentliche IP von A
            local_subnets=["10.121.0.0/16"],
            lan_interface="lan",
        ),
        end_b=VpnEnd(
            site="Cusano",
            device_id="dev-b",
            wan_interface="wan1",
            public_ip="203.0.113.2",  # eigene öffentliche IP von B
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
    assert p2.body["src-subnet"] == "10.121.0.0 255.255.0.0"  # FortiOS-Format
    assert p2.body["dst-subnet"] == "10.123.0.0 255.255.0.0"


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


class _MockWriteClient:
    """Fake-Write-Client: zeichnet POST/DELETE auf; kann beim n-ten POST gezielt scheitern."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.posts: list[str] = []
        self.deletes: list[str] = []
        self._fail_on = fail_on
        self._n = 0

    async def post_json(self, path: str, body: dict[str, Any]) -> Any:
        self._n += 1
        if self._fail_on is not None and self._n == self._fail_on:
            raise RuntimeError("simulierter FortiOS-Fehler")
        self.posts.append(path)
        return {"mkey": body.get("name") or "auto-id"}  # FortiOS liefert mkey zurück

    async def put_json(self, path: str, body: dict[str, Any]) -> Any:
        self.posts.append(path)
        return {}

    async def delete(self, path: str) -> Any:
        self.deletes.append(path)
        return {}


async def test_apply_success() -> None:
    from netbuddy.services.vpn_provision import apply_operations

    ops = plan_site_to_site(_spec()).firewalls[0].operations
    client = _MockWriteClient()
    outcome = await apply_operations(client, ops)
    assert outcome.success is True
    assert outcome.rolled_back == []
    assert len(client.posts) == len(ops)
    assert client.deletes == []


async def test_apply_failure_triggers_rollback() -> None:
    from netbuddy.services.vpn_provision import apply_operations

    ops = plan_site_to_site(_spec()).firewalls[0].operations
    client = _MockWriteClient(fail_on=3)  # 3. Operation scheitert
    outcome = await apply_operations(client, ops)
    assert outcome.success is False
    assert outcome.error is not None
    # die 2 zuvor angelegten Ops (mit rollback_path) werden zurückgenommen
    assert len(client.deletes) == 2
    assert len(outcome.rolled_back) == 2


async def test_apply_rollback_covers_route_and_policy_via_mkey() -> None:
    from netbuddy.services.vpn_provision import apply_operations

    ops = plan_site_to_site(_spec()).firewalls[0].operations  # inkl. Route + 2 Policies
    assert any(o.path.endswith("router/static") for o in ops)
    client = _MockWriteClient(fail_on=len(ops))  # letzte Operation scheitert
    outcome = await apply_operations(client, ops)
    assert outcome.success is False
    # alle zuvor angelegten Objekte zurückgenommen (auch Route/Policy ohne statischen rollback_path)
    assert len(client.deletes) == len(ops) - 1
    assert len(outcome.rolled_back) == len(ops) - 1


def test_detect_lan_interface() -> None:
    from netbuddy.services.vpn_provision import detect_lan_interface

    ifs = [
        {"name": "wan", "type": "physical", "ip": "212.103.139.234 255.255.255.248"},
        {"name": "internal", "type": "physical", "ip": "10.121.10.1 255.255.255.0"},
        {"name": "GRO-USA", "type": "tunnel", "ip": "10.121.10.1 255.255.255.255"},
    ]
    assert detect_lan_interface(ifs, "10.121.0.0/16") == "internal"
    assert detect_lan_interface(ifs, "10.199.0.0/16") is None
