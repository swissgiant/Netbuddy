"""VLAN-Survey: welche VLANs existieren wo, wie geroutet, DHCP-Server/-Helper (Feature S63).

Sammelt read-only pro Gerät die VLAN-Realität ein — als Fundament, um VLANs zu konsolidieren:

- **CLI-Switches** (dell_os6/os10, fs_centec/ruijie, tplink): live ``show running-config``
  (mit enable/Pager je Vendor), geparst: VLAN-Definitionen + Namen, SVIs (``interface vlan X``
  + ``ip address``), ``ip helper-address`` (DHCP-Relay), Access-/Trunk-Zuordnung.
- **FortiGate** (REST): VLAN-Subinterfaces (vlanid, ip, dhcp-relay) + DHCP-Server je Interface.
- **UniFi** (lokaler Controller): ``networkconf`` (vlan, name, purpose, dhcpd_enabled, subnet).

Ergebnis: pro Standort eine VLAN-Liste mit Namen, Routing-Punkten (Gateways/SVIs), DHCP-Art
(Server / Relay mit Helper-IPs / keins) und Träger-Geräten. Read-only; ein Lauf wird als
JSON-Blob persistiert (``VlanSurveyRun``).
"""

import re
from typing import TYPE_CHECKING, Any

import asyncssh
import httpx
from pydantic import BaseModel, Field

from netbuddy.adapters.connection import params_from_credential
from netbuddy.db.models import Credential, Device

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------- CLI-Config-Parsing


class SviInfo(BaseModel):
    vlan_id: int
    ip: str | None = None
    helpers: list[str] = Field(default_factory=list)  # ip helper-address (DHCP-Relay)


class DeviceVlanInfo(BaseModel):
    """VLAN-Sicht eines einzelnen Geräts (aus Config oder API)."""

    hostname: str
    site: str | None = None
    kind: str  # switch | firewall | unifi
    vlans: dict[int, str | None] = Field(default_factory=dict)  # id -> Name (falls konfiguriert)
    svis: list[SviInfo] = Field(default_factory=list)
    access_ports: dict[int, int] = Field(default_factory=dict)  # vlan -> Anzahl Access-Ports
    trunk_vlans: list[int] = Field(default_factory=list)  # über Trunks getragen
    dhcp_server_vlans: list[int] = Field(default_factory=list)  # Gerät selbst ist DHCP-Server
    error: str | None = None


def _expand_vlan_list(spec: str) -> list[int]:
    """ "90,101-116,120" → [90, 101, …, 116, 120]. Ignoriert Nicht-Zahlen ("add", "all")."""
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi - lo <= 4094:
                out.extend(range(lo, hi + 1))
        elif part.isdigit():
            out.append(int(part))
    return [v for v in out if 1 <= v <= 4094]


def parse_cli_config(hostname: str, text: str) -> DeviceVlanInfo:
    """Vendor-tolerantes Parsing einer Switch-Running-Config (os6/os10/fs/tplink).

    Regex-basiert über Zeilen + Interface-Kontext; kennt die Syntax-Varianten der Fleet-Vendor.
    """
    info = DeviceVlanInfo(hostname=hostname, kind="switch")
    ctx: str | None = None  # aktueller interface-Kontext
    svi: SviInfo | None = None
    pending_vlan_ids: list[int] = []  # zuletzt definierte VLANs (für folgendes `name`)

    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()

        m = re.match(r"(?i)^interface\s+vlan\s*(\d+)$", s)
        if m:
            if svi is not None:
                info.svis.append(svi)
            ctx = f"vlan{m.group(1)}"
            svi = SviInfo(vlan_id=int(m.group(1)))
            continue
        if re.match(r"(?i)^interface\s+\S", s):
            if svi is not None:
                info.svis.append(svi)
                svi = None
            ctx = s.split(None, 1)[1]
            continue
        if s in ("!", "exit", "end") or re.match(r"(?i)^config\b", s):
            # Kontext endet; SVI abschließen
            if svi is not None and (s in ("!", "exit", "end")):
                info.svis.append(svi)
                svi = None
                ctx = None
            continue

        # VLAN-Definitionen (global oder `vlan database`): `vlan 90,101-116` / `vlan range 120`
        m = re.match(r"(?i)^vlan\s+(?:range\s+)?([\d,\- ]+)$", s)
        if m and ctx is None:
            ids = _expand_vlan_list(m.group(1))
            for v in ids:
                info.vlans.setdefault(v, None)
            pending_vlan_ids = ids
            continue
        # Name direkt nach vlan-Definition (os6/fs: `name "MGMT"`)
        m = re.match(r"(?i)^name\s+\"?([^\"]+)\"?$", s)
        if m and pending_vlan_ids:
            if len(pending_vlan_ids) == 1:
                info.vlans[pending_vlan_ids[0]] = m.group(1).strip()
            continue

        if svi is not None:
            m = re.match(r"(?i)^ip address\s+(\d+\.\d+\.\d+\.\d+)", s)
            if m:
                svi.ip = m.group(1)
                info.vlans.setdefault(svi.vlan_id, None)
                continue
            m = re.match(r"(?i)^ip helper-address\s+(\d+\.\d+\.\d+\.\d+)", s)
            if m:
                svi.helpers.append(m.group(1))
                continue

        if ctx is not None and not ctx.startswith("vlan"):
            m = re.match(r"(?i)^switchport access vlan\s+(\d+)$", s)
            if m:
                v = int(m.group(1))
                info.access_ports[v] = info.access_ports.get(v, 0) + 1
                info.vlans.setdefault(v, None)
                continue
            m = re.match(
                r"(?i)^switchport (?:trunk|general) allowed vlan\s+(?:add\s+)?([\d,\- ]+)", s
            )
            if m:
                for v in _expand_vlan_list(m.group(1)):
                    if v not in info.trunk_vlans:
                        info.trunk_vlans.append(v)
                    info.vlans.setdefault(v, None)
                continue

    if svi is not None:
        info.svis.append(svi)
    return info


# ---------------------------------------------------------------- Live-Collector

_PAGER = ("Press any key", "--More--")


async def _read_cli_config(device: Device, credential: Credential) -> str:
    """Running-Config live lesen — mit enable (os6/tplink) und Pager-Handling."""
    p = params_from_credential(device, credential)
    line_end = "\r\n" if device.adapter_id == "tplink_jetstream" else "\n"
    conn = await asyncssh.connect(
        str(device.mgmt_ip),
        username=p.username,
        password=p.password.get_secret_value() if p.password else "",
        known_hosts=None,
    )
    try:
        proc = await conn.create_process(term_type="vt100")

        async def drain(idle: float = 3.0, presses: int = 40) -> str:
            import asyncio

            buf = ""
            used = 0
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(8192), timeout=idle)
                except TimeoutError:
                    return buf
                buf += chunk
                if any(k in chunk for k in _PAGER):
                    proc.stdin.write(" " if used < presses else "q")
                    used += 1

        await drain(2)
        if device.adapter_id in ("dell_os6", "tplink_jetstream"):
            proc.stdin.write("enable" + line_end)
            await drain(1.5)
        proc.stdin.write("terminal length 0" + line_end)
        await drain(1.5)
        proc.stdin.write("show running-config" + line_end)
        return await drain(6)
    finally:
        conn.close()


async def _fortigate_info(device: Device, credential: Credential) -> DeviceVlanInfo:
    """FortiGate via REST: VLAN-Subinterfaces (+dhcp-relay) und DHCP-Server je Interface."""
    info = DeviceVlanInfo(hostname=device.hostname, kind="firewall")
    headers = {"Authorization": f"Bearer {credential.api_token}"}
    async with httpx.AsyncClient(
        base_url=credential.base_url or "", headers=headers, verify=False, timeout=25
    ) as cl:
        r = await cl.get("/api/v2/cmdb/system/interface?vdom=root")
        r.raise_for_status()
        iface_vlan: dict[str, int] = {}
        for it in r.json().get("results", []):
            vid = it.get("vlanid")
            if not vid:
                continue
            iface_vlan[str(it.get("name"))] = int(vid)
            info.vlans[int(vid)] = str(it.get("name"))
            ip = str(it.get("ip") or "").split(" ")[0]
            svi = SviInfo(vlan_id=int(vid), ip=ip if ip and ip != "0.0.0.0" else None)
            if str(it.get("dhcp-relay-service")) == "enable":
                relay = it.get("dhcp-relay-ip") or ""
                svi.helpers = [x.strip().strip('"') for x in str(relay).split() if x.strip()]
            info.svis.append(svi)
        r = await cl.get("/api/v2/cmdb/system.dhcp/server?vdom=root")
        if r.status_code == 200:
            for srv in r.json().get("results", []):
                vid = iface_vlan.get(str(srv.get("interface")))
                if vid is not None:
                    info.dhcp_server_vlans.append(vid)
    return info


async def _unifi_info(site: str, credential: Credential) -> DeviceVlanInfo:
    """UniFi-Controller einer Site: networkconf → VLANs + Controller-DHCP."""
    from netbuddy.services.unifi_local import _PORT, CONSOLES, UnifiConsole

    info = DeviceVlanInfo(hostname=f"UniFi-Controller {site}", site=site, kind="unifi")
    ip = CONSOLES.get(site)
    if ip is None:
        info.error = f"keine UniFi-Konsole für {site!r}"
        return info
    async with UnifiConsole(
        f"https://{ip}:{_PORT}", credential.username or "", credential.password or ""
    ) as con:
        raw = await con._get("/proxy/network/api/s/default/rest/networkconf")
    for n in raw:
        vid = n.get("vlan")
        if n.get("vlan_enabled") and vid:
            info.vlans[int(vid)] = str(n.get("name") or "")
            if n.get("dhcpd_enabled"):
                info.dhcp_server_vlans.append(int(vid))
        elif not n.get("vlan_enabled"):
            # untagged Default-Netz: als VLAN 1 führen
            info.vlans.setdefault(1, str(n.get("name") or ""))
            subnet = str(n.get("ip_subnet") or "").split("/")[0]
            if subnet:
                info.svis.append(SviInfo(vlan_id=1, ip=subnet))
            if n.get("dhcpd_enabled"):
                info.dhcp_server_vlans.append(1)
    return info


# ---------------------------------------------------------------- Aggregation

CLI_ADAPTERS = ("dell_os6", "dell_os10", "fs_centec", "fs_ruijie", "tplink_jetstream")


def aggregate_survey(
    per_device: list[DeviceVlanInfo], site_names: dict[str, str]
) -> dict[str, Any]:
    """Geräte-Infos → pro Site eine VLAN-Übersicht (Namen, Gateways, DHCP, Träger)."""
    sites: dict[str, dict[int, dict[str, Any]]] = {}
    for dev in per_device:
        site = dev.site or "—"
        vlans = sites.setdefault(site, {})
        for vid, name in dev.vlans.items():
            entry = vlans.setdefault(
                vid,
                {
                    "vlan_id": vid,
                    "names": [],
                    "gateways": [],  # {device, ip}
                    "dhcp_servers": [],  # Gerätenamen
                    "dhcp_helpers": [],  # {device, vlan-svi, helpers[]}
                    "carriers": [],  # Geräte, die das VLAN tragen
                    "access_ports": 0,
                },
            )
            if name and name not in entry["names"]:
                entry["names"].append(name)
            if dev.hostname not in entry["carriers"]:
                entry["carriers"].append(dev.hostname)
            entry["access_ports"] += dev.access_ports.get(vid, 0)
        for svi in dev.svis:
            hit = vlans.get(svi.vlan_id)
            if hit is None:
                continue
            if svi.ip:
                hit["gateways"].append({"device": dev.hostname, "ip": svi.ip})
            if svi.helpers:
                hit["dhcp_helpers"].append({"device": dev.hostname, "helpers": svi.helpers})
        for vid in dev.dhcp_server_vlans:
            hit = vlans.get(vid)
            if hit is not None and dev.hostname not in hit["dhcp_servers"]:
                hit["dhcp_servers"].append(dev.hostname)
    return {
        "sites": {
            site: sorted(vlans.values(), key=lambda e: e["vlan_id"])
            for site, vlans in sorted(sites.items())
        },
        "device_errors": [{"device": d.hostname, "error": d.error} for d in per_device if d.error],
    }


async def run_vlan_survey(session: "AsyncSession") -> dict[str, Any]:
    """Kompletter Survey-Lauf über die Fleet (read-only, dauert einige Minuten).

    CLI-Switches parallel (begrenzt), FortiGates via REST, UniFi pro Standort-Konsole.
    """
    import asyncio

    from sqlalchemy import select

    from netbuddy.db.models import DeviceCredential, Site

    sites = {s.id: s.name for s in (await session.execute(select(Site))).scalars()}
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )

    async def cred_for(dev: Device, wants_api: bool) -> Credential | None:
        rows = (
            (
                await session.execute(
                    select(Credential)
                    .join(DeviceCredential, DeviceCredential.credential_id == Credential.id)
                    .where(
                        DeviceCredential.device_id == dev.id,
                        DeviceCredential.deleted_at.is_(None),
                        Credential.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for c in rows:
            if bool(c.base_url) == wants_api:
                return c
        return rows[0] if rows else None

    per_device: list[DeviceVlanInfo] = []
    sem = asyncio.Semaphore(6)

    async def do_cli(dev: Device, cred: Credential) -> DeviceVlanInfo:
        async with sem:
            try:
                cfg = await asyncio.wait_for(_read_cli_config(dev, cred), timeout=60)
                info = parse_cli_config(dev.hostname, cfg)
            except Exception as exc:
                info = DeviceVlanInfo(
                    hostname=dev.hostname, kind="switch", error=f"{type(exc).__name__}: {exc}"
                )
            info.site = sites.get(dev.site_id) if dev.site_id else None
            return info

    async def do_fw(dev: Device, cred: Credential) -> DeviceVlanInfo:
        async with sem:
            try:
                info = await asyncio.wait_for(_fortigate_info(dev, cred), timeout=45)
            except Exception as exc:
                info = DeviceVlanInfo(
                    hostname=dev.hostname, kind="firewall", error=f"{type(exc).__name__}: {exc}"
                )
            info.site = sites.get(dev.site_id) if dev.site_id else None
            return info

    tasks = []
    for dev in devices:
        if dev.adapter_id in CLI_ADAPTERS:
            cred = await cred_for(dev, wants_api=False)
            if cred:
                tasks.append(do_cli(dev, cred))
        elif dev.adapter_id == "fortigate":
            cred = await cred_for(dev, wants_api=True)
            if cred and cred.api_token:
                tasks.append(do_fw(dev, cred))
    per_device.extend(await asyncio.gather(*tasks))

    # UniFi: eine Abfrage pro Standort-Konsole (nicht pro Gerät).
    local = (
        (
            await session.execute(
                select(Credential).where(
                    Credential.name == "UnifiLocal", Credential.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .first()
    )
    if local is not None:
        from netbuddy.services.unifi_local import CONSOLES

        for site_name in CONSOLES:
            try:
                info = await asyncio.wait_for(_unifi_info(site_name, local), timeout=30)
            except Exception as exc:
                info = DeviceVlanInfo(
                    hostname=f"UniFi-Controller {site_name}",
                    site=site_name,
                    kind="unifi",
                    error=f"{type(exc).__name__}: {exc}",
                )
            per_device.append(info)

    return aggregate_survey(per_device, {str(k): v for k, v in sites.items()})
