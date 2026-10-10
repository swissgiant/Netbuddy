"""Storage-Anreicherung über die Hersteller-APIs (read + optional SNMP aktivieren).

Liest Modell, Seriennummer, Kapazität (nutzbar/belegt) und Disks direkt von den Arrays/NAS und
kann die SNMP-v2c-Read-Community ``PRTG`` setzen (für PRTG-Monitoring). Admin-Zugänge kommen aus
Passwordstate (Storage-Listen, nach IP indiziert), der Zugriff läuft über die erreichbare Adresse
(``reachable_ip`` via Cato-NAT, sonst ``mgmt_ip``). Unterstützt: Synology DSM, NetApp ONTAP REST.
Nicht erreichbare oder unbekannte Geräte bleiben unverändert.
"""

import asyncio
import re
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Credential, HardwareStatus, StorageDevice

_IP = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_SKIP_CRED = re.compile(r"monitor|veeam|backup|encryption|peer|\bsvc\b|chap", re.IGNORECASE)
_SNMP_COMMUNITY = "PRTG"


class StorageApiSummary(BaseModel):
    synology_enriched: int = 0
    netapp_enriched: int = 0
    snmp_enabled: int = 0
    community_changed: list[str] = []
    failed: list[str] = []
    skipped_no_cred: list[str] = []


def _target(dev: StorageDevice) -> str | None:
    if dev.reachable_ip:
        return str(dev.reachable_ip)
    return str(dev.mgmt_ip) if dev.mgmt_ip else None


async def _cred_index(session: AsyncSession) -> dict[str, tuple[str, str]]:
    """Admin-Logins aus den Passwordstate-Storage-Listen, nach (realer) IP: ip -> (user, pw)."""
    from netbuddy.services.passwordstate import PasswordstateApi

    pw = (
        (
            await session.execute(
                select(Credential).where(
                    Credential.name == "Passwordstate", Credential.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .first()
    )
    index: dict[str, tuple[str, str]] = {}
    if pw is None:
        return index
    async with PasswordstateApi(pw) as api:
        for lst in await api.fetch_lists():
            if not re.search(
                r"synolog|storage|netapp|qnap", f"{lst.name} {lst.tree_path or ''}", re.I
            ):
                continue
            try:
                entries = await api.fetch_list(lst.list_id)
            except Exception:
                continue
            for e in entries:
                blob = f"{e.title} {e.username or ''}"
                if _SKIP_CRED.search(blob) or not e.username or not e.password:
                    continue
                ip = None
                for field in (e.hostname, e.url, e.description, e.notes):
                    if field and (m := _IP.search(field)):
                        ip = m.group(1)
                        break
                if ip and ip not in index:
                    index[ip] = (e.username, e.password)
    return index


def _gb(value: Any) -> int | None:
    try:
        return int(int(value) / (1024**3))
    except (TypeError, ValueError):
        return None


async def _synology(client: httpx.AsyncClient, base: str, user: str, pw: str) -> dict[str, Any]:
    auth = await client.get(
        f"{base}/webapi/auth.cgi",
        params={
            "api": "SYNO.API.Auth",
            "version": "3",
            "method": "login",
            "account": user,
            "passwd": pw,
            "session": "NetBuddy",
            "format": "sid",
        },
    )
    sid = auth.json().get("data", {}).get("sid")
    if not sid:
        raise RuntimeError("Synology-Login fehlgeschlagen")
    out: dict[str, Any] = {}
    try:
        sysr = await client.get(
            f"{base}/webapi/entry.cgi",
            params={"api": "SYNO.Core.System", "version": "1", "method": "info", "_sid": sid},
        )
        data = sysr.json().get("data", {})
        out["model"] = data.get("model")
        out["serial"] = data.get("serial")
        out["firmware"] = data.get("firmware_ver") or data.get("version_string")
        stor = await client.get(
            f"{base}/webapi/entry.cgi",
            params={
                "api": "SYNO.Storage.CGI.Storage",
                "version": "1",
                "method": "load_info",
                "_sid": sid,
            },
        )
        sd = stor.json().get("data", {})
        vols = sd.get("volumes", []) or []
        total = sum(int(v.get("size", {}).get("total", 0)) for v in vols)
        used = sum(int(v.get("size", {}).get("used", 0)) for v in vols)
        out["cap_usable_gb"] = _gb(total) if total else None
        out["cap_used_gb"] = _gb(used) if used else None
        out["disk_count"] = len(sd.get("disks", []) or [])
        out["disks"] = [
            {
                "id": d.get("id"),
                "model": d.get("model"),
                "size_gb": _gb(d.get("size_total")),
                "status": d.get("status"),
            }
            for d in (sd.get("disks", []) or [])
        ]
    finally:
        await client.get(
            f"{base}/webapi/auth.cgi",
            params={
                "api": "SYNO.API.Auth",
                "version": "3",
                "method": "logout",
                "session": "NetBuddy",
                "_sid": sid,
            },
        )
    return out


async def _netapp(client: httpx.AsyncClient, base: str, user: str, pw: str) -> dict[str, Any]:
    auth = (user, pw)
    out: dict[str, Any] = {}
    cl = await client.get(
        f"{base}/api/cluster", auth=auth, params={"fields": "name,version,serial_number"}
    )
    cj = cl.json()
    out["model"] = "NetApp ONTAP"
    out["firmware"] = (cj.get("version") or {}).get("full")
    out["serial"] = cj.get("serial_number")
    nodes = await client.get(
        f"{base}/api/cluster/nodes", auth=auth, params={"fields": "model,serial_number"}
    )
    recs = nodes.json().get("records", [])
    if recs:
        out["model"] = recs[0].get("model") or out["model"]
        out["serial"] = out["serial"] or recs[0].get("serial_number")
    aggr = await client.get(f"{base}/api/storage/aggregates", auth=auth, params={"fields": "space"})
    total = used = 0
    for a in aggr.json().get("records", []):
        blk = (a.get("space") or {}).get("block_storage") or {}
        total += int(blk.get("size", 0) or 0)
        used += int(blk.get("used", 0) or 0)
    out["cap_usable_gb"] = _gb(total) if total else None
    out["cap_used_gb"] = _gb(used) if used else None
    disks = await client.get(
        f"{base}/api/storage/disks", auth=auth, params={"fields": "model,state"}
    )
    drecs = disks.json().get("records", [])
    out["disk_count"] = len(drecs)
    return out


async def _enable_snmp_synology(
    client: httpx.AsyncClient, base: str, user: str, pw: str
) -> tuple[bool, str | None]:
    """SNMP v1/v2c mit Community PRTG aktivieren (DSM). Gibt (geaendert, alte_community) zurueck."""
    auth = await client.get(
        f"{base}/webapi/entry.cgi",
        params={
            "api": "SYNO.API.Auth",
            "version": "7",
            "method": "login",
            "account": user,
            "passwd": pw,
            "session": "NetBuddy",
            "format": "sid",
        },
    )
    sid = auth.json().get("data", {}).get("sid")
    if not sid:
        return False, None
    try:
        g = await client.get(
            f"{base}/webapi/entry.cgi",
            params={"api": "SYNO.Core.SNMP", "version": "1", "method": "get", "_sid": sid},
        )
        cur = g.json().get("data", {})
        old = cur.get("rocommunity")
        if cur.get("enable_snmp") and cur.get("enable_snmp_v1v2") and old == _SNMP_COMMUNITY:
            return False, old  # schon korrekt
        r = await client.get(
            f"{base}/webapi/entry.cgi",
            params={
                "api": "SYNO.Core.SNMP",
                "version": "1",
                "method": "set",
                "_sid": sid,
                "enable_snmp": "true",
                "enable_snmp_v1v2": "true",
                "rocommunity": _SNMP_COMMUNITY,
                "enable_snmp_v3": "true" if cur.get("enable_snmp_v3") else "false",
                "contact": cur.get("contact", ""),
                "location": cur.get("location", ""),
            },
        )
        return bool(r.json().get("success")), old
    except Exception:
        return False, None
    finally:
        await client.get(
            f"{base}/webapi/entry.cgi",
            params={
                "api": "SYNO.API.Auth",
                "version": "7",
                "method": "logout",
                "session": "NetBuddy",
                "_sid": sid,
            },
        )


async def _enable_snmp_netapp(
    client: httpx.AsyncClient, base: str, user: str, pw: str
) -> tuple[bool, str | None]:
    """ONTAP: SNMP aktivieren + RO-Community PRTG (via privatem CLI-Passthrough). Best effort."""
    auth = (user, pw)
    try:
        await client.patch(f"{base}/api/support/snmp", auth=auth, json={"enabled": True})
    except Exception:
        pass
    try:
        # vorhandene Communities lesen
        existing = await client.get(
            f"{base}/api/private/cli/system/snmp/community",
            auth=auth,
            params={"fields": "community_name,type"},
        )
        names = [
            r.get("community_name")
            for r in existing.json().get("records", [])
            if r.get("type") == "ro"
        ]
        if _SNMP_COMMUNITY in names:
            return False, (names[0] if names else None)
        r = await client.post(
            f"{base}/api/private/cli/system/snmp/community",
            auth=auth,
            json={"type": "ro", "community_name": _SNMP_COMMUNITY},
        )
        return r.status_code < 300, (names[0] if names else None)
    except Exception:
        return False, None


def _apply(dev: StorageDevice, info: dict[str, Any], vendor: str, used_serials: set[str]) -> None:
    if info.get("model"):
        dev.model = str(info["model"])[:120]
    serial = str(info["serial"])[:128] if info.get("serial") else None
    if serial and serial not in used_serials:
        dev.service_tag = serial
        used_serials.add(serial)
    elif serial:
        # gleiche Serial (z.B. NetApp-Cluster-Node) -> nur im extra vermerken, Unique-Index wahren
        dev.extra = {**(dev.extra or {}), "serial_shared": serial}
    if info.get("firmware"):
        dev.firmware = str(info["firmware"])[:128]
    if info.get("cap_usable_gb"):
        dev.capacity_usable_gb = info["cap_usable_gb"]
    if info.get("cap_used_gb") is not None:
        dev.capacity_used_gb = info["cap_used_gb"]
    if info.get("disk_count"):
        dev.disk_count = info["disk_count"]
    if info.get("disks"):
        dev.disks = info["disks"]
    if info.get("ips"):
        merged = sorted(set((dev.ip_addresses or []) + list(info["ips"])))
        dev.ip_addresses = merged
    if not dev.vendor:
        dev.vendor = vendor
    dev.hardware_status = HardwareStatus.OK


async def enrich_storage_apis(
    session: AsyncSession, *, enable_snmp: bool = False
) -> StorageApiSummary:
    summary = StorageApiSummary()
    creds = await _cred_index(session)
    used_serials: set[str] = {
        st
        for st in (
            await session.execute(
                select(StorageDevice.service_tag).where(StorageDevice.service_tag.isnot(None))
            )
        )
        .scalars()
        .all()
        if st
    }
    devices = (
        (
            await session.execute(
                select(StorageDevice).where(
                    StorageDevice.deleted_at.is_(None), StorageDevice.mgmt_ip.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )
    async with httpx.AsyncClient(verify=False, timeout=6.0) as client:
        sem = asyncio.Semaphore(12)

        async def handle(dev: StorageDevice) -> None:
            ip = _target(dev)
            if not ip:
                return
            cred = creds.get(str(dev.mgmt_ip)) or creds.get(ip)
            if not cred:
                summary.skipped_no_cred.append(dev.name)
                return
            user, pw = cred
            vendor = (dev.vendor or "").lower()
            name = dev.name.lower()
            async with sem:
                try:
                    if vendor == "synology" or await _port_open(ip, 5001):
                        info = await _synology(client, f"https://{ip}:5001", user, pw)
                        _apply(dev, info, "Synology", used_serials)
                        summary.synology_enriched += 1
                        if enable_snmp:
                            ok, old = await _enable_snmp_synology(
                                client, f"https://{ip}:5001", user, pw
                            )
                            if ok:
                                summary.snmp_enabled += 1
                                if old and old != _SNMP_COMMUNITY:
                                    summary.community_changed.append(f"{dev.name}: {old}->PRTG")
                    elif (
                        vendor == "netapp" or "netapp" in name or "sto" in name
                    ) and await _port_open(ip, 443):
                        info = await _netapp(client, f"https://{ip}", user, pw)
                        _apply(dev, info, "NetApp", used_serials)
                        summary.netapp_enriched += 1
                        if enable_snmp:
                            ok, old = await _enable_snmp_netapp(client, f"https://{ip}", user, pw)
                            if ok:
                                summary.snmp_enabled += 1
                                if old and old != _SNMP_COMMUNITY:
                                    summary.community_changed.append(f"{dev.name}: {old}->PRTG")
                except Exception as exc:
                    summary.failed.append(f"{dev.name}: {str(exc)[:80]}")

        await asyncio.gather(*[handle(d) for d in devices])
    await session.commit()
    return summary


async def _port_open(ip: str, port: int) -> bool:
    import asyncio

    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), 2.0)
        writer.close()
        return True
    except Exception:
        return False
