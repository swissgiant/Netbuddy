"""iLO/iDRAC/iRMC-Hardware-Health für physische Server über Redfish (read-only).

Analog zu :mod:`netbuddy.services.storage_api` (Storage-Health): bindet die Out-of-Band-
Management-Adresse (HPE iLO / Dell iDRAC / Fujitsu iRMC) an jeden physischen Server, fragt
per **Redfish** den Hardware-Status ab und schreibt Ampel (``hardware_status``) + Klartext
(``hardware_detail``) auf :class:`~netbuddy.db.models.PhysicalServer`.

Adress-Auflösung (in dieser Reihenfolge):
1. ``extra.ilo.ip`` (bereits gebunden),
2. ``mgmt_ip`` wenn ``oob_type`` schon ein OOB-Typ ist,
3. **BLS-Regel**: Server ``10.120.20.x`` → iDRAC ``10.120.21.x`` (drittes Oktett +1; gilt für
   die BLS-Netze 10.120/10.121/10.123),
4. Passwordstate-iLO/iDRAC-Einträge nach IP.

Credential-Auflösung: Sammelkonto ``extra.kind=='ilo'`` passend zum ``extra.scope`` (z.B.
``ILO BLS`` für BLS-Server), sonst Passwordstate-Login nach IP.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models.credential import Credential
from netbuddy.db.models.physical_server import HardwareStatus, PhysicalServer
from netbuddy.db.models.site import Site

# BLS-OOB-Netze: Server x.20.y -> iLO/iDRAC x.21.y
_BLS_MGMT = re.compile(r"^10\.(120|121|123)\.20\.(\d+)$")
# Standort-Namen, für die das Sammelkonto "ILO BLS"/"Storage BLS" (scope=BLS) gilt
_BLS_SITES = {"sulgen", "grosuplje", "cusano"}
_IP = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


@dataclass
class IloHealthSummary:
    checked: int = 0
    ok: int = 0
    warning: int = 0
    critical: int = 0
    bound: int = 0  # iLO-Adresse neu gebunden
    unreachable: list[str] = field(default_factory=list)
    skipped_no_addr: list[str] = field(default_factory=list)
    skipped_no_cred: list[str] = field(default_factory=list)
    health: list[str] = field(default_factory=list)  # nur WARNING/CRITICAL


def _derive_bls_ilo(mgmt_ip: str | None) -> str | None:
    """BLS-iLO-Ableitung (letztes Oktett = Server-Oktett).

    Sulgen (Server ``10.120.20.y``) → iDRAC im **mgmt2-Netz** ``10.250.21.y``.
    Grosuplje/Cusano (``10.121/123.20.y``) → altes Schema ``10.121/123.21.y``.
    """
    if not mgmt_ip:
        return None
    m = _BLS_MGMT.match(str(mgmt_ip))
    if not m:
        return None
    third, host = m.group(1), m.group(2)
    if third == "120":
        return f"10.250.21.{host}"
    return f"10.{third}.21.{host}"


def _ilo_sub(extra: dict[str, Any] | None) -> dict[str, Any]:
    """``extra['ilo']`` als Dict (typ-sicher), sonst leer."""
    sub = (extra or {}).get("ilo")
    return sub if isinstance(sub, dict) else {}


def _ilo_addr(ps: PhysicalServer) -> tuple[str | None, bool]:
    """(iLO-IP, neu_abgeleitet). None wenn keine ermittelbar."""
    sub = _ilo_sub(ps.extra)
    cur = sub.get("ip")
    derived = _derive_bls_ilo(str(ps.mgmt_ip) if ps.mgmt_ip else None)
    # Auto-abgeleitete Alt-Bindung aktualisieren, wenn sich die Ableitungs-Regel geändert hat.
    if cur and sub.get("source") == "bls-rule" and derived and derived != str(cur):
        return derived, True
    if cur:
        return str(cur), False
    if ps.oob_type and ps.mgmt_ip:
        # mgmt_ip ist bereits die OOB-Adresse
        return str(ps.mgmt_ip), False
    if derived:
        return derived, True
    return None, False


def _worst(cur: HardwareStatus, new: HardwareStatus) -> HardwareStatus:
    order = {
        HardwareStatus.OK: 0,
        HardwareStatus.UNKNOWN: 1,
        HardwareStatus.WARNING: 2,
        HardwareStatus.CRITICAL: 3,
    }
    return new if order[new] > order[cur] else cur


def _map_health(health: str | None) -> HardwareStatus:
    h = (health or "").lower()
    if h == "ok":
        return HardwareStatus.OK
    if h == "warning":
        return HardwareStatus.WARNING
    if h in ("critical", "fatal"):
        return HardwareStatus.CRITICAL
    return HardwareStatus.UNKNOWN


async def _rf(client: httpx.AsyncClient, base: str, path: str) -> dict[str, Any] | None:
    # HPE iLO schließt gern die (wiederverwendete) Verbindung -> RemoteProtocolError: einmal retry.
    for attempt in range(2):
        try:
            r = await client.get(f"{base}{path}")
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, dict) else None
            return None
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError):
            if attempt == 0:
                continue
            return None
        except Exception:
            return None
    return None


async def _redfish_health(
    ip: str, user: str, pw: str
) -> tuple[HardwareStatus, str, dict[str, Any]]:
    """Fragt Redfish ab und aggregiert den schlechtesten Komponenten-Status + Klartext.

    Funktioniert für Dell iDRAC, HPE iLO 5/6 und Fujitsu iRMC (alle Redfish >= 1.0).
    Eigener Client je Server (Auth im Konstruktor), damit Concurrency sauber bleibt.
    """
    base = f"https://{ip}"
    # Keep-Alive aus (max_keepalive_connections=0) + Connection: close — HPE iLO verträgt keine
    # wiederverwendeten Verbindungen auf /Systems (RemoteProtocolError).
    async with httpx.AsyncClient(
        verify=False,
        timeout=8.0,
        auth=httpx.BasicAuth(user, pw),
        headers={"Connection": "close"},
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as client:
        return await _redfish_collect(client, base, ip)


async def _redfish_collect(
    client: httpx.AsyncClient, base: str, ip: str
) -> tuple[HardwareStatus, str, dict[str, Any]]:
    status = HardwareStatus.UNKNOWN
    problems: list[str] = []
    meta: dict[str, Any] = {}

    systems = await _rf(client, base, "/redfish/v1/Systems")
    sys_url = None
    if systems and systems.get("Members"):
        sys_url = systems["Members"][0].get("@odata.id")
    sysobj = await _rf(client, base, sys_url.replace(base, "")) if sys_url else None
    if sysobj is None:
        # Kein System erreichbar -> Auth/Modell-Problem
        raise RuntimeError("Redfish: kein Systems-Objekt (Auth/Reachability?)")

    meta["model"] = sysobj.get("Model")
    meta["manufacturer"] = sysobj.get("Manufacturer")
    # Dell: SKU = 7-stelliger Service-Tag (für Garantie); sonst SerialNumber.
    meta["serial"] = sysobj.get("SerialNumber")
    # Dell: SKU = eindeutiger 7-stelliger Service-Tag. HPE: SKU = Produktnummer (NICHT eindeutig!)
    # -> dort SerialNumber nehmen (eindeutig).
    _mfr = (sysobj.get("Manufacturer") or "").lower()
    meta["service_tag"] = (
        sysobj.get("SKU") if "dell" in _mfr else None
    ) or sysobj.get("SerialNumber")
    meta["bios"] = sysobj.get("BiosVersion")
    proc_sum = sysobj.get("ProcessorSummary") or {}
    mem_sum = sysobj.get("MemorySummary") or {}
    meta["cpu_count"] = proc_sum.get("Count")
    meta["cpu_model"] = proc_sum.get("Model")
    ram_gib = mem_sum.get("TotalSystemMemoryGiB")
    meta["ram_mb"] = int(float(ram_gib) * 1024) if ram_gib is not None else None
    st = sysobj.get("Status") or {}
    roll = st.get("HealthRollup") or st.get("Health")
    status = _worst(status, _map_health(roll))

    # Subsystem-Zusammenfassungen (für den Klartext, was genau)
    for key, label in (("ProcessorSummary", "CPU"), ("MemorySummary", "RAM")):
        sub = (sysobj.get(key) or {}).get("Status") or {}
        hh = sub.get("HealthRollup") or sub.get("Health")
        s2 = _map_health(hh)
        if s2 in (HardwareStatus.WARNING, HardwareStatus.CRITICAL):
            problems.append(f"{label}={hh}")
        status = _worst(status, s2)

    # CPU-Detail (Modell/Cores/Threads) aus der Processors-Collection (erster Prozessor)
    if sys_url:
        procs = await _rf(client, base, f"{sys_url.replace(base, '')}/Processors")
        if procs and procs.get("Members"):
            p0 = await _rf(client, base, procs["Members"][0].get("@odata.id", "").replace(base, ""))
            if p0:
                meta["cpu_model"] = meta.get("cpu_model") or p0.get("Model")
                meta["cpu_cores"] = p0.get("TotalCores")
                meta["cpu_threads"] = p0.get("TotalThreads")

    # Chassis: Lüfter / Netzteile / Temperatur
    chassis = await _rf(client, base, "/redfish/v1/Chassis")
    ch_url = None
    if chassis and chassis.get("Members"):
        ch_url = chassis["Members"][0].get("@odata.id")
    if ch_url:
        cu = ch_url.replace(base, "")
        for sub_path, label in ((f"{cu}/Thermal", "Lüfter/Temp"), (f"{cu}/Power", "Netzteil")):
            obj = await _rf(client, base, sub_path)
            if not obj:
                continue
            arrays = ("Fans", "Temperatures") if "Thermal" in sub_path else ("PowerSupplies",)
            for arr in arrays:
                for item in obj.get(arr, []) or []:
                    ist = item.get("Status") or {}
                    hh = ist.get("Health")
                    state = ist.get("State")
                    if state in ("Absent", "UnavailableOffline", None) and hh is None:
                        continue
                    s2 = _map_health(hh)
                    if s2 in (HardwareStatus.WARNING, HardwareStatus.CRITICAL):
                        nm = item.get("Name") or item.get("MemberId") or arr
                        problems.append(f"{label}:{nm}={hh}")
                    status = _worst(status, s2)

    # Laufwerke (SimpleStorage/Storage) — nur wenn vorhanden
    for sp in ("/Storage", "/SimpleStorage"):
        coll = await _rf(client, base, f"{sys_url.replace(base, '')}{sp}") if sys_url else None
        if not coll:
            continue
        for mem in coll.get("Members", []) or []:
            d = await _rf(client, base, mem.get("@odata.id", "").replace(base, ""))
            if not d:
                continue
            for drv in d.get("Drives", []) or d.get("Devices", []) or []:
                if isinstance(drv, dict) and "@odata.id" in drv:
                    drv = await _rf(client, base, drv["@odata.id"].replace(base, "")) or {}
                ist = drv.get("Status") or {}
                s2 = _map_health(ist.get("Health"))
                if s2 in (HardwareStatus.WARNING, HardwareStatus.CRITICAL):
                    problems.append(f"Disk:{drv.get('Name') or drv.get('Id')}={ist.get('Health')}")
                status = _worst(status, s2)
        break  # erste gefundene Collection reicht

    if status == HardwareStatus.UNKNOWN and roll:
        status = _map_health(roll)
    detail = "; ".join(problems) if problems else (f"Redfish Health={roll}" if roll else "")
    return status, detail, meta


async def _resolve_creds(
    session: AsyncSession,
) -> tuple[dict[str, Credential], dict[str, tuple[str, str]]]:
    """(scope->Sammel-Credential, IP->(user,pw) aus Passwordstate-iLO/iDRAC-Listen)."""
    scoped: dict[str, Credential] = {}
    for c in (
        (await session.execute(select(Credential).where(Credential.deleted_at.is_(None))))
        .scalars()
        .all()
    ):
        if (c.extra or {}).get("kind") == "ilo" and c.username and c.password:
            scoped[str((c.extra or {}).get("scope", "")).lower()] = c

    by_ip: dict[str, tuple[str, str]] = {}
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
    if pw:
        from netbuddy.services.passwordstate import PasswordstateApi

        try:
            async with PasswordstateApi(pw) as api:
                for lst in await api.fetch_lists():
                    if not re.search(
                        r"ilo|idrac|irmc|imm|xclarity|hardware|remote|oob|server",
                        f"{lst.name} {lst.tree_path or ''}",
                        re.I,
                    ):
                        continue
                    try:
                        entries = await api.fetch_list(lst.list_id)
                    except Exception:
                        continue
                    for e in entries:
                        if not e.username or not e.password:
                            continue
                        found = None
                        for fieldv in (e.hostname, e.url, e.description, e.notes, e.title):
                            if fieldv and (m := _IP.search(fieldv)):
                                found = m.group(1)
                                break
                        if not found:  # Host-URL (z.B. rmcbchz-esxi01.corp...) -> DNS auflösen
                            for fieldv in (e.url, e.hostname):
                                if fieldv:
                                    host = re.sub(r"^https?://", "", fieldv).split("/")[0].strip()
                                    if host and "." in host and not _IP.match(host):
                                        found = await asyncio.to_thread(_resolve_host, host)
                                        if found:
                                            break
                        if found:
                            by_ip.setdefault(found, (e.username, e.password))
        except Exception:
            pass
    return scoped, by_ip


def _resolve_host(host: str) -> str | None:
    import socket

    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


def _scope(site_name: str | None, ilo_ip: str | None) -> str | None:
    """BLS-Scope, wenn die iLO in einem BLS-OOB-Netz liegt (10.120/10.121/10.123) oder der
    Standort ein BLS-Standort ist. Deckt so auch die Cusano-HPE-iLOs (10.123.40.x) ab."""
    if ilo_ip and ilo_ip.startswith(("10.250.", "10.120.", "10.121.", "10.123.")):
        return "bls"
    if site_name and site_name.lower() in _BLS_SITES:
        return "bls"
    return None


async def enrich_ilo_health(
    session: AsyncSession, *, sites: list[str] | None = None, bind_only: bool = False
) -> IloHealthSummary:
    """Bindet iLO-Adressen und fragt Hardware-Health ab. ``bind_only`` schreibt nur die Adresse.

    ``sites`` grenzt auf Standort-Namen ein; ``None`` = alle.
    """
    summary = IloHealthSummary()
    site_names = {s.id: s.name for s in (await session.execute(select(Site))).scalars().all()}

    conds = [PhysicalServer.deleted_at.is_(None)]
    if sites:
        ids = set(
            (await session.execute(select(Site.id).where(Site.name.in_(sites)))).scalars().all()
        )
        conds.append(PhysicalServer.site_id.in_(ids))
    servers = (await session.execute(select(PhysicalServer).where(*conds))).scalars().all()

    scoped, by_ip = ({}, {}) if bind_only else await _resolve_creds(session)

    sem = asyncio.Semaphore(10)

    async def handle(ps: PhysicalServer) -> None:
        site_name = site_names.get(ps.site_id) if ps.site_id else None
        ilo_ip, newly = _ilo_addr(ps)
        if not ilo_ip:
            summary.skipped_no_addr.append(ps.hostname)
            return
        if newly:
            extra = dict(ps.extra or {})
            extra["ilo"] = {
                **_ilo_sub(extra),
                "ip": ilo_ip,
                "source": "bls-rule",
                "bound": datetime.now(UTC).isoformat(),
            }
            ps.extra = extra
            if not ps.oob_type:
                ps.oob_type = "idrac" if (ps.vendor or "").lower().startswith("dell") else "ilo"
            summary.bound += 1
        if bind_only:
            return
        scope = _scope(site_name, ilo_ip)
        cred = scoped.get(scope) if scope else None
        if cred and cred.username and cred.password:
            user, pwd = str(cred.username), str(cred.password)
        elif ilo_ip in by_ip:
            user, pwd = by_ip[ilo_ip]
        else:
            summary.skipped_no_cred.append(f"{ps.hostname} ({ilo_ip})")
            return
        async with sem:
            try:
                st, detail, meta = await _redfish_health(ilo_ip, user, pwd)
            except Exception as exc:
                summary.unreachable.append(f"{ps.hostname} ({ilo_ip}): {str(exc)[:60]}")
                return
        ps.hardware_status = st
        ps.hardware_detail = detail or None
        # Hardware-Stammdaten aus Redfish (Redfish ist die Hardware-Wahrheit):
        # nur setzen, wenn Redfish einen Wert liefert (sonst Bestehendes behalten).
        if meta.get("service_tag"):
            ps.service_tag = str(meta["service_tag"])
        if meta.get("model"):
            ps.model = str(meta["model"])
        if meta.get("manufacturer"):
            ps.vendor = str(meta["manufacturer"])
        if meta.get("cpu_model"):
            ps.cpu_model = str(meta["cpu_model"])
        if meta.get("cpu_count") is not None:
            ps.cpu_sockets = int(meta["cpu_count"])
        if meta.get("cpu_cores") is not None:
            ps.cpu_cores = int(meta["cpu_cores"])
        if meta.get("cpu_threads") is not None:
            ps.cpu_threads = int(meta["cpu_threads"])
        if meta.get("ram_mb") is not None:
            ps.ram_mb = int(meta["ram_mb"])
        extra2 = dict(ps.extra or {})
        extra2["ilo"] = {
            **_ilo_sub(extra2),
            "ip": ilo_ip,
            "bios": meta.get("bios"),
            "serial": meta.get("serial"),
            "checked": datetime.now(UTC).isoformat(),
        }
        ps.extra = extra2
        summary.checked += 1
        if st == HardwareStatus.OK:
            summary.ok += 1
        elif st == HardwareStatus.WARNING:
            summary.warning += 1
            summary.health.append(f"{ps.hostname}: WARNING - {detail}")
        elif st == HardwareStatus.CRITICAL:
            summary.critical += 1
            summary.health.append(f"{ps.hostname}: CRITICAL - {detail}")

    await asyncio.gather(*[handle(ps) for ps in servers])
    await session.commit()
    return summary
