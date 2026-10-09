"""Cato-Networks-Inventar über die GraphQL-API (read-only gegenüber Cato).

Quelle: Cato Management Application, Endpoint ``https://api.catonetworks.com/api/v1/graphql2``
mit Header ``x-api-key``. Credential „CatoCloud": ``base_url``, ``api_token`` und
``extra.account_id`` (Pflicht); optional ``extra.site_map`` =
``{"<Cato-Site>": "<NetBuddy-Site>"}``, wenn Cato-Site und NetBuddy-Standort anders heißen.

Drei Lesesichten, bewusst getrennt von der DB-Logik (ohne Netz testbar)::

    api = CatoApi(cred)
    sites = await fetch_sites(api)               # accountSnapshot + networkRangeList je Site
    devices = await fetch_devices(api)           # Cato-Geräte-Inventar (Assets: IP/MAC/Hersteller)
    report = await sync_sites(session, cred, sites, dry_run=True)
    candidates = await infra_candidates(session, devices)  # Switch/FW/AP-Verdacht

Der Sync legt pro Cato-Site einen NetBuddy-Standort (falls unbekannt) samt ``SiteSubnet``-
Segmenten an und pro Socket ein ``Device`` (adapter ``cato``, Typ Firewall). Nichts wird
gelöscht oder verschoben — Konflikte (Subnetz schon an anderem Standort) werden gemeldet.
"""

import ipaddress
import re
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.api_client import HttpxApiClient
from netbuddy.adapters.base import AdapterError
from netbuddy.db.models import (
    Credential,
    CredentialProtocol,
    Device,
    DeviceCredential,
    DeviceType,
    Site,
    SiteSubnet,
)
from netbuddy.services.crawl import guess_adapter

GRAPHQL_PATH = "/api/v1/graphql2"
_PAGE = 200
_MAX_DEVICES = 20_000

_QUERY_SNAPSHOT = """
query snapshot($accountID: ID!) {
  accountSnapshot(accountID: $accountID) {
    sites {
      id
      connectivityStatus
      popName
      hostCount
      info { name type connType isHA
        sockets { id serial isPrimary platform version } }
      devices { id name connected haRole internalIP version
        socketInfo { serial platform version isPrimary } }
    }
  }
}
"""

_QUERY_RANGES = """
query ranges($accountId: ID!, $siteId: String!) {
  site(accountId: $accountId) {
    networkRangeList(input: { site: { by: ID, input: $siteId } }) {
      items { networkRangeId name rangeType subnet localIp gateway vlan
        dhcpSettings { dhcpType ipRange } internetOnly }
      total
    }
  }
}
"""

_QUERY_DEVICES = """
query devices($accountId: ID!, $from: Int!, $limit: Int!) {
  devices(accountId: $accountId) {
    list(input: { paging: { from: $from, limit: $limit },
                  sort: { lastSeen: { direction: DESC, priority: 1 } } }) {
      device {
        id name ip ipAddress category firstSeen lastSeen isManaged
        site { id name }
        nic { macAddress ip vendor }
        os { product vendor version }
        hw { type model manufacturer }
        network { subnet networkName }
      }
      paging { total }
    }
  }
}
"""

# Cato-Gerätetyp/-Kategorie bzw. Hersteller, die auf Netz-Infrastruktur hindeuten.
_INFRA_TYPE = re.compile(
    r"switch|router|firewall|access point|wireless|wlan|network|gateway|controller", re.IGNORECASE
)
_INFRA_VENDOR = re.compile(
    r"fortinet|ubiquiti|fs com|fiberstore|cisco|meraki|aruba|hewlett|hpe|juniper|watchguard"
    r"|palo alto|mikrotik|zyxel|netgear|tp-link|d-link|extreme|brocade|ruckus|lancom|sophos"
    r"|check point|allied telesis|cambium|dell",
    re.IGNORECASE,
)
# Hersteller, die vor allem Server/Clients bauen → nur mit Infrastruktur-Typ als Verdacht zählen.
_AMBIGUOUS_VENDOR = re.compile(r"dell|hewlett|hpe", re.IGNORECASE)


class CatoSocket(BaseModel):
    serial: str | None
    name: str | None
    platform: str | None
    version: str | None
    is_primary: bool | None
    internal_ip: str | None
    connected: bool | None
    ha_role: str | None


class CatoRange(BaseModel):
    id: str | None
    name: str | None
    subnet: str | None
    vlan: int | None
    gateway: str | None
    local_ip: str | None
    range_type: str | None
    dhcp_type: str | None
    dhcp_range: str | None
    internet_only: bool | None


class CatoSite(BaseModel):
    id: str
    name: str
    type: str | None
    conn_type: str | None
    connectivity: str | None
    pop: str | None
    is_ha: bool | None
    host_count: int | None
    sockets: list[CatoSocket] = []
    ranges: list[CatoRange] = []


class CatoDevice(BaseModel):
    id: str | None
    name: str | None
    ip: str | None
    mac: str | None
    nic_vendor: str | None
    site: str | None
    network_name: str | None
    subnet: str | None
    hw_type: str | None
    hw_model: str | None
    manufacturer: str | None
    os: str | None
    category: str | None
    first_seen: str | None
    last_seen: str | None
    is_managed: bool | None


class InfraCandidate(CatoDevice):
    """Geräte-Inventar-Eintrag mit Infrastruktur-Verdacht + Abgleich gegen NetBuddy-Devices."""

    reason: str  # warum Infrastruktur-Verdacht: "typ", "hersteller", "os"
    guessed_adapter: str | None
    known_device_id: uuid.UUID | None  # schon inventarisiert (per Mgmt-IP oder Hostname)


class SyncSummary(BaseModel):
    dry_run: bool
    sites_created: list[str] = []
    sites_matched: list[str] = []  # "Cato-Site → NetBuddy-Standort (Grund)"
    subnets_created: list[str] = []
    subnets_existing: int = 0
    subnets_conflict: list[str] = []  # Subnetz liegt schon an einem anderen Standort
    sockets_created: int = 0
    sockets_updated: int = 0
    sockets_skipped: list[str] = []  # ohne interne IP/Serial


class CatoApi:
    """Dünner GraphQL-Client (Auth-Header, Fehler aus `errors` als AdapterError)."""

    def __init__(self, credential: Credential) -> None:
        extra = credential.extra or {}
        self.account_id = str(extra.get("account_id") or "")
        if not self.account_id:
            raise AdapterError("Cato-Credential braucht extra.account_id")
        base = (credential.base_url or "https://api.catonetworks.com").rstrip("/")
        for suffix in (GRAPHQL_PATH, "/api/v1/graphql"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        self._client = HttpxApiClient(
            base,
            token=credential.api_token,
            header_name=str(extra.get("auth_header", "x-api-key")),
            verify=True,
        )

    async def __aenter__(self) -> "CatoApi":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(None, None, None)

    async def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = await self._client.post_json(
            GRAPHQL_PATH, {"query": query, "variables": variables}
        )
        if not isinstance(payload, dict):
            raise AdapterError("Cato: unerwartete Antwort (kein JSON-Objekt)")
        if payload.get("errors"):
            msg = "; ".join(str(e.get("message", e)) for e in payload["errors"][:3])
            raise AdapterError(f"Cato-API: {msg}")
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}


# --- Parsen (reine Funktionen) ----------------------------------------------------------------


def parse_sites(snapshot: dict[str, Any]) -> list[CatoSite]:
    """accountSnapshot → CatoSite-Liste (ohne Netzbereiche, die kommen pro Site)."""
    sites: list[CatoSite] = []
    for s in (snapshot.get("accountSnapshot") or {}).get("sites") or []:
        info = s.get("info") or {}
        name = info.get("name")
        if not name:
            continue
        # Laufzeit-Sicht (devices) hat IP/Status; Stammdaten (info.sockets) Serial/Modell.
        by_serial: dict[str, dict[str, Any]] = {}
        for sock in info.get("sockets") or []:
            if sock.get("serial"):
                by_serial[sock["serial"]] = dict(sock)
        for dev in s.get("devices") or []:
            si = dev.get("socketInfo") or {}
            serial = si.get("serial")
            entry = by_serial.setdefault(serial or f"dev:{dev.get('id')}", {})
            entry.update(
                {
                    "serial": serial or entry.get("serial"),
                    "name": dev.get("name"),
                    "platform": si.get("platform") or entry.get("platform"),
                    "version": dev.get("version") or si.get("version") or entry.get("version"),
                    "isPrimary": si.get("isPrimary", entry.get("isPrimary")),
                    "internalIP": dev.get("internalIP"),
                    "connected": dev.get("connected"),
                    "haRole": dev.get("haRole"),
                }
            )
        sockets = [
            CatoSocket(
                serial=e.get("serial"),
                name=e.get("name"),
                platform=e.get("platform"),
                version=e.get("version"),
                is_primary=e.get("isPrimary"),
                internal_ip=e.get("internalIP"),
                connected=e.get("connected"),
                ha_role=e.get("haRole"),
            )
            for e in by_serial.values()
        ]
        sites.append(
            CatoSite(
                id=str(s.get("id")),
                name=str(name),
                type=info.get("type"),
                conn_type=info.get("connType"),
                connectivity=s.get("connectivityStatus"),
                pop=s.get("popName"),
                is_ha=info.get("isHA"),
                host_count=s.get("hostCount"),
                sockets=sockets,
            )
        )
    return sites


def parse_ranges(data: dict[str, Any]) -> list[CatoRange]:
    items = ((data.get("site") or {}).get("networkRangeList") or {}).get("items") or []
    out: list[CatoRange] = []
    for r in items:
        dhcp = r.get("dhcpSettings") or {}
        vlan = r.get("vlan")
        out.append(
            CatoRange(
                id=str(r.get("networkRangeId")) if r.get("networkRangeId") else None,
                name=r.get("name"),
                subnet=r.get("subnet"),
                vlan=int(vlan) if vlan not in (None, "") else None,
                gateway=r.get("gateway"),
                local_ip=r.get("localIp"),
                range_type=r.get("rangeType"),
                dhcp_type=dhcp.get("dhcpType"),
                dhcp_range=dhcp.get("ipRange"),
                internet_only=r.get("internetOnly"),
            )
        )
    return out


def parse_devices(data: dict[str, Any]) -> tuple[list[CatoDevice], int]:
    """devices.list → (Geräte dieser Seite, Gesamtzahl)."""
    lst = (data.get("devices") or {}).get("list") or {}
    total = int(((lst.get("paging") or {}).get("total")) or 0)
    out: list[CatoDevice] = []
    for d in lst.get("device") or []:
        nic = d.get("nic") or {}
        os_ = d.get("os") or {}
        hw = d.get("hw") or {}
        net = d.get("network") or {}
        os_parts = (os_.get("vendor"), os_.get("product"), os_.get("version"))
        os_str = " ".join(str(x) for x in os_parts if x)
        out.append(
            CatoDevice(
                id=str(d.get("id")) if d.get("id") else None,
                name=d.get("name"),
                ip=d.get("ip") or d.get("ipAddress") or nic.get("ip"),
                mac=nic.get("macAddress"),
                nic_vendor=nic.get("vendor"),
                site=(d.get("site") or {}).get("name"),
                network_name=net.get("networkName"),
                subnet=net.get("subnet"),
                hw_type=hw.get("type"),
                hw_model=hw.get("model"),
                manufacturer=hw.get("manufacturer"),
                os=os_str or None,
                category=d.get("category"),
                first_seen=d.get("firstSeen"),
                last_seen=d.get("lastSeen"),
                is_managed=d.get("isManaged"),
            )
        )
    return out, total


# --- Netz-Calls ---------------------------------------------------------------------------------


async def fetch_sites(api: CatoApi, *, with_ranges: bool = True) -> list[CatoSite]:
    sites = parse_sites(await api.query(_QUERY_SNAPSHOT, {"accountID": api.account_id}))
    if with_ranges:
        for site in sites:
            try:
                data = await api.query(
                    _QUERY_RANGES, {"accountId": api.account_id, "siteId": site.id}
                )
            except AdapterError:
                continue  # z.B. IPsec-/Cloud-Sites ohne Socket-Netzbereiche
            site.ranges = parse_ranges(data)
    return sorted(sites, key=lambda s: s.name.lower())


async def fetch_devices(api: CatoApi) -> list[CatoDevice]:
    """Komplettes Geräte-Inventar (seitenweise, nach lastSeen absteigend)."""
    devices: list[CatoDevice] = []
    start = 0
    while start < _MAX_DEVICES:
        page, total = parse_devices(
            await api.query(
                _QUERY_DEVICES, {"accountId": api.account_id, "from": start, "limit": _PAGE}
            )
        )
        devices.extend(page)
        start += _PAGE
        if not page or start >= total:
            break
    return devices


# --- DB-Logik -----------------------------------------------------------------------------------


def _net(cidr: str | None) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    try:
        return ipaddress.ip_network(str(cidr), strict=False) if cidr else None
    except ValueError:
        return None


def _resolve_site(
    cato: CatoSite,
    site_map: dict[str, str],
    sites: list[Site],
    subnets: list[SiteSubnet],
) -> tuple[Site | None, str]:
    """Cato-Site → NetBuddy-Standort: site_map > Name/Code > Subnetz-Überlappung."""
    wanted = site_map.get(cato.name)
    if wanted:
        for s in sites:
            if wanted.lower() in {(s.name or "").lower(), (s.code or "").lower()}:
                return s, "site_map"
    for s in sites:
        if cato.name.lower() in {(s.name or "").lower(), (s.code or "").lower()}:
            return s, "name"
    nets = [n for n in (_net(r.subnet) for r in cato.ranges) if n]
    for sub in subnets:
        existing = _net(str(sub.cidr))
        if existing and any(existing.overlaps(n) for n in nets):
            site = next((s for s in sites if s.id == sub.site_id), None)
            if site:
                return site, f"subnetz {sub.cidr}"
    return None, "neu"


async def sync_sites(
    session: AsyncSession, credential: Credential, cato_sites: list[CatoSite], *, dry_run: bool
) -> SyncSummary:
    """Cato-Sites → Standorte + Segmente + Socket-Devices. ``dry_run`` ändert nichts."""
    site_map = {str(k): str(v) for k, v in ((credential.extra or {}).get("site_map") or {}).items()}
    sites = list((await session.execute(select(Site).where(Site.deleted_at.is_(None)))).scalars())
    subnets = list((await session.execute(select(SiteSubnet))).scalars())
    summary = SyncSummary(dry_run=dry_run)
    for cato in cato_sites:
        site, how = _resolve_site(cato, site_map, sites, subnets)
        if site is None:
            summary.sites_created.append(cato.name)
            site = Site(
                name=cato.name,
                description=f"Cato-Site ({cato.type or '?'}, {cato.conn_type or '?'})",
            )
            if not dry_run:
                session.add(site)
                await session.flush()
            sites.append(site)
        else:
            summary.sites_matched.append(f"{cato.name} → {site.name} ({how})")
        for r in cato.ranges:
            net = _net(r.subnet)
            if net is None:
                continue
            same = [s for s in subnets if _net(str(s.cidr)) == net]
            if any(s.site_id == site.id for s in same):
                summary.subnets_existing += 1
                continue
            if same:
                other = next((s for s in sites if s.id == same[0].site_id), None)
                summary.subnets_conflict.append(
                    f"{net} ({cato.name}) liegt schon bei {other.name if other else '?'}"
                )
                continue
            label = f"Cato {cato.name}: {r.name or r.range_type or ''}".strip()
            if r.vlan:
                label += f" VLAN {r.vlan}"
            summary.subnets_created.append(f"{net} — {label}")
            if not dry_run:
                sub = SiteSubnet(site_id=site.id, cidr=str(net), description=label[:255])
                session.add(sub)
                subnets.append(sub)
        await _sync_sockets(session, credential, cato, site, summary, dry_run=dry_run)
    if not dry_run:
        await session.flush()
    return summary


async def _sync_sockets(
    session: AsyncSession,
    credential: Credential,
    cato: CatoSite,
    site: Site,
    summary: SyncSummary,
    *,
    dry_run: bool,
) -> None:
    for i, sock in enumerate(cato.sockets, start=1):
        if not sock.internal_ip or not sock.serial:
            summary.sockets_skipped.append(f"{cato.name}: {sock.name or sock.serial or '?'}")
            continue
        hostname = sock.name or f"{cato.name}-socket{i}"
        stmt = select(Device).where(
            Device.deleted_at.is_(None),
            (Device.serial_number == sock.serial) | (Device.hostname == hostname),
        )
        dev = (await session.execute(stmt)).scalars().first()
        if dev is None:
            summary.sockets_created += 1
            if dry_run:
                continue
            dev = Device(
                hostname=hostname,
                mgmt_ip=sock.internal_ip,
                vendor="cato",
                model=sock.platform,
                os_version=sock.version,
                serial_number=sock.serial,
                adapter_id="cato",
                device_type=DeviceType.FIREWALL,
                site_id=site.id,
                enabled=True,
                notes=f"Cato-Socket Site {cato.name} ({sock.ha_role or 'single'})",
            )
            session.add(dev)
            await session.flush()
        else:
            summary.sockets_updated += 1
            if dry_run:
                continue
            dev.mgmt_ip = sock.internal_ip
            dev.model = sock.platform or dev.model
            dev.os_version = sock.version or dev.os_version
            dev.serial_number = sock.serial
            dev.site_id = dev.site_id or site.id
        link = (
            await session.execute(
                select(DeviceCredential).where(
                    DeviceCredential.device_id == dev.id,
                    DeviceCredential.credential_id == credential.id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            session.add(
                DeviceCredential(
                    device_id=dev.id, credential_id=credential.id, protocol=CredentialProtocol.API
                )
            )


def _infra_reason(d: CatoDevice) -> str | None:
    blob = " ".join(str(x) for x in (d.hw_type, d.category) if x)
    if _INFRA_TYPE.search(blob):
        return "typ"
    vendor = " ".join(str(x) for x in (d.manufacturer, d.nic_vendor) if x)
    if _INFRA_VENDOR.search(vendor) and not _AMBIGUOUS_VENDOR.search(vendor):
        return "hersteller"
    os_ = (d.os or "").lower()
    if any(k in os_ for k in ("ios", "nx-os", "junos", "fortios", "os10", "unifi", "meraki")):
        return "os"
    return None


async def infra_candidates(
    session: AsyncSession, devices: list[CatoDevice], *, infra_only: bool = True
) -> list[InfraCandidate]:
    """Geräte-Inventar → Infrastruktur-Verdachte, mit Abgleich gegen bekannte Devices."""
    existing = list(
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars()
    )
    known = {str(d.mgmt_ip): d.id for d in existing}
    known_names = {(d.hostname or "").lower(): d.id for d in existing}
    out: list[InfraCandidate] = []
    for d in devices:
        reason = _infra_reason(d)
        if infra_only and reason is None:
            continue
        desc = " ".join(str(x) for x in (d.manufacturer, d.hw_model, d.os, d.nic_vendor) if x)
        out.append(
            InfraCandidate(
                **d.model_dump(),
                reason=reason or "-",
                guessed_adapter=guess_adapter(desc, None, chassis_id=d.mac),
                known_device_id=known.get(d.ip or "") or known_names.get((d.name or "").lower()),
            )
        )
    out.sort(key=lambda c: ((c.site or "").lower(), (c.name or c.ip or "").lower()))
    return out
