import asyncio
import re
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import ArpEntry, Host

_NON_HEX = re.compile(r"[^0-9a-f]")


def normalize_mac(raw: str) -> str:
    """MAC auf kanonische 12-Hex-Kleinbuchstaben reduzieren (Trenner/Whitespace entfernt).

    Vendor schreiben MACs verschieden (``08:00:2b:01:02:03``, ``0800.2b01.0203``,
    ``08-00-2b-01-02-03``). Für den Abgleich ARP ↔ MAC-Table ↔ Host brauchen wir eine
    einheitliche Form. Liefert ``""`` bei ungültiger Länge (≠ 12 Hex).
    """
    cleaned = _NON_HEX.sub("", raw.strip().lower())
    return cleaned if len(cleaned) == 12 else ""


# IP → Hostname (oder None). Injizierbar, damit Tests ohne echtes DNS laufen.
DnsResolver = Callable[[str], Awaitable[str | None]]


async def reverse_dns(ip: str) -> str | None:
    """Reverse-DNS-Auflösung (PTR) im Thread-Pool — ``socket`` ist blockierend."""
    try:
        host, _aliases, _addrs = await asyncio.to_thread(socket.gethostbyaddr, ip)
    except OSError:
        return None
    return host or None


async def correlate_hosts(
    session: AsyncSession, resolver: DnsResolver = reverse_dns
) -> dict[str, int]:
    """Korreliert die gesammelten ARP-Einträge zu Hosts: MAC ↔ IP (ARP) ↔ Name (Reverse-DNS).

    Pro kanonischer MAC wird die zuletzt gesehene IP gewählt und per ``resolver`` aufgelöst.
    Idempotent: bestehende Hosts werden aktualisiert (Upsert über die MAC). Read-only gegenüber
    Geräten — es werden nur DB-Daten und DNS genutzt.
    """
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(ArpEntry.mac, ArpEntry.ip_address).order_by(ArpEntry.updated_at)
        )
    ).all()
    # Letzte IP je MAC gewinnt (rows sind nach updated_at sortiert).
    ip_by_mac: dict[str, str] = {mac: ip for mac, ip in rows if mac and ip}

    existing = {h.mac: h for h in (await session.execute(select(Host))).scalars()}
    resolved = 0
    for mac, ip in ip_by_mac.items():
        name = await resolver(ip)
        host = existing.get(mac)
        if host is None:
            host = Host(mac=mac)
            session.add(host)
            existing[mac] = host
        host.ip_address = ip
        host.name = name
        host.resolved_at = now
        if name:
            resolved += 1
    await session.flush()
    return {"hosts": len(ip_by_mac), "resolved": resolved}
