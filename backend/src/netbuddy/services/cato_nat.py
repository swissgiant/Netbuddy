"""Cato Range-NAT: interne (ggf. doppelt vergebene) IPs auf ihre erreichbare Adresse übersetzen.

Viele Standorte (v.a. Steelco) nutzen private Netze mehrfach (z.B. 192.168.1.0/24). Cato bildet
diese je Standort auf eine eindeutige ``translatedSubnet`` ab (z.B. Riese 192.168.1.0/24 →
10.137.101.0/24). Damit lassen sich auch doppelt vergebene Geräte von BLS aus erreichen. Dieser
Helfer liest die Übersetzungstabelle aus Cato und schreibt je Gerät die **erreichbare** Adresse
in ``extra.reachable_ip`` (für SNMP-/API-Zugriff), ohne die intern dokumentierte IP zu verlieren.
"""

import ipaddress
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Credential, PhysicalServer, Site, StorageDevice

# NetBuddy-Standort → Cato-Standortname (nur wo sie abweichen; B-* heissen gleich).
_SITE_TO_CATO = {
    "S00 - Steelco HQ": "SCO-S00-Riese",
    "S01 - Icos Pharma": "SCO-S01-Cusano",
    "S00 - Valla Office": "SCO-S00-Valla",
    "S02 - Steelco Service": "SCO-S02-Padova",
    "S05 - Steelco Benelux": "SCO-S05-Vianen",
}


class NatRule(BaseModel):
    cato_site: str
    internal: str
    translated: str


class NatResolveSummary(BaseModel):
    rules: int = 0
    storage_resolved: int = 0
    physical_resolved: int = 0


async def fetch_nat_rules(session: AsyncSession) -> list[NatRule]:
    """Übersetzungstabelle (subnet → translatedSubnet, nur wo abweichend) aus Cato lesen."""
    from netbuddy.services.cato_inventory import (
        _QUERY_RANGES,
        _QUERY_SNAPSHOT,
        CatoApi,
        parse_sites,
    )

    cred = (
        (
            await session.execute(
                select(Credential).where(
                    Credential.base_url.ilike("%catonetworks%"), Credential.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .first()
    )
    if cred is None:
        return []
    rules: list[NatRule] = []
    async with CatoApi(cred) as api:
        sites = parse_sites(await api.query(_QUERY_SNAPSHOT, {"accountID": api.account_id}))
        for site in sites:
            try:
                data = await api.query(
                    _QUERY_RANGES, {"accountId": api.account_id, "siteId": site.id}
                )
            except Exception:
                continue
            for item in data["site"]["networkRangeList"]["items"]:
                sub = item.get("subnet")
                tr = item.get("translatedSubnet")
                if sub and tr and sub != tr:
                    rules.append(NatRule(cato_site=site.name, internal=sub, translated=tr))
    return rules


def translate(rules: list[NatRule], cato_site: str, ip: str) -> str | None:
    """Erreichbare (übersetzte) Adresse für eine interne IP am gegebenen Cato-Standort."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for rule in rules:
        if rule.cato_site != cato_site:
            continue
        try:
            net = ipaddress.ip_network(rule.internal, strict=False)
            tnet = ipaddress.ip_network(rule.translated, strict=False)
        except ValueError:
            continue
        if addr in net:
            host = int(addr) - int(net.network_address)
            return str(ipaddress.ip_address(int(tnet.network_address) + host))
    return None


def _cato_site_for(site_name: str | None) -> str | None:
    if not site_name:
        return None
    return _SITE_TO_CATO.get(site_name, site_name)


def reachable_ip(
    dev: StorageDevice | PhysicalServer, site_name: str | None, rules: list[NatRule]
) -> str | None:
    """Erreichbare IP: übersetzte Adresse, falls eine NAT-Regel greift, sonst die Mgmt-IP selbst."""
    if dev.mgmt_ip is None:
        return None
    ip = str(dev.mgmt_ip)
    cato = _cato_site_for(site_name)
    if cato:
        tr = translate(rules, cato, ip)
        if tr:
            return tr
    return ip


async def resolve_reachable_ips(session: AsyncSession) -> NatResolveSummary:
    """Schreibt je Gerät ``extra.reachable_ip`` (übersetzt, wo nötig)."""
    rules = await fetch_nat_rules(session)
    summary = NatResolveSummary(rules=len(rules))
    site_names: dict[Any, str] = {
        s.id: s.name for s in (await session.execute(select(Site))).scalars().all()
    }
    storage = (
        (
            await session.execute(
                select(StorageDevice).where(
                    StorageDevice.deleted_at.is_(None), StorageDevice.mgmt_ip.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for dev in storage:
        tr = reachable_ip(dev, site_names.get(dev.site_id), rules)
        if tr and tr != str(dev.mgmt_ip):
            dev.extra = {**(dev.extra or {}), "reachable_ip": tr}
            summary.storage_resolved += 1
    physical = (
        (
            await session.execute(
                select(PhysicalServer).where(
                    PhysicalServer.deleted_at.is_(None), PhysicalServer.mgmt_ip.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for pdev in physical:
        tr = reachable_ip(pdev, site_names.get(pdev.site_id), rules)
        if tr and tr != str(pdev.mgmt_ip):
            pdev.extra = {**(pdev.extra or {}), "reachable_ip": tr}
            summary.physical_resolved += 1
    await session.commit()
    return summary
