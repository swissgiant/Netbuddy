"""Storage-Anreicherung über die Hersteller-APIs (read + optional SNMP aktivieren).

Liest Modell, Seriennummer, Kapazität (nutzbar/belegt), Disks **und den echten Hardware-Status**
(defekte Platten, Status der Storage-Prozessoren/Node-Canister, PSU/Lüfter) direkt von den
Arrays/NAS und kann die SNMP-v2c-Read-Community ``PRTG`` setzen (für PRTG-Monitoring). Admin-Zugänge
kommen aus Passwordstate (Storage-Listen, nach IP indiziert), der Zugriff läuft über die erreichbare
Adresse (``reachable_ip`` via Cato-NAT, sonst ``mgmt_ip``). Unterstützt: Synology DSM,
NetApp ONTAP REST, IBM Storwize/SVC (SSH-CLI). Nicht erreichbare oder unbekannte Geräte bleiben
unverändert (Hardware-Status wird nicht blind auf OK gesetzt).
"""

import asyncio
import re
from collections import Counter
from datetime import UTC, datetime
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
    storwize_enriched: int = 0
    qnap_enriched: int = 0
    snmp_enabled: int = 0
    community_changed: list[str] = []
    health: list[str] = []  # "name: WARNING/CRITICAL - Detail"
    failed: list[str] = []
    skipped_no_cred: list[str] = []


def _target(dev: StorageDevice) -> str | None:
    if dev.reachable_ip:
        return str(dev.reachable_ip)
    return str(dev.mgmt_ip) if dev.mgmt_ip else None


_STORAGE_SOURCE = "passwordstate-storage"
_STORAGE_LIST_RE = re.compile(r"synolog|storage|netapp|qnap", re.IGNORECASE)


async def _cred_index(session: AsyncSession) -> dict[str, tuple[str, str]]:
    """IP -> (user, pw) für Storage-Logins.

    Primär aus den **NetBuddy-Credentials** (einmalig aus Passwordstate importiert,
    ``extra.source == "passwordstate-storage"``, nach ``extra.ip`` indiziert). Der Live-Abruf aus
    Passwordstate läuft nur noch als Fallback, falls noch nichts importiert wurde.
    """
    index: dict[str, tuple[str, str]] = {}
    rows = (
        await session.execute(select(Credential).where(Credential.deleted_at.is_(None)))
    ).scalars()
    for c in rows:
        ex = c.extra or {}
        ip = ex.get("ip")
        if ex.get("source") != _STORAGE_SOURCE or not ip or not c.username or not c.password:
            continue
        if _SKIP_CRED.search(f"{c.name} {c.username}"):
            continue
        index.setdefault(str(ip), (c.username, c.password))
    if index:
        return index
    return await _cred_index_live(session)


async def import_storage_credentials(
    session: AsyncSession, *, dry_run: bool = False
) -> "list[str]":
    """Zieht die Passwordstate-Storage-Listen einmal und legt sie als NetBuddy-Credentials ab
    (``source='passwordstate-storage'``), damit der Enrich-Lauf daraus statt live liest.
    Gibt eine kurze Zusammenfassung (angelegt/aktualisiert/übersprungen) zurück."""
    from netbuddy.services.passwordstate import PasswordstateApi, _first_ip, import_entries

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
    if pw is None:
        return ["Keine Passwordstate-Credential gefunden"]
    entries = []
    async with PasswordstateApi(pw) as api:
        for lst in await api.fetch_lists():
            if not _STORAGE_LIST_RE.search(f"{lst.name} {lst.tree_path or ''}"):
                continue
            try:
                entries += await api.fetch_list(lst.list_id)
            except Exception:
                continue
    # Nur die tatsächlich vom Enrich-Lauf genutzten Logins: mit IP + User + Passwort, kein
    # Monitoring-/Backup-/Veeam-Konto (gleiche Filter wie der Live-Index).
    usable = [
        e
        for e in entries
        if _first_ip(e)
        and e.username
        and e.password
        and not _SKIP_CRED.search(f"{e.title} {e.username}")
    ]
    summary = await import_entries(session, usable, dry_run=dry_run, source=_STORAGE_SOURCE)
    if not dry_run:
        await session.commit()
    return [
        f"angelegt={len(summary.created)}",
        f"aktualisiert={len(summary.updated)}",
        f"übersprungen={len(summary.skipped)}",
        *(f"NEU: {n}" for n in summary.created),
        *(f"SKIP: {n}" for n in summary.skipped),
    ]


async def _cred_index_live(session: AsyncSession) -> dict[str, tuple[str, str]]:
    """Fallback: Admin-Logins live aus den Passwordstate-Storage-Listen, nach IP."""
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


def _verdict(
    critical: list[str], warning: list[str], ok_summary: str
) -> tuple[HardwareStatus, str]:
    """Rollt Einzel-Befunde zu einem Gesamt-Hardware-Status + Detailtext zusammen."""
    if critical:
        return HardwareStatus.CRITICAL, "; ".join(critical + warning)[:1000]
    if warning:
        return HardwareStatus.WARNING, "; ".join(warning)[:1000]
    return HardwareStatus.OK, ok_summary[:1000]


def _parse_kv(output: str, sep: str = ":") -> dict[str, str]:
    """``key:value`` je Zeile (z.B. IBM ``lssystem -delim :``)."""
    out: dict[str, str] = {}
    for line in output.splitlines():
        if sep in line:
            key, val = line.split(sep, 1)
            out[key.strip()] = val.strip()
    return out


def _parse_delim(output: str, sep: str = ":") -> list[dict[str, str]]:
    """Kopfzeile + Datenzeilen (z.B. IBM ``lsdrive -delim :``) -> Liste von Dicts."""
    lines = [ln for ln in output.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0].split(sep)
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split(sep)
        parts += [""] * (len(header) - len(parts))
        rows.append(dict(zip(header, parts, strict=False)))
    return rows


# Synology-Disk-Status, die KEIN Defekt sind: belegt-normal, leere/unbelegte Slots (not_use),
# NVMe-Cache-Leerslots, System-Partition normal, Standby. Alles andere wird bewertet.
_SYNO_DISK_OK = frozenset(
    {
        "normal",
        "",
        "none",
        "not_use",
        "not_init",
        "not_initialized",
        "initialized",
        "sys_partition_normal",
        "hibernation",
        "sleeping",
        "safe",
    }
)
# Disk-Status, die hart kritisch sind (defekte Platte / Storage-Prozessor-nahe Fehler).
_SYNO_DISK_CRIT = frozenset({"crashed", "system_crashed", "failed", "failing", "broken"})
# Pool-/Volume-Status: diese sind kritisch; "attention"/"background" etc. nur Warnung (gelb).
_SYNO_VOL_CRIT = frozenset({"crashed", "degrade", "degraded", "unmounted", "error"})


def _is_crit_word(s: str) -> bool:
    """Heuristik für kritische SMART-/Statustexte, wenn der genaue Wert unbekannt ist."""
    return any(k in s for k in ("crit", "fail", "danger", "bad"))


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
        temp_warn = bool(data.get("sys_tempwarn") or data.get("temperature_warning"))
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
        raw_disks = sd.get("disks", []) or []
        out["disk_count"] = len(raw_disks)
        out["disks"] = [
            {
                "id": d.get("id"),
                "model": d.get("model"),
                "size_gb": _gb(d.get("size_total")),
                "status": d.get("status"),
                "smart": d.get("smart_status"),
                "temp_c": d.get("temp"),
                "remain_life": d.get("remain_life"),
            }
            for d in raw_disks
        ]
        # --- Hardware-Health ---
        pools = sd.get("storagePools") or sd.get("pools") or []
        critical: list[str] = []
        warning: list[str] = []
        for d in raw_disks:
            did = d.get("id")
            st = (d.get("status") or "normal").strip().lower()
            smart = (d.get("smart_status") or "normal").strip().lower()
            if st in _SYNO_DISK_CRIT:
                critical.append(f"Disk {did}: Status {d.get('status')}")
            elif st not in _SYNO_DISK_OK:
                warning.append(f"Disk {did}: Status {d.get('status')}")
            elif smart not in _SYNO_DISK_OK:
                (critical if _is_crit_word(smart) else warning).append(
                    f"Disk {did}: SMART {d.get('smart_status')}"
                )
            elif d.get("below_remain_life_thr"):
                warning.append(f"Disk {did}: SSD-Restlebensdauer unter Schwelle")
        for pl in pools:
            st = (pl.get("status") or "normal").strip().lower()
            if st in _SYNO_VOL_CRIT:
                critical.append(f"Pool {pl.get('id')}: {pl.get('status')}")
            elif st not in ("normal", "", "none"):
                warning.append(f"Pool {pl.get('id')}: {pl.get('status')}")
        for v in vols:
            st = (v.get("status") or "normal").strip().lower()
            if st in _SYNO_VOL_CRIT:
                critical.append(f"Volume {v.get('id')}: {v.get('status')}")
            elif st not in ("normal", "", "none"):
                warning.append(f"Volume {v.get('id')}: {v.get('status')}")
        if temp_warn:
            warning.append("System-Temperatur-Warnung aktiv")
        out["health_status"], out["health_detail"] = _verdict(
            critical,
            warning,
            f"{len(raw_disks)} Platten normal, {len(pools)} Pool(s)/{len(vols)} Volume(s) ok",
        )
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
    critical: list[str] = []
    warning: list[str] = []
    nodes = await client.get(
        f"{base}/api/cluster/nodes",
        auth=auth,
        params={"fields": "name,model,serial_number,state"},
    )
    recs = nodes.json().get("records", [])
    if recs:
        out["model"] = recs[0].get("model") or out["model"]
        out["serial"] = out["serial"] or recs[0].get("serial_number")
    for n in recs:
        if (n.get("state") or "up") != "up":
            critical.append(f"Controller {n.get('name')}: {n.get('state')}")
    aggr = await client.get(f"{base}/api/storage/aggregates", auth=auth, params={"fields": "space"})
    total = used = 0
    for a in aggr.json().get("records", []):
        blk = (a.get("space") or {}).get("block_storage") or {}
        total += int(blk.get("size", 0) or 0)
        used += int(blk.get("used", 0) or 0)
    out["cap_usable_gb"] = _gb(total) if total else None
    out["cap_used_gb"] = _gb(used) if used else None
    disks = await client.get(
        f"{base}/api/storage/disks",
        auth=auth,
        params={"fields": "name,model,state,container_type", "max_records": "600"},
    )
    drecs = disks.json().get("records", [])
    out["disk_count"] = len(drecs)
    out["disks"] = [
        {"id": d.get("name"), "model": d.get("model"), "status": d.get("state")} for d in drecs
    ]
    for d in drecs:
        st = (d.get("state") or "present").lower()
        if st == "broken":
            critical.append(f"Disk {d.get('name')}: broken")
        elif st in ("maintenance", "reconstructing", "copy", "zeroing", "failed"):
            warning.append(f"Disk {d.get('name')}: {st}")
    try:
        shelves = await client.get(
            f"{base}/api/storage/shelves", auth=auth, params={"fields": "name,state"}
        )
        for sh in shelves.json().get("records", []):
            if (sh.get("state") or "ok") not in ("ok", "unknown"):
                warning.append(f"Shelf {sh.get('name')}: {sh.get('state')}")
    except Exception:
        pass
    states = Counter((d.get("state") or "present") for d in drecs)
    out["health_status"], out["health_detail"] = _verdict(
        critical,
        warning,
        f"{len(drecs)} Platten ({', '.join(f'{v}x {k}' for k, v in states.items())}), "
        f"{len(recs)} Controller up",
    )
    try:
        lifs = await client.get(
            f"{base}/api/network/ip/interfaces", auth=auth, params={"fields": "ip.address"}
        )
        ips = [
            (r.get("ip") or {}).get("address")
            for r in lifs.json().get("records", [])
            if (r.get("ip") or {}).get("address")
        ]
        if ips:
            out["ips"] = ips
    except Exception:
        pass
    return out


async def _storwize_ssh(host: str, user: str, pw: str) -> dict[str, Any]:
    """IBM Storwize/SVC-Health über SSH-CLI: Node-Canister (= Storage-Prozessoren),
    Enclosures (PSU/Lüfter/Canister), Drives und Kapazität (lsmdiskgrp)."""
    import asyncssh

    out: dict[str, Any] = {}
    async with asyncssh.connect(
        host, username=user, password=pw, known_hosts=None, connect_timeout=10
    ) as conn:

        async def run(cmd: str) -> str:
            res = await conn.run(cmd, timeout=25, check=False)
            return str(res.stdout or "")

        system = _parse_kv(await run("lssystem -delim :"))
        out["firmware"] = system.get("code_level")
        out["serial"] = system.get("id")

        critical: list[str] = []
        warning: list[str] = []

        canisters = _parse_delim(await run("lsnodecanister -delim :"))
        for c in canisters:
            if (c.get("status") or "online").lower() != "online":
                critical.append(f"Node-Canister {c.get('name') or c.get('id')}: {c.get('status')}")

        enclosures = _parse_delim(await run("lsenclosure -delim :"))
        for e in enclosures:
            if (e.get("status") or "online").lower() != "online":
                critical.append(f"Enclosure {e.get('id')}: {e.get('status')}")
            for part, label in (
                ("PSUs", "PSU"),
                ("canisters", "Canister"),
                ("fan_modules", "Lüfter"),
            ):
                tot = e.get(f"total_{part}", "")
                onl = e.get(f"online_{part}", "")
                if tot.isdigit() and onl.isdigit() and int(tot) > 0 and int(onl) < int(tot):
                    warning.append(f"Enclosure {e.get('id')}: {onl}/{tot} {label} online")

        drives = _parse_delim(await run("lsdrive -delim :"))
        out["disk_count"] = len(drives)
        out["disks"] = [
            {
                "id": d.get("id"),
                "status": d.get("status"),
                "use": d.get("use"),
                "size": d.get("capacity"),
            }
            for d in drives
        ]
        for d in drives:
            st = (d.get("status") or "online").lower()
            use = (d.get("use") or "").lower()
            if st == "offline":
                # Member/Candidate offline = Array degradiert (kritisch); Spare offline =
                # nur verlorene Redundanz (Warnung, keine Datengefahr).
                if use in ("member", "candidate", "failed"):
                    critical.append(f"Drive {d.get('id')} ({use}): offline")
                else:
                    warning.append(f"Drive {d.get('id')} ({use or 'spare'}): offline")
            elif st and st != "online":
                warning.append(f"Drive {d.get('id')}: {st}")

        pools = _parse_delim(await run("lsmdiskgrp -bytes -delim :"))
        total = free = 0
        for p in pools:
            try:
                total += int(p.get("capacity") or 0)
                free += int(p.get("free_capacity") or 0)
            except ValueError:
                pass
        if total:
            out["cap_usable_gb"] = _gb(total)
            out["cap_used_gb"] = _gb(total - free)

        onl_can = sum(1 for c in canisters if (c.get("status") or "").lower() == "online")
        onl_drv = sum(1 for d in drives if (d.get("status") or "").lower() == "online")
        out["health_status"], out["health_detail"] = _verdict(
            critical,
            warning,
            f"{onl_can}/{len(canisters)} Node-Canister online, "
            f"{len(enclosures)} Enclosure(s) online, {onl_drv}/{len(drives)} Drives online",
        )
    return out


async def _qnap(client: httpx.AsyncClient, base: str, user: str, pw: str) -> dict[str, Any]:
    """QNAP (QTS/QES) über die Web-CGI: Platten-Health (qsmart) + Kapazität (chartReq)."""
    import base64
    import xml.etree.ElementTree as ET

    pwd = base64.b64encode(pw.encode()).decode()
    login = await client.get(f"{base}/cgi-bin/authLogin.cgi", params={"user": user, "pwd": pwd})
    m = re.search(r"<authSid><!\[CDATA\[(.*?)\]\]>", login.text) or re.search(
        r"<authSid>(.*?)</authSid>", login.text
    )
    sid = m.group(1) if m else None
    if not sid:
        raise RuntimeError("QNAP-Login fehlgeschlagen")
    out: dict[str, Any] = {}
    try:
        sm = await client.get(
            f"{base}/cgi-bin/disk/qsmart.cgi", params={"func": "all_hd_data", "sid": sid}
        )
        root = ET.fromstring(sm.text)
        model = root.findtext("model/modelName")
        if model:
            out["model"] = model.strip()
        fw = root.findtext("firmware/version")
        if fw and fw.strip() not in ("", "000"):
            out["firmware"] = fw.strip()
        disks: list[dict[str, Any]] = []
        critical: list[str] = []
        warning: list[str] = []
        for e in root.iter("entry"):
            status = (e.findtext("Disk_Status") or "").strip()
            if status in ("-5", ""):  # -5 = leerer Slot
                continue
            health = (e.findtext("Health") or "").strip()
            alias = (e.findtext("Disk_Alias") or "").strip()
            disks.append(
                {
                    "id": alias,
                    "model": (e.findtext("Model") or "").strip(),
                    "status": health or status,
                    "temp_c": (e.findtext("Temperature") or "").strip() or None,
                }
            )
            healthy = health.upper() in ("OK", "GOOD", "NORMAL", "") and status == "0"
            if not healthy:
                tag = f"Disk {alias}: {health or 'Status ' + status}"
                (warning if "WARN" in health.upper() else critical).append(tag)
        out["disk_count"] = len(disks)
        out["disks"] = disks
        try:
            cu = await client.get(
                f"{base}/cgi-bin/management/chartReq.cgi",
                params={"chart_func": "disk_usage", "sid": sid},
            )
            croot = ET.fromstring(cu.text)
            totals = [int(t) for x in croot.iter("total_size") if (t := (x.text or "")).isdigit()]
            frees = [int(t) for x in croot.iter("free_size") if (t := (x.text or "")).isdigit()]
            if totals:
                out["cap_usable_gb"] = _gb(max(totals))
                if frees:
                    out["cap_used_gb"] = _gb(max(totals) - min(frees))
        except Exception:
            pass
        out["health_status"], out["health_detail"] = _verdict(
            critical, warning, f"{len(disks)} Platten Health OK"
        )
    finally:
        await client.get(f"{base}/cgi-bin/authLogout.cgi", params={"sid": sid})
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
    """ONTAP: SNMP aktivieren + RO-Community PRTG (via privatem CLI-Passthrough). Best effort.

    Hinweis: Manche ONTAP-Versionen lehnen das Anlegen der Community per REST-POST ab (405);
    dort muss ``system snmp community add -type ro -community-name PRTG`` per SSH gesetzt werden.
    """
    auth = (user, pw)
    try:
        await client.patch(f"{base}/api/support/snmp", auth=auth, json={"enabled": True})
    except Exception:
        pass
    try:
        # vorhandene RO-Communities lesen (Feld heisst "access", nicht "type")
        existing = await client.get(
            f"{base}/api/private/cli/system/snmp/community",
            auth=auth,
            params={"fields": "community_name,access"},
        )
        names = [
            r.get("community_name")
            for r in existing.json().get("records", [])
            if r.get("access") == "ro"
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
    if info.get("disks") is not None:
        dev.disks = info["disks"]
    if info.get("ips"):
        merged = sorted(set((dev.ip_addresses or []) + list(info["ips"])))
        dev.ip_addresses = merged
    if not dev.vendor:
        dev.vendor = vendor
    # Echten Hardware-Status aus der API übernehmen (kein blindes OK mehr).
    if info.get("health_status") is not None:
        dev.hardware_status = info["health_status"]
        dev.hardware_detail = info.get("health_detail") or None
    dev.last_seen = datetime.now(UTC)


async def enrich_storage_apis(
    session: AsyncSession, *, enable_snmp: bool = False, sites: list[str] | None = None
) -> StorageApiSummary:
    """Reichert Storage-Geräte über die Hersteller-APIs an (Modell, Kapazität, Disks, Health).

    ``sites`` grenzt auf bestimmte Standort-Namen ein (z.B. ``["S00 - Steelco HQ", "S01 - Icos
    Pharma", "Cusano"]``); ``None`` = alle. ``enable_snmp`` setzt zusätzlich die SNMP-RO-Community
    (nur Synology/NetApp) - ein Schreibzugriff, daher i.d.R. mit ``sites`` eingrenzen.
    """
    from netbuddy.db.models import Site

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
    site_ids: set[Any] | None = None
    if sites:
        site_ids = set(
            (await session.execute(select(Site.id).where(Site.name.in_(sites)))).scalars().all()
        )
    conditions = [StorageDevice.deleted_at.is_(None), StorageDevice.mgmt_ip.isnot(None)]
    if site_ids is not None:
        conditions.append(StorageDevice.site_id.in_(site_ids))
    devices = (await session.execute(select(StorageDevice).where(*conditions))).scalars().all()
    async with httpx.AsyncClient(verify=False, timeout=6.0) as client:
        sem = asyncio.Semaphore(12)

        def record(dev: StorageDevice) -> None:
            if dev.hardware_status in (HardwareStatus.WARNING, HardwareStatus.CRITICAL):
                summary.health.append(
                    f"{dev.name}: {dev.hardware_status.value.upper()} - {dev.hardware_detail}"
                )

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
            blob = f"{name} {(dev.model or '').lower()}"
            async with sem:
                try:
                    if (vendor == "ibm" or "storwize" in blob) and await _port_open(ip, 22):
                        info = await _storwize_ssh(ip, user, pw)
                        _apply(dev, info, "IBM", used_serials)
                        summary.storwize_enriched += 1
                        record(dev)
                        # Storwize-Monitoring läuft über SSH/REST, nicht via SNMP-v2c-Community.
                    elif (vendor == "qnap" or "qnap" in blob) and await _port_open(ip, 443):
                        info = await _qnap(client, f"https://{ip}", user, pw)
                        _apply(dev, info, "QNAP", used_serials)
                        summary.qnap_enriched += 1
                        record(dev)
                        # QNAP-SNMP ist am Standort bereits aktiv (antwortet auf PRTG-Community).
                    elif vendor == "synology" or await _port_open(ip, 5001):
                        info = await _synology(client, f"https://{ip}:5001", user, pw)
                        _apply(dev, info, "Synology", used_serials)
                        summary.synology_enriched += 1
                        record(dev)
                        if enable_snmp:
                            ok, old = await _enable_snmp_synology(
                                client, f"https://{ip}:5001", user, pw
                            )
                            if ok:
                                summary.snmp_enabled += 1
                                if old and old != _SNMP_COMMUNITY:
                                    summary.community_changed.append(f"{dev.name}: {old}->PRTG")
                    elif (
                        vendor == "netapp"
                        or "netapp" in name
                        or ("sto" in name and "msa" not in name)
                    ) and await _port_open(ip, 443):
                        info = await _netapp(client, f"https://{ip}", user, pw)
                        _apply(dev, info, "NetApp", used_serials)
                        summary.netapp_enriched += 1
                        record(dev)
                        if enable_snmp:
                            ok, old = await _enable_snmp_netapp(client, f"https://{ip}", user, pw)
                            if ok:
                                summary.snmp_enabled += 1
                                if old and old != _SNMP_COMMUNITY:
                                    summary.community_changed.append(f"{dev.name}: {old}->PRTG")
                except Exception as exc:
                    detail = str(exc).strip() or type(exc).__name__
                    summary.failed.append(f"{dev.name}: {detail[:80]}")

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
