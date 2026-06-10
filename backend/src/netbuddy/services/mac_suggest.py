import re

from pydantic import BaseModel
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import ArpEntry, Device, Host, Interface, LldpNeighbor, MacAddressEntry
from netbuddy.services.hosts import normalize_mac
from netbuddy.services.oui import vendor_for_mac

# Hersteller, die (fast) nur Netz-Infrastruktur bauen → MAC in der Tabelle = vermutlich
# Switch/Firewall/AP. Bewusst OHNE Dell/Intel/Broadcom: das sind im Fleet vor allem
# Server-NICs und Latitude-Laptops; Dell-SWITCHES melden sich ohnehin per LLDP.
_INFRA_VENDORS = re.compile(
    r"fortinet|ubiquiti|fs com|fiberstore|cisco|aruba|juniper|watchguard|palo alto"
    r"|mikrotik|zyxel|netgear|tp-link|d-link|extreme netw|brocade|ruckus|lancom"
    r"|sophos|check point|allied telesis|cambium",
    re.IGNORECASE,
)

# OUI-Hersteller → adapter_id, nur wo eindeutig (FS Centec/Ruijie und Dell OS10/OS6
# sind per MAC nicht unterscheidbar).
_ADAPTER_FOR_VENDOR: list[tuple[str, str]] = [
    ("fortinet", "fortigate"),
    ("ubiquiti", "unifi"),
]


class MacSuggestedDevice(BaseModel):
    """Infrastruktur-Verdacht aus der MAC-Tabelle (OUI): Gerät ohne LLDP erkennen."""

    mac: str  # kanonisch (12 Hex)
    vendor: str  # OUI-Hersteller (IEEE-Registry)
    ip_address: str | None  # aus ARP (für 1-Klick-Anlage)
    name: str | None  # aus DNS (Host-Korrelation)
    guessed_adapter: str | None
    seen_on: list[str]  # "<hostname> / <interface>"


def _guess_adapter(vendor: str) -> str | None:
    low = vendor.lower()
    for needle, adapter_id in _ADAPTER_FOR_VENDOR:
        if needle in low:
            return adapter_id
    return None


async def suggest_devices_from_mac_table(session: AsyncSession) -> list[MacSuggestedDevice]:
    """Schlägt Geräte vor, deren MAC-OUI auf einen Infrastruktur-Hersteller zeigt.

    Ergänzt die LLDP-Vorschläge um Geräte, die LLDP **nicht** sprechen (z.B. FS-Switches
    mit Default-Konfig): deren MAC taucht trotzdem in den MAC-Tabellen der Nachbarn auf.
    Bereits inventarisierte Geräte (per ARP-IP) und LLDP-bekannte Chassis werden gefiltert.
    """
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    known_ips = {str(d.mgmt_ip) for d in devices}
    device_by_id = {d.id: d for d in devices}
    iface_by_id = {i.id: i for i in (await session.execute(select(Interface))).scalars()}

    # LLDP-bekannte Chassis (laufen über die LLDP-Vorschläge, hier nicht doppelt melden).
    lldp_chassis = {
        normalize_mac(c)
        for (c,) in (await session.execute(select(LldpNeighbor.remote_chassis_id))).all()
        if normalize_mac(c)
    }

    arp_ip: dict[str, str] = {}
    for ip, mac in (await session.execute(select(ArpEntry.ip_address, ArpEntry.mac))).all():
        arp_ip.setdefault(mac, ip)
    hosts = {h.mac: h for h in (await session.execute(select(Host))).scalars()}

    rows = (
        await session.execute(
            select(
                cast(MacAddressEntry.mac_address, String),
                MacAddressEntry.device_id,
                MacAddressEntry.interface_id,
            )
        )
    ).all()

    by_mac: dict[str, MacSuggestedDevice] = {}
    for raw_mac, device_id, interface_id in rows:
        mac = normalize_mac(raw_mac)
        if not mac or mac in lldp_chassis:
            continue
        vendor = vendor_for_mac(mac)
        if vendor is None or not _INFRA_VENDORS.search(vendor):
            continue
        ip = arp_ip.get(mac)
        if ip is not None and ip in known_ips:
            continue  # schon im Inventar
        dev = device_by_id.get(device_id)
        iface = iface_by_id.get(interface_id)
        seen = f"{dev.hostname if dev else '?'} / {iface.name if iface else '?'}"
        entry = by_mac.get(mac)
        if entry is None:
            host = hosts.get(mac)
            by_mac[mac] = MacSuggestedDevice(
                mac=mac,
                vendor=vendor,
                ip_address=ip or (host.ip_address if host else None),
                name=host.name if host else None,
                guessed_adapter=_guess_adapter(vendor),
                seen_on=[seen],
            )
        elif seen not in entry.seen_on:
            entry.seen_on.append(seen)

    return sorted(by_mac.values(), key=lambda s: (s.vendor.lower(), s.mac))
