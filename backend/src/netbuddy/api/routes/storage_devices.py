"""Kategorie „Storage" — filter-/sortierbare Liste (CRUD).

Befüllt netzweit über :mod:`netbuddy.services.server_inventory` (Array-APIs, vCenter-Datastores,
NAS). Enthält nutzbaren und belegten Speicher, Disks, Anbindungen und Garantie.
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select

from netbuddy.api.deps import SessionDep
from netbuddy.db.models import (
    HardwareStatus,
    PhysicalServer,
    Site,
    StorageDevice,
    StorageLink,
    StorageType,
    VirtualServer,
    WarrantyStatus,
)

router = APIRouter(prefix="/storage-devices", tags=["storage-devices"])


class StorageDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("mgmt_ip", "reachable_ip", mode="before")
    @classmethod
    def _ip_str(cls, v: object) -> str | None:
        return str(v) if v is not None else None

    id: uuid.UUID
    name: str
    dns_name: str | None
    site_id: uuid.UUID | None
    site_name: str | None = None
    storage_type: StorageType
    vendor: str | None
    model: str | None
    service_tag: str | None
    firmware: str | None
    hardware_status: HardwareStatus
    hardware_detail: str | None
    disk_count: int | None
    disks: list[dict[str, object]]
    capacity_raw_gb: int | None
    capacity_usable_gb: int | None
    capacity_used_gb: int | None
    mgmt_ip: str | None
    reachable_ip: str | None = None
    ip_addresses: list[str]
    protocols: list[str]
    connections: list[dict[str, object]]
    warranty_provider: str | None
    warranty_start: date | None
    warranty_end: date | None
    warranty_status: WarrantyStatus
    warranty_checked_at: datetime | None
    source: str | None
    last_seen: datetime | None
    notes: str | None
    created_at: datetime


class StorageDeviceCreate(BaseModel):
    name: str
    storage_type: StorageType = StorageType.UNKNOWN
    site_id: uuid.UUID | None = None
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    mgmt_ip: str | None = None
    notes: str | None = None


class StorageDeviceUpdate(BaseModel):
    """Teil-Update; nur gesetzte Felder werden geändert."""

    name: str | None = None
    dns_name: str | None = None
    site_id: uuid.UUID | None = None
    storage_type: StorageType | None = None
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    firmware: str | None = None
    hardware_status: HardwareStatus | None = None
    hardware_detail: str | None = None
    disk_count: int | None = None
    capacity_raw_gb: int | None = None
    capacity_usable_gb: int | None = None
    capacity_used_gb: int | None = None
    mgmt_ip: str | None = None
    reachable_ip: str | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_status: WarrantyStatus | None = None
    notes: str | None = None


async def _site_names(session: SessionDep) -> dict[uuid.UUID, str]:
    return {sid: name for sid, name in (await session.execute(select(Site.id, Site.name))).all()}


def _read(row: StorageDevice, names: dict[uuid.UUID, str]) -> StorageDeviceRead:
    out = StorageDeviceRead.model_validate(row)
    out.mgmt_ip = str(row.mgmt_ip) if row.mgmt_ip else None
    out.reachable_ip = str(row.reachable_ip) if row.reachable_ip else None
    out.site_name = names.get(row.site_id) if row.site_id else None
    return out


async def _get_or_404(session: SessionDep, row_id: uuid.UUID) -> StorageDevice:
    row = await session.get(StorageDevice, row_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storage nicht gefunden")
    return row


@router.get("", response_model=list[StorageDeviceRead])
async def list_storage_devices(session: SessionDep) -> list[StorageDeviceRead]:
    rows = (
        (
            await session.execute(
                select(StorageDevice)
                .where(StorageDevice.deleted_at.is_(None))
                .order_by(StorageDevice.name)
            )
        )
        .scalars()
        .all()
    )
    names = await _site_names(session)
    return [_read(r, names) for r in rows]


@router.post("", response_model=StorageDeviceRead, status_code=status.HTTP_201_CREATED)
async def create_storage_device(
    body: StorageDeviceCreate, session: SessionDep
) -> StorageDeviceRead:
    row = StorageDevice(**body.model_dump(), source="manual")
    session.add(row)
    await session.flush()
    return _read(row, await _site_names(session))


@router.patch("/{row_id}", response_model=StorageDeviceRead)
async def update_storage_device(
    row_id: uuid.UUID, body: StorageDeviceUpdate, session: SessionDep
) -> StorageDeviceRead:
    row = await _get_or_404(session, row_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    return _read(row, await _site_names(session))


@router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage_device(row_id: uuid.UUID, session: SessionDep) -> None:
    row = await _get_or_404(session, row_id)
    row.deleted_at = datetime.now().astimezone()


# --- Baumansicht: Array/NAS -> LUN/Volume -> Anbindung (Hosts/VMs) ---------------------------


class StorageAttachment(BaseModel):
    kind: str  # "vm" | "physical"
    name: str
    protocol: str | None = None


class StorageChild(BaseModel):
    id: uuid.UUID
    name: str
    storage_type: StorageType
    capacity_usable_gb: int | None
    capacity_used_gb: int | None
    datastore_type: str | None = None
    attachments: list[StorageAttachment] = []


class StorageTreeNode(BaseModel):
    key: str
    name: str
    vendor: str | None = None
    model: str | None = None
    site_name: str | None = None
    storage_type: StorageType
    mgmt_ip: str | None = None
    reachable_ip: str | None = None
    service_tag: str | None = None
    capacity_usable_gb: int | None = None
    capacity_used_gb: int | None = None
    is_group: bool = False
    children: list[StorageChild] = []


def _array_key(name: str) -> tuple[str, str]:
    """(Schlüssel, Anzeigename) des zugehörigen Arrays aus einem LUN-/Datastore-Namen ableiten."""
    low = name.lower()
    if "dorado" in low or "sanhuawei" in low:
        return "huawei-dorado", "Huawei Dorado"
    if "synolog" in low or "synsan" in low or low.startswith("syn"):
        return "synology", "Synology"
    if "flashstore" in low:
        return "flashstore", "Flashstore"
    if low.startswith(("nfsb", "stob", "s00_nfs", "s00nfs")) or "nfs" in low or "-sto-" in low:
        return "netapp", "NetApp"
    return "lun-sonstige", "Sonstige LUNs/Datastores"


@router.get("/tree", response_model=list[StorageTreeNode])
async def storage_tree(session: SessionDep) -> list[StorageTreeNode]:
    """Array/NAS als Wurzeln, darunter die LUNs/Volumes (vCenter-Datastores) und ihre Anbindung.

    Echte Arrays/NAS (aus Passwordstate/SNMP) stehen mit Hersteller/Modell/Grösse oben; die
    vCenter-LUNs werden über Namensmuster zu Array-Gruppen zusammengefasst und tragen die
    angebundenen Hosts/VMs (aus den Storage-Links).
    """
    names = await _site_names(session)
    devices = (
        (await session.execute(select(StorageDevice).where(StorageDevice.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    links = (await session.execute(select(StorageLink))).scalars().all()
    vm_rows = (await session.execute(select(VirtualServer.id, VirtualServer.name))).all()
    ph_rows = (await session.execute(select(PhysicalServer.id, PhysicalServer.hostname))).all()
    vm_names: dict[uuid.UUID, str] = {r[0]: r[1] for r in vm_rows}
    ph_names: dict[uuid.UUID, str] = {r[0]: r[1] for r in ph_rows}
    attach: dict[uuid.UUID, list[StorageAttachment]] = {}
    for link in links:
        if link.virtual_server_id and link.virtual_server_id in vm_names:
            attach.setdefault(link.storage_device_id, []).append(
                StorageAttachment(
                    kind="vm", name=vm_names[link.virtual_server_id], protocol=link.protocol
                )
            )
        elif link.physical_server_id and link.physical_server_id in ph_names:
            attach.setdefault(link.storage_device_id, []).append(
                StorageAttachment(
                    kind="physical",
                    name=ph_names[link.physical_server_id],
                    protocol=link.protocol,
                )
            )

    arrays = [d for d in devices if d.source != "vcenter-datastore"]
    datastores = [d for d in devices if d.source == "vcenter-datastore"]

    # Arrays nach allen bekannten Adressen/Namen indizieren (für NFS-Host-Auflösung)
    array_by_addr: dict[str, StorageDevice] = {}
    for a in arrays:
        for ip in (a.mgmt_ip, a.reachable_ip, *(a.ip_addresses or [])):
            if ip:
                array_by_addr[str(ip)] = a
        if a.dns_name:
            array_by_addr[a.dns_name.lower()] = a

    roots: list[StorageTreeNode] = []
    node_for_array: dict[uuid.UUID, StorageTreeNode] = {}
    groups: dict[str, StorageTreeNode] = {}

    def array_node(a: StorageDevice) -> StorageTreeNode:
        node = node_for_array.get(a.id)
        if node is None:
            node = StorageTreeNode(
                key=str(a.id),
                name=a.name,
                vendor=a.vendor,
                model=a.model,
                site_name=names.get(a.site_id) if a.site_id else None,
                storage_type=a.storage_type,
                mgmt_ip=str(a.mgmt_ip) if a.mgmt_ip else None,
                reachable_ip=str(a.reachable_ip) if a.reachable_ip else None,
                service_tag=a.service_tag,
                capacity_usable_gb=a.capacity_usable_gb,
                capacity_used_gb=a.capacity_used_gb,
                children=[],
            )
            node_for_array[a.id] = node
            roots.append(node)
        return node

    def child_of(d: StorageDevice) -> StorageChild:
        ex = d.extra or {}
        label = d.name
        if ex.get("nfs_host"):
            label = f"{d.name}  ({ex.get('nfs_host')}:{ex.get('nfs_path') or ''})"
        return StorageChild(
            id=d.id,
            name=label,
            storage_type=d.storage_type,
            capacity_usable_gb=d.capacity_usable_gb,
            capacity_used_gb=d.capacity_used_gb,
            datastore_type=str(ex.get("datastore_type") or "") or None,
            attachments=attach.get(d.id, []),
        )

    def group_node(
        gkey: str, name: str, site_id: uuid.UUID | None, mgmt: str | None
    ) -> StorageTreeNode:
        existing = groups.get(gkey)
        if existing is not None:
            return existing
        g = StorageTreeNode(
            key=gkey,
            name=name,
            site_name=names.get(site_id) if site_id else None,
            storage_type=StorageType.ENTERPRISE_ARRAY,
            mgmt_ip=mgmt,
            is_group=True,
            capacity_usable_gb=0,
            capacity_used_gb=0,
            children=[],
        )
        groups[gkey] = g
        roots.append(g)
        return g

    # 1) echte Arrays als Wurzeln (auch ohne Kinder sichtbar)
    for a in arrays:
        array_node(a)

    # 2) Datastores/LUNs ihrem Array über die Anbindung zuordnen
    for d in sorted(datastores, key=lambda x: x.name.lower()):
        ex = d.extra or {}
        nfs_host = ex.get("nfs_host")
        target = None
        if nfs_host:
            target = array_by_addr.get(str(nfs_host)) or array_by_addr.get(str(nfs_host).lower())
        if target is not None:
            node = array_node(target)
        elif nfs_host:
            node = group_node(f"nfs:{nfs_host}", f"NFS {nfs_host}", d.site_id, str(nfs_host))
        else:
            node = group_node(
                f"vmfs:{d.site_id}", "Block-LUNs (VMFS, Array unbekannt)", d.site_id, None
            )
        node.children.append(child_of(d))
        if node.is_group:
            node.capacity_usable_gb = (node.capacity_usable_gb or 0) + (d.capacity_usable_gb or 0)
            node.capacity_used_gb = (node.capacity_used_gb or 0) + (d.capacity_used_gb or 0)

    return sorted(roots, key=lambda n: (n.site_name or "", n.name.lower()))
