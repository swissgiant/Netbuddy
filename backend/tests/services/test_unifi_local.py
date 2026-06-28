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
