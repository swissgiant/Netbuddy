import ipaddress
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import SiteSubnet


async def site_for_ip(session: AsyncSession, ip: str) -> uuid.UUID | None:
    """Standort einer IP über die Site-Segmente (längster passender Präfix gewinnt).

    Macht die Standort-Zuordnung automatisch: Geräte beim Anlegen, Crawl-Funde,
    später VLAN-Scoping. None, wenn kein Segment passt.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    best: tuple[int, uuid.UUID] | None = None
    for subnet in (await session.execute(select(SiteSubnet))).scalars():
        try:
            net = ipaddress.ip_network(str(subnet.cidr))
        except ValueError:
            continue
        if addr in net and (best is None or net.prefixlen > best[0]):
            best = (net.prefixlen, subnet.site_id)
    return best[1] if best else None


def subnet_overlaps_site(cidrs: list[str], site_cidrs: list[str]) -> bool:
    """True, wenn eines der ``cidrs`` (z.B. VPN-Selektoren) ein Site-Segment überlappt."""
    nets = []
    for c in site_cidrs:
        try:
            nets.append(ipaddress.ip_network(str(c)))
        except ValueError:
            continue
    for c in cidrs:
        try:
            candidate = ipaddress.ip_network(str(c))
        except ValueError:
            continue
        if any(candidate.overlaps(net) for net in nets):
            return True
    return False
