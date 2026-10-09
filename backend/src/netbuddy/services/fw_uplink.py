"""Firewall-/Cato-Socket-Uplinks aus MAC- und ARP-Tabellen ableiten.

Cato-Sockets und viele Firewalls sprechen kein LLDP; ihr Anschluss-Port am Switch lässt sich
aber messen: Die Gateway-MAC (ARP-Eintrag für die erste/letzte Adresse eines Standort-Subnetzes
oder für die Management-IP der Firewall) wird auf genau einem Port je Switch gelernt. Auf dem
**direkt** angeschlossenen Switch trägt dieser Port nur die Firewall-MACs (wenige Adressen); auf
allen anderen Switches ist es der Uplink Richtung Core mit hunderten MACs. Daraus entstehen
echte, gemessene Kanten Switch↔Firewall für die Topologie und ein Check „hängt der Standort am
erwarteten Cato-Punkt?".
"""

import ipaddress
import uuid
from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    ArpEntry,
    Device,
    DeviceType,
    Interface,
    MacAddressEntry,
    SiteSubnet,
)

# Ein Port gilt als direkte Firewall-Verbindung, wenn er höchstens so viele verschiedene MACs
# trägt (Sockets haben je VLAN eine virtuelle MAC → Handvoll, ein Core-Uplink hat hunderte).
_DIRECT_MAX_MACS = 12


class FwUplink(BaseModel):
    site_id: uuid.UUID
    switch_id: uuid.UUID
    switch_hostname: str
    port: str
    firewall_ids: list[uuid.UUID]  # Firewall(s)/Sockets des Standorts
    gateway_macs: list[str]
    macs_on_port: int
    direct: bool  # True = Port trägt nur Gateway-MACs → direkt an der Firewall/am Socket


def _canon(mac: str) -> str:
    return "".join(ch for ch in str(mac).lower() if ch in "0123456789abcdef")


def _gateway_ips(cidrs: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for cidr in cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        hosts = list(net.hosts()) if net.num_addresses <= 2**16 else []
        if hosts:
            out.add(str(hosts[0]))
            out.add(str(hosts[-1]))
    return out


async def firewall_uplinks(session: AsyncSession, devices: Sequence[Device]) -> list[FwUplink]:
    """Je Standort mit Firewall(s) und Switches: wo wird die Gateway-MAC gelernt?"""
    by_site: dict[uuid.UUID, list[Device]] = defaultdict(list)
    for d in devices:
        if d.site_id is not None:
            by_site[d.site_id].append(d)
    subnets: dict[uuid.UUID, list[str]] = defaultdict(list)
    for sub in (await session.execute(select(SiteSubnet))).scalars():
        subnets[sub.site_id].append(str(sub.cidr))

    result: list[FwUplink] = []
    for site_id, members in by_site.items():
        firewalls = [
            d for d in members if d.device_type in (DeviceType.FIREWALL, DeviceType.ROUTER)
        ]
        switches = [d for d in members if d.device_type == DeviceType.SWITCH]
        if not firewalls or not switches:
            continue
        switch_ids = [d.id for d in switches]
        gateway_ips = _gateway_ips(subnets.get(site_id, [])) | {str(f.mgmt_ip) for f in firewalls}
        arp_rows = (
            await session.execute(
                select(ArpEntry.mac).where(
                    ArpEntry.device_id.in_(switch_ids), ArpEntry.ip_address.in_(gateway_ips)
                )
            )
        ).scalars()
        gateway_macs = {_canon(m) for m in arp_rows}
        if not gateway_macs:
            continue
        rows = (
            await session.execute(
                select(MacAddressEntry.device_id, Interface.name, MacAddressEntry.mac_address)
                .join(Interface, Interface.id == MacAddressEntry.interface_id)
                .where(
                    MacAddressEntry.device_id.in_(switch_ids),
                    MacAddressEntry.deleted_at.is_(None),
                )
            )
        ).all()
        per_port: dict[tuple[uuid.UUID, str], set[str]] = defaultdict(set)
        for dev_id, port, mac in rows:
            per_port[(dev_id, port)].add(_canon(mac))
        for sw in switches:
            candidates = [
                (port, macs)
                for (dev_id, port), macs in per_port.items()
                if dev_id == sw.id and macs & gateway_macs
            ]
            if not candidates:
                continue
            # Der Port mit den meisten Gateway-MACs ist die Richtung zur Firewall.
            port, macs = max(candidates, key=lambda c: (len(c[1] & gateway_macs), -len(c[1])))
            result.append(
                FwUplink(
                    site_id=site_id,
                    switch_id=sw.id,
                    switch_hostname=sw.hostname,
                    port=port,
                    firewall_ids=[f.id for f in firewalls],
                    gateway_macs=sorted(macs & gateway_macs),
                    macs_on_port=len(macs),
                    direct=len(macs) <= _DIRECT_MAX_MACS,
                )
            )
    return result
