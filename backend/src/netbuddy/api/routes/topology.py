import uuid
from collections import defaultdict

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import (
    ApLocation,
    Device,
    DeviceType,
    LldpNeighbor,
    Site,
    SiteSubnet,
    VpnTunnel,
)
from netbuddy.services.sites_net import subnet_overlaps_site

router = APIRouter(prefix="/topology", tags=["topology"])


class TopologyNode(BaseModel):
    id: str  # z.B. "device:<uuid>" / "site:<uuid>"
    label: str
    type: str  # "site" | "switch" | "firewall" | "router" | "ap" | "other"
    parent: str | None = None  # Compound: Geräte liegen IM Standort-Container


class TopologyEdge(BaseModel):
    source: str
    target: str
    type: str  # "lldp" (Gerät↔Gerät) | "vpn" (Standort↔Standort)
    label: str | None = None
    up: bool | None = None  # für vpn: Tunnel-Status


class Topology(BaseModel):
    """Graph für das GUI: Standorte als Container (Compound-Knoten), Geräte darin,
    LLDP-Links zwischen Geräten und VPN-Kanten zwischen Standorten.

    Die `type`-Felder dienen dem Frontend als Layer (ein-/ausblendbar).
    """

    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


@router.get("", response_model=Topology)
async def get_topology(session: SessionDep) -> Topology:
    """Liefert den Topologie-Graphen (Standorte als Wolken, Geräte, LLDP- + VPN-Kanten)."""
    sites = (await session.execute(select(Site).where(Site.deleted_at.is_(None)))).scalars().all()
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )
    subnets_by_site: dict[uuid.UUID, list[str]] = {}
    for sub in (await session.execute(select(SiteSubnet))).scalars():
        subnets_by_site.setdefault(sub.site_id, []).append(str(sub.cidr))

    nodes: list[TopologyNode] = [
        TopologyNode(id=f"site:{s.id}", label=s.name, type="site") for s in sites
    ]
    by_hostname: dict[str, Device] = {}
    for device in devices:
        nodes.append(
            TopologyNode(
                id=f"device:{device.id}",
                label=device.hostname,
                type=device.device_type.value,
                parent=f"site:{device.site_id}" if device.site_id else None,
            )
        )
        by_hostname[device.hostname] = device
        # Auch unter dem Kurznamen (vor dem ersten Punkt) ablegen: LLDP meldet oft den FQDN
        # (z.B. "BLS-SLO2.bls.local"), das Inventar führt aber "BLS-SLO2" — sonst kein Match.
        short = device.hostname.split(".")[0]
        by_hostname.setdefault(short, device)

    edges: list[TopologyEdge] = []
    devices_by_id = {device.id: device for device in devices}
    ip2dev = {str(d.mgmt_ip): d for d in devices}

    def is_ap(device_id: uuid.UUID | None) -> bool:
        d = devices_by_id.get(device_id) if device_id else None
        return d is not None and d.device_type == DeviceType.AP

    # Site-Core + Site-Firewall (Core = Name "core" oder DC-Plattform dell_os10/fs_ruijie).
    site_switches: dict[uuid.UUID, list[Device]] = defaultdict(list)
    site_fw: dict[uuid.UUID, Device] = {}
    for d in devices:
        if d.site_id is None:
            continue
        if d.device_type == DeviceType.SWITCH:
            site_switches[d.site_id].append(d)
        elif d.device_type in (DeviceType.FIREWALL, DeviceType.ROUTER) and d.site_id not in site_fw:
            site_fw[d.site_id] = d
    site_core: dict[uuid.UUID, Device] = {}
    for sid, sws in site_switches.items():
        named = [s for s in sws if "core" in s.hostname.lower()]
        dc = [s for s in sws if s.adapter_id in ("dell_os10", "fs_ruijie")]
        if named:
            site_core[sid] = named[0]
        elif dc:
            site_core[sid] = dc[0]

    seen: set[tuple[str, str, str]] = set()

    def add_edge(a: uuid.UUID, b: uuid.UUID, etype: str, label: str | None = None) -> None:
        if a == b:
            return
        key = (str(a), str(b), etype) if str(a) < str(b) else (str(b), str(a), etype)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            TopologyEdge(source=f"device:{a}", target=f"device:{b}", type=etype, label=label)
        )

    # Echte LLDP-Backbone-Kanten: Match per Hostname ODER mgmt-IP. Unaufgelöste, von ≥2 Switches
    # einer Site gemeldete Hub-Nachbarn (z.B. OS10-Core meldet "SW2") werden auf das Site-Core-
    # Gerät aufgelöst — auch das sind echte, gemessene LLDP-Kanten, keine Fabrikation.
    lldp = (await session.execute(select(LldpNeighbor))).scalars().all()
    hub_reporters: dict[tuple[uuid.UUID, str], set[uuid.UUID]] = defaultdict(set)
    for n in lldp:
        local = devices_by_id.get(n.local_device_id)
        if local is None or is_ap(local.id):
            continue
        remote = None
        if n.remote_system_name:
            remote = by_hostname.get(n.remote_system_name) or by_hostname.get(
                n.remote_system_name.split(".")[0]
            )
        if remote is None and n.remote_mgmt_address:
            remote = ip2dev.get(str(n.remote_mgmt_address))
        if remote is not None:
            if not is_ap(remote.id):
                add_edge(local.id, remote.id, "lldp")
            continue
        # Firewalls NICHT als Hub-Reporter: ihre unaufgelösten Nachbarn sind WAN/extern
        # (Aruba/Trzin/…), nicht der lokale Core → sonst falsche FW↔Core-Kante (Gro).
        key = (n.remote_chassis_id or n.remote_system_name or "").lower()
        if key and local.site_id is not None and local.device_type.value != "firewall":
            hub_reporters[(local.site_id, key)].add(local.id)
    for (sid, _key), reporters in hub_reporters.items():
        core = site_core.get(sid)
        if core is not None and len(reporters) >= 2:  # geteilter Hub = der Core (Clients raus)
            for r in reporters:
                add_edge(r, core.id, "lldp")

    # AP→Switch-Uplinks (+ persistierte UniFi-Switch→Core-Uplinks) — echte, gemessene Verortung.
    # Mesh-APs (drahtloser Uplink) bekommen stattdessen eine gestrichelte Kante zum Eltern-AP.
    ap_locs = (await session.execute(select(ApLocation))).scalars().all()
    ap_dev_by_mac = {
        loc.ap_mac: by_hostname.get(loc.ap_name)
        for loc in ap_locs
        if by_hostname.get(loc.ap_name) is not None
    }
    for loc in ap_locs:
        dev = by_hostname.get(loc.ap_name)
        if dev is not None and loc.device_id is not None and loc.device_id in devices_by_id:
            if dev.id != loc.device_id:
                add_edge(dev.id, loc.device_id, "uplink", loc.port or None)
        # Drahtlose Mesh-Verbindung zum Eltern-AP (echte UniFi-uplink_mac-Daten).
        if dev is not None and loc.uplink_ap_mac:
            parent = ap_dev_by_mac.get(loc.uplink_ap_mac)
            if parent is not None and parent.id != dev.id:
                add_edge(dev.id, parent.id, "wireless", "Mesh")

    # VPN-Kanten von der lokalen Firewall zur **Firewall** des Remote-Standorts (nicht zum Block).
    device_site = {d.id: d.site_id for d in devices}
    seen_vpn: set[tuple[str, str, str]] = set()
    for tunnel in (await session.execute(select(VpnTunnel))).scalars():
        if not tunnel.relevant or tunnel.device_id not in device_site:
            continue
        local_site = device_site.get(tunnel.device_id)
        for site in sites:
            if site.id == local_site:
                continue
            site_cidrs = subnets_by_site.get(site.id, [])
            if not site_cidrs:
                continue
            if not subnet_overlaps_site([str(s) for s in tunnel.remote_subnets], site_cidrs):
                continue
            vkey = (str(tunnel.device_id), str(site.id), tunnel.name)
            if vkey in seen_vpn:
                continue
            seen_vpn.add(vkey)
            remote_fw = site_fw.get(site.id)
            target = f"device:{remote_fw.id}" if remote_fw else f"site:{site.id}"
            edges.append(
                TopologyEdge(
                    source=f"device:{tunnel.device_id}",
                    target=target,
                    type="vpn",
                    label=tunnel.name,
                    up=tunnel.is_up,
                )
            )

    # Kein Gerät ohne Verbindung: verbleibende Waisen hängen an einem "unerkannten Switch" je
    # Standort — ehrlicher Platzhalter für einen real existierenden, aber (noch) nicht
    # identifizierten Switch (statt einer erfundenen Linie zum Core).
    connected: set[str] = set()
    for e in edges:
        for ref in (e.source, e.target):
            if ref.startswith("device:"):
                connected.add(ref.split(":", 1)[1])
    unknown_by_site: dict[uuid.UUID, str] = {}
    for d in devices:
        if str(d.id) in connected or d.site_id is None:
            continue
        uid = unknown_by_site.get(d.site_id)
        if uid is None:
            uid = f"unknown:{d.site_id}"
            unknown_by_site[d.site_id] = uid
            nodes.append(
                TopologyNode(
                    id=uid, label="Unbekannter Switch", type="unknown", parent=f"site:{d.site_id}"
                )
            )
        edges.append(TopologyEdge(source=f"device:{d.id}", target=uid, type="uplink"))

    return Topology(nodes=nodes, edges=edges)
