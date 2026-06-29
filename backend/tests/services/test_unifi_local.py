import json

import httpx

from netbuddy.db.models import Credential
from netbuddy.services import unifi_local

_DEVICES = [
    {
        "type": "usw",
        "mac": "aa:bb:cc:00:00:01",
        "name": "BLS-SW-CU-01",
        "model": "USWF069",
        "ip": "10.123.10.11",
        "uplink": {"type": "wire", "uplink_mac": "aa:bb:cc:00:00:09"},
        "port_table": [
            {
                "port_idx": 1,
                "name": "Port 1",
                "port_poe": True,
                "poe_enable": True,
                "poe_good": True,
                "poe_power": "8.35",
                "up": True,
            },
            {
                "port_idx": 2,
                "name": "Port 2",
                "port_poe": True,
                "poe_enable": True,
                "poe_good": False,
                "poe_power": "0.00",
                "up": False,
            },
            {"port_idx": 49, "name": "SFP", "port_poe": False, "up": True},
        ],
    },
    {
        "type": "uap",
        "mac": "d0:21:f9:00:00:01",
        "name": "BLS-AP-CU-01",
        "model": "U7 Pro",
        "ip": "10.123.12.5",
        "uplink": {"type": "wire", "uplink_mac": "aa:bb:cc:00:00:01"},
    },
    {"type": "ugw", "mac": "ff:ff:ff:ff:ff:ff", "name": "GW"},  # wird ignoriert
]
_CLIENTS = [
    {
        "mac": "50:28:4a:00:00:01",
        "hostname": "PC1",
        "ip": "10.123.41.5",
        "is_wired": True,
        "sw_mac": "aa:bb:cc:00:00:01",
        "sw_port": 5,
        "oui": "Intel",
    },
    {
        "mac": "50:28:4a:00:00:02",
        "hostname": "Phone",
        "ip": "10.123.41.6",
        "is_wired": False,
        "ap_mac": "d0:21:f9:00:00:01",
        "oui": "Apple",
    },
]


def _serve(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/api/auth/login":
        return httpx.Response(200, headers={"X-CSRF-Token": "csrf123"}, json={"meta": {}})
    if p.endswith("/self/sites"):
        return httpx.Response(200, json={"data": [{"name": "default"}]})
    if p.endswith("/stat/device"):
        return httpx.Response(200, json={"data": _DEVICES})
    if p.endswith("/stat/sta"):
        return httpx.Response(200, json={"data": _CLIENTS})
    if p.endswith("/cmd/devmgr"):
        return httpx.Response(200, json={"data": [], "meta": {"rc": "ok"}})
    return httpx.Response(404)


def _factory(recorder: list[httpx.Request] | None = None) -> unifi_local.ClientFactory:
    def handler(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.append(request)
        return _serve(request)

    def make(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))

    return make


async def test_fetch_console_parses_devices_and_clients() -> None:
    devices, clients = await unifi_local.fetch_console(
        "Cusano", "https://10.123.12.253:11443", "netbuddy", "pw", client_factory=_factory()
    )
    # ugw rausgefiltert → 1 switch + 1 ap
    sw = next(d for d in devices if d.type == "usw")
    ap = next(d for d in devices if d.type == "uap")
    assert sw.name == "BLS-SW-CU-01" and sw.site == "Cusano"
    # nur PoE-Ports (SFP raus); Power korrekt geparst
    assert len(sw.poe_ports) == 2
    p1 = next(p for p in sw.poe_ports if p.port_idx == 1)
    assert p1.poe_good and p1.poe_power == 8.35 and p1.up
    p2 = next(p for p in sw.poe_ports if p.port_idx == 2)
    assert not p2.poe_good and not p2.up
    assert ap.uplink_type == "wire" and ap.uplink_mac == "aa:bb:cc:00:00:01"

    wired = next(c for c in clients if c.is_wired)
    wireless = next(c for c in clients if not c.is_wired)
    assert wired.sw_mac == "aa:bb:cc:00:00:01" and wired.sw_port == 5
    assert wireless.ap_mac == "d0:21:f9:00:00:01"


async def test_power_cycle_sends_csrf_and_payload() -> None:
    rec: list[httpx.Request] = []
    async with unifi_local.UnifiConsole(
        "https://x:11443", "netbuddy", "pw", client_factory=_factory(rec)
    ) as con:
        await con.power_cycle("aa:bb:cc:00:00:01", 2)
    devmgr = next(r for r in rec if r.url.path.endswith("/cmd/devmgr"))
    assert devmgr.headers.get("X-CSRF-Token") == "csrf123"
    body = json.loads(devmgr.content)
    assert body == {"cmd": "power-cycle", "mac": "aa:bb:cc:00:00:01", "port_idx": 2}


def test_find_poe_faults_and_locate_clients() -> None:
    sw = unifi_local.UnifiDevice(
        site="Cusano",
        mac="aa",
        type="usw",
        name="SW1",
        poe_ports=[
            unifi_local.UnifiSwitchPort(port_idx=1, poe_enable=True, poe_good=True, up=True),
            unifi_local.UnifiSwitchPort(port_idx=2, poe_enable=True, poe_good=False, up=False),
            unifi_local.UnifiSwitchPort(port_idx=3, poe_enable=False, poe_good=False),
        ],
    )
    ap = unifi_local.UnifiDevice(site="Cusano", mac="dd", type="uap", name="AP1")

    faults = unifi_local.find_poe_faults([sw, ap])
    assert len(faults) == 1 and faults[0].port_idx == 2 and faults[0].switch_mac == "aa"

    clients = [
        unifi_local.UnifiClient(site="Cusano", mac="c1", is_wired=True, sw_mac="aa", sw_port=5),
        unifi_local.UnifiClient(site="Cusano", mac="c2", is_wired=False, ap_mac="dd"),
    ]
    locs = unifi_local.locate_clients([sw, ap], clients)
    wired = next(loc for loc in locs if loc.kind == "wired")
    wireless = next(loc for loc in locs if loc.kind == "wireless")
    assert wired.via_device == "SW1" and wired.port == 5
    assert wireless.via_device == "AP1"


def _network_factory(
    store: list[dict[str, object]], recorder: list[httpx.Request]
) -> unifi_local.ClientFactory:
    """Fake-Controller mit zustandsbehafteter ``rest/networkconf`` (GET/POST/DELETE)."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        p = request.url.path
        if p == "/api/auth/login":
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf123"}, json={"meta": {}})
        if p.endswith("/rest/networkconf"):
            if request.method == "GET":
                return httpx.Response(200, json={"data": store})
            body = json.loads(request.content)
            created = {**body, "_id": f"id{len(store)}"}
            store.append(created)
            return httpx.Response(200, json={"data": [created]})
        return httpx.Response(404)

    def make(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))

    return make


async def test_create_vlan_only_network_payload_and_csrf() -> None:
    store: list[dict[str, object]] = []
    rec: list[httpx.Request] = []
    async with unifi_local.UnifiConsole(
        "https://x:11443", "netbuddy", "pw", client_factory=_network_factory(store, rec)
    ) as con:
        net = await con.create_vlan_only_network("Testnetz01", 101)
    # Login ist auch ein POST → auf den networkconf-Call filtern.
    post = next(r for r in rec if r.method == "POST" and r.url.path.endswith("/rest/networkconf"))
    assert post.headers.get("X-CSRF-Token") == "csrf123"
    body = json.loads(post.content)
    assert body["purpose"] == "vlan-only" and body["vlan"] == 101 and body["vlan_enabled"] is True
    assert net.vlan == 101 and net.name == "Testnetz01" and net.id == "id0"


async def test_provision_vlan_only_networks_is_idempotent() -> None:
    # VLAN 101 existiert schon, 102 fehlt → nur 102 wird angelegt.
    store: list[dict[str, object]] = [
        {
            "_id": "x",
            "name": "Testnetz01",
            "purpose": "vlan-only",
            "vlan_enabled": True,
            "vlan": 101,
        }
    ]
    rec: list[httpx.Request] = []
    cred = Credential(name="UnifiLocal", username="netbuddy", password="pw")
    report = await unifi_local.provision_vlan_only_networks(
        cred,
        "Cusano",
        [(101, "Testnetz01"), (102, "Testnetz02")],
        consoles={"Cusano": "10.123.12.253"},
        client_factory=_network_factory(store, rec),
    )
    assert report.created == [102] and report.existing == [101]
    assert {n.vlan for n in report.networks} == {101, 102}
    posts = [r for r in rec if r.method == "POST" and r.url.path.endswith("/rest/networkconf")]
    assert len(posts) == 1


async def test_provision_dry_run_writes_nothing() -> None:
    store: list[dict[str, object]] = []
    rec: list[httpx.Request] = []
    cred = Credential(name="UnifiLocal", username="netbuddy", password="pw")
    report = await unifi_local.provision_vlan_only_networks(
        cred,
        "Cusano",
        [(101, "Testnetz01"), (102, "Testnetz02")],
        dry_run=True,
        consoles={"Cusano": "10.123.12.253"},
        client_factory=_network_factory(store, rec),
    )
    assert report.created == [101, 102] and report.dry_run is True
    assert not any(r.url.path.endswith("/rest/networkconf") and r.method == "POST" for r in rec)
    assert store == []


def _port_factory(rec: list[httpx.Request]) -> unifi_local.ClientFactory:
    """Fake-Controller: networkconf (VLAN 101) + ein Switch mit bestehendem Port-Override."""

    def handler(request: httpx.Request) -> httpx.Response:
        rec.append(request)
        p = request.url.path
        if p == "/api/auth/login":
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf123"}, json={})
        if p.endswith("/rest/networkconf"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"_id": "net101", "name": "Testnetz01", "vlan_enabled": True, "vlan": 101}
                    ]
                },
            )
        if p.endswith("/stat/device"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "_id": "sw1",
                            "mac": "aa:bb:cc:00:00:01",
                            "ip": "10.123.40.3",
                            "port_overrides": [{"port_idx": 1, "poe_mode": "auto"}],
                        }
                    ]
                },
            )
        if "/rest/device/" in p and request.method == "PUT":
            return httpx.Response(200, json={"data": [{}]})
        return httpx.Response(404)

    def make(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))

    return make


async def test_assign_unifi_port_vlan_sets_native_override() -> None:
    rec: list[httpx.Request] = []
    cred = Credential(name="UnifiLocal", username="netbuddy", password="pw")
    res = await unifi_local.assign_unifi_port_vlan(
        cred,
        "Cusano",
        "10.123.40.3",
        5,
        101,
        consoles={"Cusano": "10.123.12.253"},
        client_factory=_port_factory(rec),
    )
    assert res.networkconf_id == "net101" and res.port_idx == 5
    put = next(r for r in rec if r.method == "PUT" and "/rest/device/sw1" in r.url.path)
    overrides = json.loads(put.content)["port_overrides"]
    target = next(o for o in overrides if o["port_idx"] == 5)
    assert target["native_networkconf_id"] == "net101" and target["forward"] == "native"
    # bestehender Override (Port 1, PoE) bleibt erhalten
    assert any(o["port_idx"] == 1 and o.get("poe_mode") == "auto" for o in overrides)


async def test_reset_unifi_port_vlan_clears_override() -> None:
    rec: list[httpx.Request] = []
    cred = Credential(name="UnifiLocal", username="netbuddy", password="pw")
    await unifi_local.reset_unifi_port_vlan(
        cred,
        "Cusano",
        "10.123.40.3",
        1,
        consoles={"Cusano": "10.123.12.253"},
        client_factory=_port_factory(rec),
    )
    put = next(r for r in rec if r.method == "PUT" and "/rest/device/sw1" in r.url.path)
    overrides = json.loads(put.content)["port_overrides"]
    assert all(o["port_idx"] != 1 for o in overrides)  # Override für Port 1 entfernt


async def test_fetch_all_skips_unreachable() -> None:
    def make(base_url: str) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            if "10.120.12.253" in base_url:
                raise httpx.ConnectError("down")
            return _serve(request)

        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))

    cred = Credential(name="UnifiLocal", username="netbuddy", password="pw")
    consoles = {"Sulgen": "10.120.12.253", "Cusano": "10.123.12.253"}
    devices, clients = await unifi_local.fetch_all(cred, consoles, client_factory=make)
    # Sulgen down → nur Cusano-Daten
    assert all(d.site == "Cusano" for d in devices)
    assert len(devices) == 2 and len(clients) == 2
