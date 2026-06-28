"""Lokaler UniFi-Network-Controller (UniFi OS Server) — read + PoE-Recovery über die lokale API.

Pro Standort eine Konsole auf **Port 11443**. Login per lokalem Konto (Credential ``UnifiLocal``),
Session-Cookie wird über den ``httpx``-Client gehalten. Liefert Geräte (Switches/APs inkl.
Uplink-Typ wired/wireless = Mesh + PoE-Portstatus) und Clients (welcher Client an welchem AP bzw.
Switch-Port). Port-Bounce per ``cmd/devmgr`` ``power-cycle``.

Read-only-Calls verändern nichts; ``power_cycle`` ist der einzige Schreibpfad und nur über die
autorisierte PoE-Recovery aufgerufen.
"""

from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx
from pydantic import BaseModel

from netbuddy.db.models import Credential

# NetBuddy-Site-Name -> lokale Controller-IP (UniFi OS Server). BLS-UniFi-Slowenia = Site Grosuplje.
CONSOLES: dict[str, str] = {
    "Sulgen": "10.120.12.253",
    "Grosuplje": "10.121.12.253",
    "USA": "10.120.12.250",
    "Cusano": "10.123.12.253",
}
_PORT = 11443

ClientFactory = Callable[[str], httpx.AsyncClient]


def _default_client(base_url: str) -> httpx.AsyncClient:
    # Interne Controller mit selbstsigniertem Cert → keine TLS-Verifikation.
    return httpx.AsyncClient(base_url=base_url, verify=False, timeout=25)


class UnifiSwitchPort(BaseModel):
    """Ein PoE-fähiger Switch-Port aus dem ``port_table`` eines UniFi-Switches."""

    port_idx: int
    name: str | None = None
    poe_enable: bool = False
    poe_good: bool = False  # Controller-Sicht: Port liefert sauber Strom
    poe_power: float | None = None
    up: bool = False


class UnifiDevice(BaseModel):
    """Ein UniFi-Switch (``usw``) oder AP (``uap``) aus ``stat/device``."""

    site: str
    mac: str
    name: str | None = None
    model: str | None = None
    ip: str | None = None
    type: str  # usw | uap
    uplink_type: str | None = None  # wire | wireless (= Mesh)
    uplink_mac: str | None = None  # Upstream-Gerät (Switch), sofern UniFi-verwaltet
    poe_ports: list[UnifiSwitchPort] = []


class UnifiClient(BaseModel):
    """Ein aktiver Client aus ``stat/sta`` — wired (Switch+Port) oder wireless (AP)."""

    site: str
    mac: str
    hostname: str | None = None
    ip: str | None = None
    is_wired: bool = False
    ap_mac: str | None = None  # bei wireless: AP, an dem der Client hängt
    sw_mac: str | None = None  # bei wired: Switch
    sw_port: int | None = None  # bei wired: Switch-Port
    oui: str | None = None


def parse_device(raw: dict[str, Any], site: str) -> UnifiDevice:
    up = raw.get("uplink") or {}
    ports: list[UnifiSwitchPort] = []
    for p in raw.get("port_table", []) or []:
        if not p.get("port_poe") or p.get("port_idx") is None:
            continue
        power = p.get("poe_power")
        ports.append(
            UnifiSwitchPort(
                port_idx=int(p["port_idx"]),
                name=p.get("name"),
                poe_enable=bool(p.get("poe_enable")),
                poe_good=bool(p.get("poe_good")),
                poe_power=float(power) if power not in (None, "") else None,
                up=bool(p.get("up")),
            )
        )
    return UnifiDevice(
        site=site,
        mac=str(raw.get("mac") or ""),
        name=raw.get("name"),
        model=raw.get("model"),
        ip=raw.get("ip"),
        type=str(raw.get("type")),
        uplink_type=up.get("type"),
        uplink_mac=up.get("uplink_mac"),
        poe_ports=ports,
    )


def parse_client(raw: dict[str, Any], site: str) -> UnifiClient:
    return UnifiClient(
        site=site,
        mac=str(raw.get("mac") or ""),
        hostname=raw.get("hostname") or raw.get("name"),
        ip=raw.get("ip"),
        is_wired=bool(raw.get("is_wired")),
        ap_mac=raw.get("ap_mac"),
        sw_mac=raw.get("sw_mac"),
        sw_port=raw.get("sw_port"),
        oui=raw.get("oui"),
    )


class UnifiConsole:
    """Eine UniFi-OS-Konsole: Login + read + ``power-cycle`` (async Context-Manager).

    Der ``client_factory`` ist injizierbar, damit Tests ohne echten Controller laufen.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        client_factory: ClientFactory = _default_client,
    ) -> None:
        self._base = base_url
        self._user = username
        self._pw = password
        self._cf = client_factory
        self._client: httpx.AsyncClient | None = None
        self._csrf: str | None = None

    async def __aenter__(self) -> "UnifiConsole":
        self._client = self._cf(self._base)
        resp = await self._client.post(
            "/api/auth/login",
            json={"username": self._user, "password": self._pw, "rememberMe": False},
        )
        resp.raise_for_status()
        # UniFi OS verlangt für Mutationen den CSRF-Token aus der Login-Antwort.
        self._csrf = resp.headers.get("X-CSRF-Token") or resp.headers.get("X-Updated-CSRF-Token")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _get(self, path: str) -> list[dict[str, Any]]:
        assert self._client is not None
        resp = await self._client.get(path)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else payload
        return [d for d in data if isinstance(d, dict)]

    async def sites(self) -> list[str]:
        return [str(s.get("name")) for s in await self._get("/proxy/network/api/self/sites")]

    async def devices(self, site: str = "default") -> list[dict[str, Any]]:
        return await self._get(f"/proxy/network/api/s/{site}/stat/device")

    async def clients(self, site: str = "default") -> list[dict[str, Any]]:
        return await self._get(f"/proxy/network/api/s/{site}/stat/sta")

    async def power_cycle(
        self, switch_mac: str, port_idx: int, site: str = "default"
    ) -> dict[str, Any]:
        """⚠️ Schreibpfad: PoE-Port am UniFi-Switch aus- und wieder einschalten."""
        assert self._client is not None
        headers = {"X-CSRF-Token": self._csrf} if self._csrf else {}
        resp = await self._client.post(
            f"/proxy/network/api/s/{site}/cmd/devmgr",
            json={"cmd": "power-cycle", "mac": switch_mac, "port_idx": port_idx},
            headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()
        return result if isinstance(result, dict) else {"data": result}


async def fetch_console(
    site: str,
    base_url: str,
    username: str,
    password: str,
    *,
    client_factory: ClientFactory = _default_client,
) -> tuple[list[UnifiDevice], list[UnifiClient]]:
    """Geräte (Switches/APs) + Clients einer Konsole über alle ihre Sites."""
    devices: list[UnifiDevice] = []
    clients: list[UnifiClient] = []
    async with UnifiConsole(base_url, username, password, client_factory=client_factory) as con:
        for sn in (await con.sites()) or ["default"]:
            for raw in await con.devices(sn):
                if str(raw.get("type")) in ("usw", "uap"):
                    devices.append(parse_device(raw, site))
            for raw in await con.clients(sn):
                clients.append(parse_client(raw, site))
    return devices, clients


class ClientLocation(BaseModel):
    """Ein Endgerät mit Aufenthaltsort: wired (Switch+Port) oder wireless (AP)."""

    mac: str
    hostname: str | None = None
    ip: str | None = None
    kind: str  # wired | wireless
    via_device: str | None = None  # Switch- bzw. AP-Name (oder MAC, falls unbekannt)
    port: int | None = None  # Switch-Port (nur wired)
    site: str
    oui: str | None = None


def locate_clients(devices: list[UnifiDevice], clients: list[UnifiClient]) -> list[ClientLocation]:
    """Clients → wo sie hängen: wired auf Switch+Port, wireless am AP (Namen aufgelöst)."""
    sw = {d.mac: d for d in devices if d.type == "usw"}
    ap = {d.mac: d for d in devices if d.type == "uap"}
    out: list[ClientLocation] = []
    for c in clients:
        if c.is_wired:
            d = sw.get(c.sw_mac or "")
            out.append(
                ClientLocation(
                    mac=c.mac,
                    hostname=c.hostname,
                    ip=c.ip,
                    kind="wired",
                    via_device=d.name if d else c.sw_mac,
                    port=c.sw_port,
                    site=c.site,
                    oui=c.oui,
                )
            )
        else:
            d = ap.get(c.ap_mac or "")
            out.append(
                ClientLocation(
                    mac=c.mac,
                    hostname=c.hostname,
                    ip=c.ip,
                    kind="wireless",
                    via_device=d.name if d else c.ap_mac,
                    site=c.site,
                    oui=c.oui,
                )
            )
    return out


class PoeFault(BaseModel):
    """Ein UniFi-Switch-Port, der Strom freigegeben hat, aber nicht sauber liefert (= stuck)."""

    site: str
    switch_mac: str
    switch_name: str | None = None
    switch_ip: str | None = None
    port_idx: int
    port_name: str | None = None


def find_poe_faults(devices: list[UnifiDevice]) -> list[PoeFault]:
    """Stuck-UniFi-Ports: ``poe_enable`` (PD erkannt/freigegeben) aber ``poe_good`` False."""
    faults: list[PoeFault] = []
    for d in devices:
        if d.type != "usw":
            continue
        for p in d.poe_ports:
            if p.poe_enable and not p.poe_good:
                faults.append(
                    PoeFault(
                        site=d.site,
                        switch_mac=d.mac,
                        switch_name=d.name,
                        switch_ip=d.ip,
                        port_idx=p.port_idx,
                        port_name=p.name,
                    )
                )
    return faults


async def power_cycle_port(
    credential: Credential,
    site: str,
    switch_mac: str,
    port_idx: int,
    *,
    consoles: dict[str, str] = CONSOLES,
    client_factory: ClientFactory = _default_client,
) -> dict[str, Any]:
    """⚠️ Schreibpfad: PoE-Port eines UniFi-Switches power-cyclen (über die Site-Konsole)."""
    ip = consoles.get(site)
    if ip is None:
        raise ValueError(f"Keine UniFi-Konsole für Standort {site!r} bekannt")
    async with UnifiConsole(
        f"https://{ip}:{_PORT}",
        credential.username or "",
        credential.password or "",
        client_factory=client_factory,
    ) as con:
        return await con.power_cycle(switch_mac, port_idx)


async def fetch_all(
    credential: Credential,
    consoles: dict[str, str] = CONSOLES,
    *,
    client_factory: ClientFactory = _default_client,
) -> tuple[list[UnifiDevice], list[UnifiClient]]:
    """Über alle Konsolen: Geräte + Clients. Eine nicht erreichbare Konsole wird übersprungen."""
    username = credential.username or ""
    password = credential.password or ""
    all_devices: list[UnifiDevice] = []
    all_clients: list[UnifiClient] = []
    for site, ip in consoles.items():
        try:
            devices, clients = await fetch_console(
                site, f"https://{ip}:{_PORT}", username, password, client_factory=client_factory
            )
        except Exception:
            continue
        all_devices.extend(devices)
        all_clients.extend(clients)
    return all_devices, all_clients
