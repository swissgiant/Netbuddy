"""vCenter-Inventar (read-only): virtuelle Server, physische ESXi-Hosts und Storage-Datastores.

Befüllt die drei Kategorien aus jedem hinterlegten vCenter. Ein vCenter ist eine
:class:`~netbuddy.db.models.Credential` mit ``extra.kind == "vcenter"`` (``base_url`` = Host/IP,
``username``/``password`` = Login). So lassen sich netzweit mehrere vCenter (BLS, Belimed, Steelco)
anbinden, indem man je eine Credential anlegt.

pyvmomi ist synchron — der Abruf läuft über :func:`asyncio.to_thread`, der Upsert ist async.
Dedupe: VMs über ``instanceUuid``, Hosts über Service-Tag (sonst Hostname), Storage über den
Datastore-Namen. Nichts wird gelöscht (ausser den eigenen Storage-Links, die idempotent neu
gesetzt werden).
"""

import asyncio
import ssl
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    Credential,
    HardwareStatus,
    PhysicalServer,
    PowerState,
    ServerKind,
    ServerRole,
    Site,
    StorageDevice,
    StorageLink,
    StorageType,
    Vcenter,
    VirtualServer,
)

_HW = {
    "green": HardwareStatus.OK,
    "yellow": HardwareStatus.WARNING,
    "red": HardwareStatus.CRITICAL,
    "gray": HardwareStatus.UNKNOWN,
}
_POW = {
    "poweredOn": PowerState.ON,
    "poweredOff": PowerState.OFF,
    "suspended": PowerState.SUSPENDED,
}

# vCenter-Datacenter-Codes -> NetBuddy-Site-Namen (Credential.extra["site_map"] ueberschreibt).
_DC_SITE_ALIAS = {
    "BHQ": "B-HQ",
    "BSAG": "B-SAG",
    "BSIG": "B-SI",
    "BSI": "B-SI",
    "BDEM": "B-DE",
    "BDE": "B-DE",
    "BUSL": "B-US",
    "BUS": "B-US",
}


def _resolve_site(sites: dict[str, Any], dc: str, site_map: dict[str, str]) -> Any:
    name = site_map.get(dc) or _DC_SITE_ALIAS.get(dc, dc)
    return sites.get(name) or sites.get(dc)


class VcHost(BaseModel):
    dc: str
    name: str
    vendor: str | None = None
    model: str | None = None
    service_tag: str | None = None
    cpu_model: str | None = None
    cpu_sockets: int | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    ram_mb: int | None = None
    mgmt_ip: str | None = None
    status: str | None = None
    os_name: str | None = None
    os_version: str | None = None


class VcVm(BaseModel):
    dc: str
    name: str
    vm_uuid: str | None = None
    power: str = "unknown"
    vcpu: int | None = None
    ram_mb: int | None = None
    cluster: str | None = None
    esxi_host: str | None = None
    guest_os: str | None = None
    tools: str | None = None
    disk_count: int | None = None
    disk_total_gb: int | None = None
    disks: list[dict[str, Any]] = []
    datastores: list[str] = []
    ips: list[str] = []
    networks: list[str] = []


class VcDatastore(BaseModel):
    dc: str
    name: str
    type: str
    cap_gb: int
    free_gb: int
    hosts: int
    local: bool


class VcCluster(BaseModel):
    datacenter: str
    name: str
    hosts: list[str] = []
    host_count: int = 0


class VcSnapshot(BaseModel):
    vcenter: str
    about: dict[str, str | None] = {}
    hosts: list[VcHost] = []
    vms: list[VcVm] = []
    datastores: list[VcDatastore] = []
    clusters: list[VcCluster] = []


class VcSyncSummary(BaseModel):
    vcenter: str
    physical_created: int = 0
    physical_updated: int = 0
    virtual_created: int = 0
    virtual_updated: int = 0
    storage_created: int = 0
    storage_updated: int = 0
    links: int = 0
    error: str | None = None


def _host_mgmt_ip(host: Any) -> str | None:
    try:
        for vnic in host.config.network.vnic:
            ip = vnic.spec.ip.ipAddress
            if ip and not ip.startswith("169.254"):
                return str(ip)
    except Exception:
        pass
    return None


def _collect(host: str, user: str, password: str) -> VcSnapshot:
    """Synchroner Abruf (pyvmomi). Läuft via asyncio.to_thread."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    si = SmartConnect(host=host, user=user, pwd=password, sslContext=ctx)  # type: ignore[no-untyped-call]
    try:
        content = si.RetrieveContent()
        snap = VcSnapshot(vcenter=host)
        about = content.about
        snap.about = {
            "version": about.version,
            "build": about.build,
            "full_name": about.fullName,
            "api_type": about.apiType,
        }
        for dc in content.rootFolder.childEntity:
            if not isinstance(dc, vim.Datacenter):
                continue
            _collect_hosts(content, dc, snap)
            _collect_vms(content, dc, snap)
            _collect_datastores(content, dc, snap)
            _collect_clusters(content, dc, snap)
        return snap
    finally:
        Disconnect(si)  # type: ignore[no-untyped-call]


def _collect_hosts(content: Any, dc: Any, snap: VcSnapshot) -> None:
    view = content.viewManager.CreateContainerView(dc.hostFolder, [vim.HostSystem], True)
    try:
        for h in view.view:
            hwi = h.hardware.systemInfo
            tag = next(
                (
                    i.identifierValue
                    for i in (hwi.otherIdentifyingInfo or [])
                    if str(i.identifierType.key) == "ServiceTag"
                ),
                None,
            )
            cpu = h.hardware.cpuInfo
            pkg = h.hardware.cpuPkg[0].description if h.hardware.cpuPkg else None
            snap.hosts.append(
                VcHost(
                    dc=dc.name,
                    name=h.name,
                    vendor=hwi.vendor,
                    model=hwi.model,
                    service_tag=tag,
                    cpu_model=pkg,
                    cpu_sockets=cpu.numCpuPackages,
                    cpu_cores=cpu.numCpuCores,
                    cpu_threads=cpu.numCpuThreads,
                    ram_mb=int(h.hardware.memorySize / 1048576),
                    mgmt_ip=_host_mgmt_ip(h),
                    status=str(h.overallStatus),
                    os_name=h.config.product.name if h.config else None,
                    os_version=h.config.product.version if h.config else None,
                )
            )
    finally:
        view.Destroy()


def _collect_vms(content: Any, dc: Any, snap: VcSnapshot) -> None:
    view = content.viewManager.CreateContainerView(dc.vmFolder, [vim.VirtualMachine], True)
    try:
        for vm in view.view:
            cfg = vm.config
            if cfg is None or cfg.template:
                continue
            disks: list[dict[str, Any]] = []
            dstores: set[str] = set()
            nets: set[str] = set()
            total = 0
            devices: list[Any] = cfg.hardware.device or []
            for dev in devices:
                if isinstance(dev, vim.vm.device.VirtualDisk):
                    gb = int(dev.capacityInKB / 1048576)
                    total += gb
                    dsn = None
                    try:
                        dsn = dev.backing.datastore.name  # type: ignore[union-attr]
                    except Exception:
                        pass
                    if dsn:
                        dstores.add(dsn)
                    disks.append(
                        {"label": dev.deviceInfo.label, "size_gb": gb, "datastore": dsn}  # type: ignore[union-attr]
                    )
                elif isinstance(dev, vim.vm.device.VirtualEthernetCard):
                    name = getattr(dev.backing, "deviceName", None)
                    if name:
                        nets.add(name)
            ips: list[str] = []
            for nic in vm.guest.net or []:
                for ip in nic.ipAddress or []:
                    if ip and ":" not in ip and not ip.startswith("169.254"):
                        ips.append(ip)
            runtime = vm.summary.runtime
            host_name = runtime.host.name if runtime and runtime.host else None
            cluster = None
            try:
                cluster = runtime.host.parent.name
            except Exception:
                pass
            snap.vms.append(
                VcVm(
                    dc=dc.name,
                    name=cfg.name,
                    vm_uuid=cfg.instanceUuid,
                    power=str(runtime.powerState),
                    vcpu=cfg.hardware.numCPU,
                    ram_mb=cfg.hardware.memoryMB,
                    cluster=cluster,
                    esxi_host=host_name,
                    guest_os=cfg.guestFullName,
                    tools=str(vm.guest.toolsStatus) if vm.guest else None,
                    disk_count=len(disks),
                    disk_total_gb=total,
                    disks=disks,
                    datastores=sorted(dstores),
                    ips=sorted(set(ips)),
                    networks=sorted(nets),
                )
            )
    finally:
        view.Destroy()


def _collect_datastores(content: Any, dc: Any, snap: VcSnapshot) -> None:
    view = content.viewManager.CreateContainerView(dc.datastoreFolder, [vim.Datastore], True)
    try:
        for d in view.view:
            s = d.summary
            hosts = len(d.host or [])
            snap.datastores.append(
                VcDatastore(
                    dc=dc.name,
                    name=d.name,
                    type=s.type,
                    cap_gb=int(s.capacity / 1073741824),
                    free_gb=int(s.freeSpace / 1073741824),
                    hosts=hosts,
                    local=(s.type == "VMFS" and hosts <= 1),
                )
            )
    finally:
        view.Destroy()


def _collect_clusters(content: Any, dc: Any, snap: VcSnapshot) -> None:
    view = content.viewManager.CreateContainerView(
        dc.hostFolder, [vim.ClusterComputeResource], True
    )
    try:
        for c in view.view:
            hosts = [h.name for h in (c.host or [])]
            snap.clusters.append(
                VcCluster(datacenter=dc.name, name=c.name, hosts=hosts, host_count=len(hosts))
            )
    finally:
        view.Destroy()


def _storage_vendor(name: str) -> tuple[str | None, StorageType]:
    low = name.lower()
    if "dorado" in low or "huawei" in low:
        return "Huawei", StorageType.ENTERPRISE_ARRAY
    if "synolog" in low or "synsan" in low or low.startswith("syn"):
        return "Synology", StorageType.NAS
    return None, StorageType.ENTERPRISE_ARRAY


async def _sync_snapshot(
    session: AsyncSession, snap: VcSnapshot, site_map: dict[str, str]
) -> VcSyncSummary:
    summary = VcSyncSummary(vcenter=snap.vcenter)
    now = datetime.now().astimezone()
    sites = {s.name: s.id for s in (await session.execute(select(Site))).scalars().all()}

    host_pid: dict[str, Any] = {}
    for h in snap.hosts:
        found: PhysicalServer | None = None
        if h.service_tag:
            found = (
                (
                    await session.execute(
                        select(PhysicalServer).where(
                            PhysicalServer.service_tag == h.service_tag,
                            PhysicalServer.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
        if found is None:
            found = (
                (
                    await session.execute(
                        select(PhysicalServer).where(
                            PhysicalServer.hostname == h.name, PhysicalServer.deleted_at.is_(None)
                        )
                    )
                )
                .scalars()
                .first()
            )
        ps = found if found is not None else PhysicalServer(hostname=h.name)
        if found is None:
            session.add(ps)
        ps.hostname = h.name
        ps.dns_name = h.name
        ps.site_id = _resolve_site(sites, h.dc, site_map)
        ps.server_role = ServerRole.ESXI_HOST
        ps.vendor = h.vendor
        ps.model = h.model
        ps.service_tag = h.service_tag
        ps.cpu_model = h.cpu_model
        ps.cpu_sockets = h.cpu_sockets
        ps.cpu_cores = h.cpu_cores
        ps.cpu_threads = h.cpu_threads
        ps.ram_mb = h.ram_mb
        ps.os_name = h.os_name
        ps.os_version = h.os_version
        ps.mgmt_ip = h.mgmt_ip
        ps.hardware_status = _HW.get(h.status or "", HardwareStatus.UNKNOWN)
        ps.source = "vcenter"
        ps.last_seen = now
        await session.flush()
        host_pid[h.name] = ps.id
        summary.physical_created += int(found is None)
        summary.physical_updated += int(found is not None)

    ds_sid: dict[str, Any] = {}
    for x in snap.datastores:
        if x.local:
            continue
        vendor, stype = _storage_vendor(x.name)
        found_sd = (
            (
                await session.execute(
                    select(StorageDevice).where(
                        StorageDevice.name == x.name,
                        StorageDevice.source == "vcenter-datastore",
                        StorageDevice.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        sd = found_sd if found_sd is not None else StorageDevice(name=x.name)
        if found_sd is None:
            session.add(sd)
        sd.name = x.name
        sd.site_id = _resolve_site(sites, x.dc, site_map)
        sd.storage_type = stype
        sd.vendor = vendor
        sd.capacity_raw_gb = x.cap_gb
        sd.capacity_usable_gb = x.cap_gb
        sd.capacity_used_gb = x.cap_gb - x.free_gb
        sd.protocols = ["VMFS"]
        sd.source = "vcenter-datastore"
        sd.last_seen = now
        sd.extra = {"datastore_type": x.type, "hosts_mounted": x.hosts, "datacenter": x.dc}
        await session.flush()
        ds_sid[x.name] = sd.id
        summary.storage_created += int(found_sd is None)
        summary.storage_updated += int(found_sd is not None)

    await session.execute(
        text(
            "DELETE FROM storage_link WHERE extra->>'source'='vcenter' AND virtual_server_id IN "
            "(SELECT id FROM virtual_server WHERE vcenter=:vc)"
        ).bindparams(vc=snap.vcenter)
    )
    for v in snap.vms:
        found_vs: VirtualServer | None = None
        if v.vm_uuid:
            found_vs = (
                (
                    await session.execute(
                        select(VirtualServer).where(
                            VirtualServer.vm_uuid == v.vm_uuid, VirtualServer.deleted_at.is_(None)
                        )
                    )
                )
                .scalars()
                .first()
            )
        if found_vs is None:
            found_vs = (
                (
                    await session.execute(
                        select(VirtualServer).where(
                            VirtualServer.name == v.name,
                            VirtualServer.vcenter == snap.vcenter,
                            VirtualServer.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
        vs = found_vs if found_vs is not None else VirtualServer(name=v.name)
        if found_vs is None:
            session.add(vs)
        vs.name = v.name
        vs.site_id = _resolve_site(sites, v.dc, site_map)
        vs.power_state = _POW.get(v.power, PowerState.UNKNOWN)
        vs.vcpu = v.vcpu
        vs.ram_mb = v.ram_mb
        vs.cluster = v.cluster
        vs.esxi_host = v.esxi_host
        vs.physical_server_id = host_pid.get(v.esxi_host or "")
        vs.vcenter = snap.vcenter
        vs.guest_os = v.guest_os
        vs.vmware_tools = v.tools
        vs.disk_count = v.disk_count
        vs.disk_total_gb = v.disk_total_gb
        vs.disks = v.disks
        vs.datastores = v.datastores
        vs.ip_addresses = v.ips
        vs.networks = v.networks
        vs.vm_uuid = v.vm_uuid
        vs.source = "vcenter"
        vs.last_seen = now
        await session.flush()
        summary.virtual_created += int(found_vs is None)
        summary.virtual_updated += int(found_vs is not None)
        for dsn in v.datastores:
            if dsn in ds_sid:
                session.add(
                    StorageLink(
                        server_kind=ServerKind.VIRTUAL,
                        virtual_server_id=vs.id,
                        storage_device_id=ds_sid[dsn],
                        protocol="VMFS",
                        path=dsn,
                        extra={"source": "vcenter"},
                    )
                )
                summary.links += 1
    return summary


async def _upsert_vcenter(session: AsyncSession, snap: VcSnapshot, cred: Credential) -> None:
    now = datetime.now().astimezone()
    found = (
        (
            await session.execute(
                select(Vcenter).where(Vcenter.name == cred.name, Vcenter.deleted_at.is_(None))
            )
        )
        .scalars()
        .first()
    )
    vc = found if found is not None else Vcenter(name=cred.name)
    if found is None:
        session.add(vc)
    vm_by_cluster: dict[str, int] = {}
    for v in snap.vms:
        if v.cluster:
            vm_by_cluster[v.cluster] = vm_by_cluster.get(v.cluster, 0) + 1
    dcs = sorted(
        {h.dc for h in snap.hosts}
        | {v.dc for v in snap.vms}
        | {c.datacenter for c in snap.clusters}
    )
    vc.name = cred.name
    vc.host = snap.vcenter
    vc.version = snap.about.get("version")
    vc.build = snap.about.get("build")
    vc.full_name = snap.about.get("full_name")
    vc.api_type = snap.about.get("api_type")
    vc.credential_id = cred.id
    vc.datacenters = dcs
    vc.clusters = [
        {
            "datacenter": c.datacenter,
            "name": c.name,
            "host_count": c.host_count,
            "hosts": c.hosts,
            "vm_count": vm_by_cluster.get(c.name, 0),
        }
        for c in snap.clusters
    ]
    host_cluster: dict[str, str] = {}
    for c in snap.clusters:
        for hn in c.hosts:
            host_cluster[hn] = c.name
    vm_by_host: dict[str, int] = {}
    for v in snap.vms:
        if v.esxi_host:
            vm_by_host[v.esxi_host] = vm_by_host.get(v.esxi_host, 0) + 1
    vc.hosts = [
        {
            "datacenter": h.dc,
            "name": h.name,
            "cluster": host_cluster.get(h.name),
            "model": h.model,
            "cpu_cores": h.cpu_cores,
            "ram_mb": h.ram_mb,
            "status": h.status,
            "vm_count": vm_by_host.get(h.name, 0),
        }
        for h in snap.hosts
    ]
    vc.host_count = len(snap.hosts)
    vc.vm_count = len(snap.vms)
    vc.source = "vcenter"
    vc.last_seen = now


async def vcenter_credentials(session: AsyncSession) -> list[Credential]:
    rows = (
        (
            await session.execute(
                select(Credential).where(
                    Credential.deleted_at.is_(None),
                    Credential.extra["kind"].astext == "vcenter",
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def sync_vcenters(session: AsyncSession) -> list[VcSyncSummary]:
    """Alle hinterlegten vCenter abrufen und die drei Kategorien befüllen (read-only am vCenter)."""
    summaries: list[VcSyncSummary] = []
    for cred in await vcenter_credentials(session):
        host = (cred.base_url or "").replace("https://", "").replace("http://", "").strip("/")
        if not host or not cred.username or not cred.password:
            summaries.append(
                VcSyncSummary(vcenter=cred.name, error="base_url/username/password fehlt")
            )
            continue
        try:
            snap = await asyncio.to_thread(_collect, host, cred.username, cred.password)
            site_map = (cred.extra or {}).get("site_map") or {}
            summaries.append(await _sync_snapshot(session, snap, site_map))
            await _upsert_vcenter(session, snap, cred)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            summaries.append(VcSyncSummary(vcenter=cred.name, error=str(exc)[:300]))
    return summaries
