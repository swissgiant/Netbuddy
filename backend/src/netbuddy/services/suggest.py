import re
import uuid

from pydantic import BaseModel
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import ArpEntry, Device, Host, Interface, LldpNeighbor, MacAddressEntry
from netbuddy.services.crawl import guess_adapter
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


class SuggestedDevice(BaseModel):
    """Vereinheitlichter Geräte-Vorschlag: LLDP-Nachbar und/oder MAC-Tabellen-Verdacht (OUI).

    Gemeinsamer Schlüssel ist die kanonische Chassis-/Quell-MAC — meldet ein Gerät sich per
    LLDP **und** taucht seine MAC in MAC-Tabellen auf, wird das zu EINEM Eintrag gemerged.
    """

    key: str  # kanonische MAC oder (bei Nicht-MAC-Chassis) der LLDP-Chassis-String
    sources: list[str]  # "lldp" und/oder "mac"
    name: str | None  # LLDP-System-Name, sonst DNS-Kurzname
    dns_name: str | None  # voller Reverse-DNS-Name (Host-Korrelation)
    ip_address: str | None  # LLDP-Mgmt-Adresse > ARP > Host
    vendor: str | None  # Hersteller aus dem MAC-OUI (IEEE-Registry)
    chassis_id: str | None  # roher LLDP-Chassis-Wert (nur bei LLDP-Quelle)
    system_description: str | None
    guessed_adapter: str | None
    seen_on: list[str]  # "<hostname> / <interface>"


def _merge_seen(entry: SuggestedDevice, seen: str) -> None:
    if seen not in entry.seen_on:
        entry.seen_on.append(seen)


async def suggest_devices(session: AsyncSession) -> list[SuggestedDevice]:
    """Eine Liste für alles „Gefundene, noch nicht Inventarisierte":

    1. LLDP-Nachbarn bekannter Geräte (sprechen LLDP, melden meist Name/Beschreibung).
    2. Infrastruktur-MACs aus den MAC-Tabellen (OUI-Filter) — Geräte OHNE LLDP.
    Angereichert mit IP (LLDP-Mgmt > ARP) und DNS-Name (Host-Korrelation).
    """
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    known_hostnames = {d.hostname for d in devices}
    known_ips = {str(d.mgmt_ip) for d in devices}
    device_by_id = {d.id: d for d in devices}
    iface_by_id = {i.id: i for i in (await session.execute(select(Interface))).scalars()}

    arp_by_mac: dict[str, str] = {}
    for ip, mac in (await session.execute(select(ArpEntry.ip_address, ArpEntry.mac))).all():
        if mac:
            arp_by_mac.setdefault(mac, ip)
    hosts = {h.mac: h for h in (await session.execute(select(Host))).scalars()}

    def seen_label(device_id: uuid.UUID, interface_id: uuid.UUID) -> str:
        dev = device_by_id.get(device_id)
        iface = iface_by_id.get(interface_id)
        return f"{dev.hostname if dev else '?'} / {iface.name if iface else '?'}"

    by_key: dict[str, SuggestedDevice] = {}

    # --- Quelle 1: LLDP-Nachbarn -------------------------------------------------------------
    for n in (await session.execute(select(LldpNeighbor))).scalars():
        if n.remote_system_name and n.remote_system_name in known_hostnames:
            continue  # schon im Inventar
        mac = normalize_mac(n.remote_chassis_id)
        key = mac or n.remote_chassis_id
        host = hosts.get(mac) if mac else None
        ip = (
            n.remote_mgmt_address
            or (arp_by_mac.get(mac) if mac else None)
            or (host.ip_address if host else None)
        )
        seen = seen_label(n.local_device_id, n.local_interface_id)
        dns_short = host.name.split(".")[0] if host and host.name else None
        entry = by_key.get(key)
        if entry is None:
            by_key[key] = SuggestedDevice(
                key=key,
                sources=["lldp"],
                name=n.remote_system_name or dns_short,
                dns_name=host.name if host else None,
                ip_address=ip,
                vendor=vendor_for_mac(n.remote_chassis_id),
                chassis_id=n.remote_chassis_id,
                system_description=n.remote_system_description,
                guessed_adapter=guess_adapter(
                    n.remote_system_description, None, chassis_id=n.remote_chassis_id
                ),
                seen_on=[seen],
            )
        else:
            _merge_seen(entry, seen)
            entry.name = entry.name or n.remote_system_name
            entry.ip_address = entry.ip_address or ip
            entry.system_description = entry.system_description or n.remote_system_description
            entry.guessed_adapter = entry.guessed_adapter or guess_adapter(
                n.remote_system_description, None, chassis_id=n.remote_chassis_id
            )

    # --- Quelle 2: MAC-Tabellen (nur Infrastruktur-OUIs) --------------------------------------
    rows = (
        await session.execute(
            select(
                cast(MacAddressEntry.mac_address, String),
                MacAddressEntry.device_id,
                MacAddressEntry.interface_id,
            )
        )
    ).all()
    for raw_mac, device_id, interface_id in rows:
        mac = normalize_mac(raw_mac)
        if not mac:
            continue
        seen = seen_label(device_id, interface_id)
        entry = by_key.get(mac)
        if entry is not None:
            # schon per LLDP bekannt → nur Quelle + Fundort ergänzen
            if "mac" not in entry.sources:
                entry.sources.append("mac")
            _merge_seen(entry, seen)
            continue
        vendor = vendor_for_mac(mac)
        if vendor is None or not _INFRA_VENDORS.search(vendor):
            continue
        ip = arp_by_mac.get(mac)
        if ip is not None and ip in known_ips:
            continue  # schon im Inventar (per Mgmt-IP gematcht)
        host = hosts.get(mac)
        by_key[mac] = SuggestedDevice(
            key=mac,
            sources=["mac"],
            name=host.name.split(".")[0] if host and host.name else None,
            dns_name=host.name if host else None,
            ip_address=ip or (host.ip_address if host else None),
            vendor=vendor,
            chassis_id=None,
            system_description=None,
            guessed_adapter=guess_adapter(None, None, chassis_id=mac),
            seen_on=[seen],
        )

    # LLDP-Funde zuerst (meist die aussagekräftigeren), dann nach Hersteller/Schlüssel.
    return sorted(
        by_key.values(),
        key=lambda s: ("lldp" not in s.sources, (s.vendor or "~").lower(), s.key),
    )
