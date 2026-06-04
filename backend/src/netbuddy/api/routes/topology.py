from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import Device, LldpNeighbor, Site

router = APIRouter(prefix="/topology", tags=["topology"])


class TopologyNode(BaseModel):
    id: str  # z.B. "device:<uuid>" / "site:<uuid>"
    label: str
    type: str  # "site" | "switch" | "firewall" | "router" | "ap" | "other"
    site_id: str | None = None


class TopologyEdge(BaseModel):
    source: str
    target: str
    type: str  # "member" (Gerät→Standort) | "lldp" (Gerät↔Gerät)


class Topology(BaseModel):
    """Graph für das GUI: Knoten (Standorte + Geräte) und Kanten (Zugehörigkeit + LLDP-Links).

    Die `type`-Felder dienen dem Frontend als Layer (ein-/ausblendbar).
    """

    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


@router.get("", response_model=Topology)
async def get_topology(session: SessionDep) -> Topology:
    """Liefert den Topologie-Graphen (Standorte, Geräte, LLDP-Verbindungen)."""
    sites = (await session.execute(select(Site).where(Site.deleted_at.is_(None)))).scalars().all()
    devices = (
        (await session.execute(select(Device).where(Device.deleted_at.is_(None)))).scalars().all()
    )

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
                site_id=f"site:{device.site_id}" if device.site_id else None,
            )
        )
        by_hostname[device.hostname] = device

    edges: list[TopologyEdge] = []
    device_ids = {device.id for device in devices}
    for device in devices:
        if device.site_id is not None:
            edges.append(
                TopologyEdge(
                    source=f"device:{device.id}", target=f"site:{device.site_id}", type="member"
                )
            )

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

    return Topology(nodes=nodes, edges=edges)
