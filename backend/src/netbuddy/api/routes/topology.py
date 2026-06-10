import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Device, LldpNeighbor, Site, SiteSubnet, VpnTunnel
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

    edges: list[TopologyEdge] = []
    device_ids = {device.id for device in devices}

    # LLDP-Links: nur zwischen bekannten Geräten (remote_system_name == hostname), dedupliziert.
    seen: set[tuple[str, str]] = set()
    lldp = (await session.execute(select(LldpNeighbor))).scalars().all()
    for neighbor in lldp:
        if neighbor.local_device_id not in device_ids or not neighbor.remote_system_name:
            continue
        remote = by_hostname.get(neighbor.remote_system_name)
        if remote is None:
            continue
        local_id, remote_id = str(neighbor.local_device_id), str(remote.id)
        if local_id == remote_id:
            continue
        pair = (local_id, remote_id) if local_id < remote_id else (remote_id, local_id)
        if pair in seen:
            continue
        seen.add(pair)
        edges.append(
            TopologyEdge(
                source=f"device:{neighbor.local_device_id}",
                target=f"device:{remote.id}",
                type="lldp",
            )
        )

    # VPN-Kanten gehen von der FIREWALL aus (nicht Site↔Site): Tunnel, dessen Remote-
    # Selektoren ein Segment von Site B überlappen → Kante device:firewall → site:B.
    device_site = {d.id: d.site_id for d in devices}
    seen_vpn: set[tuple[str, str, str]] = set()
    for tunnel in (await session.execute(select(VpnTunnel))).scalars():
        if not tunnel.relevant:
            continue
        local_site = device_site.get(tunnel.device_id)
        if tunnel.device_id not in device_site:
            continue
        for site in sites:
            if site.id == local_site:
                continue
            site_cidrs = subnets_by_site.get(site.id, [])
            if not site_cidrs:
                continue
            if not subnet_overlaps_site([str(s) for s in tunnel.remote_subnets], site_cidrs):
                continue
            key = (str(tunnel.device_id), str(site.id), tunnel.name)
            if key in seen_vpn:
                continue
            seen_vpn.add(key)
            edges.append(
                TopologyEdge(
                    source=f"device:{tunnel.device_id}",
                    target=f"site:{site.id}",
                    type="vpn",
                    label=tunnel.name,
                    up=tunnel.is_up,
                )
            )

    return Topology(nodes=nodes, edges=edges)
