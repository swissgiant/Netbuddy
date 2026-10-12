"""SNMP-Anreicherung (read-only) für Storage und physische Server.

Die SNMP-Read-Community liegt in Passwordstate (Liste „B-HQ Switch", Eintrag „SNMP Community") und
wird organisationsweit genutzt. Nicht jedes Gerät hat SNMP aktiv/erreichbar — wer nicht antwortet,
bleibt unverändert. Gelesen werden: Systembeschreibung/-name (Modell-Hinweis), Seriennummer
(ENTITY-MIB bzw. NetApp-MIB), Kapazität (HOST-RESOURCES hrStorage) und bei Servern RAM.
"""

import asyncio
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import (
    Credential,
    HardwareStatus,
    PhysicalServer,
    StorageDevice,
)

_SYSDESCR = "1.3.6.1.2.1.1.1.0"
_SYSNAME = "1.3.6.1.2.1.1.5.0"
_HR_TYPE = "1.3.6.1.2.1.25.2.3.1.2"
_HR_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
_HR_UNITS = "1.3.6.1.2.1.25.2.3.1.4"
_HR_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
_HR_USED = "1.3.6.1.2.1.25.2.3.1.6"
_HR_FIXED_DISK = "1.3.6.1.2.1.25.2.1.4"
_HR_MEM = "1.3.6.1.2.1.25.2.2.0"  # KB
_ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
_ENT_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13"
_NETAPP_MODEL = "1.3.6.1.4.1.789.1.1.5.0"
_NETAPP_SERIAL = "1.3.6.1.4.1.789.1.1.9.0"
_SYNO_MODEL = "1.3.6.1.4.1.6574.1.5.1.0"
_SYNO_SERIAL = "1.3.6.1.4.1.6574.1.5.2.0"
_QNAP_MODEL = "1.3.6.1.4.1.24681.1.2.12.0"
_QNAP_SERIAL = "1.3.6.1.4.1.24681.1.4.4.0"


class SnmpSummary(BaseModel):
    community_found: bool
    storage_total: int = 0
    storage_enriched: int = 0
    physical_total: int = 0
    physical_enriched: int = 0
    no_response: list[str] = []


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("latin-1", "replace").strip() or None
    return str(value).strip() or None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _communities(session: AsyncSession) -> list[str]:
    """Read-Communities: dedizierte SNMP-Credentials (PRTG) zuerst, dann Switch-Liste."""
    out: list[str] = []
    snmp_creds = (
        (
            await session.execute(
                select(Credential).where(
                    Credential.deleted_at.is_(None), Credential.snmp_community.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for c in sorted(snmp_creds, key=lambda x: 0 if "prtg" in x.name.lower() else 1):
        if c.snmp_community and c.snmp_community not in out:
            out.append(c.snmp_community)
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
    if pw is not None:
        try:
            async with PasswordstateApi(pw) as api:
                for lst in await api.fetch_lists():
                    if lst.name == "B-HQ Switch":
                        for entry in await api.fetch_list(lst.list_id):
                            if "SNMP Community" in entry.title and entry.password:
                                if entry.password not in out:
                                    out.append(entry.password)
        except Exception:
            pass
    return out


class _Snmp:
    """Dünner Wrapper um puresnmp mit hartem Timeout je Abfrage."""

    def __init__(self, ip: str, community: str) -> None:
        from puresnmp import V2C, Client, PyWrapper

        self._c = PyWrapper(Client(ip, V2C(community)))

    async def get(self, oid: str, timeout_s: float = 1.5) -> Any:
        async with asyncio.timeout(timeout_s):
            return await self._c.get(oid)

    async def table(self, timeout_s: float = 8.0) -> dict[str, dict[str, Any]]:
        """hrStorageTable nach Index sammeln (descr/units/size/used/type)."""
        rows: dict[str, dict[str, Any]] = {}

        async def walk(col: str, key: str) -> None:
            async for vb in self._c.walk(col):
                idx = str(vb.oid).rsplit(".", 1)[-1]
                rows.setdefault(idx, {})[key] = vb.value

        for col, key in (
            (_HR_TYPE, "type"),
            (_HR_DESCR, "descr"),
            (_HR_UNITS, "units"),
            (_HR_SIZE, "size"),
            (_HR_USED, "used"),
        ):
            try:
                async with asyncio.timeout(timeout_s):
                    await walk(col, key)
            except Exception:
                break
        return rows


def _capacity_gb(table: dict[str, dict[str, Any]]) -> tuple[int | None, int | None]:
    """Summe der „Fixed Disk"-Zeilen → (nutzbar_gb, belegt_gb)."""
    total_b = 0
    used_b = 0
    found = False
    for row in table.values():
        if str(row.get("type", "")).endswith(
            _HR_FIXED_DISK.rsplit(".", 1)[-1]
        ) or _HR_FIXED_DISK in str(row.get("type", "")):
            units = _int(row.get("units")) or 0
            size = _int(row.get("size")) or 0
            used = _int(row.get("used")) or 0
            if units and size:
                total_b += units * size
                used_b += units * used
                found = True
    if not found:
        return None, None
    return total_b // (1024**3), used_b // (1024**3)


async def _enrich_storage(snmp: _Snmp, dev: StorageDevice) -> bool:
    descr = _text(await snmp.get(_SYSDESCR))  # wirft bei Timeout -> no response
    name = _text(await snmp.get(_SYSNAME))
    # Kein blindes OK mehr: ein erreichbarer sysDescr belegt keine Platten-/SP-Gesundheit.
    # Den echten Hardware-Status setzen die Hersteller-API-Adapter (storage_api.py).
    extra = dict(dev.extra or {})
    if descr:
        extra["snmp_sysdescr"] = descr[:300]
        if not dev.model:
            dev.model = descr.split(",")[0][:120]
    if name and not dev.dns_name:
        dev.dns_name = name
    for oid in (_NETAPP_SERIAL, _ENT_SERIAL):
        try:
            serial = _text(await snmp.get(oid))
        except Exception:
            serial = None
        if serial and not dev.service_tag:
            dev.service_tag = serial[:128]
            break
    try:
        model = _text(await snmp.get(_NETAPP_MODEL))
        if model:
            dev.model = model[:120]
    except Exception:
        pass
    for model_oid, serial_oid in ((_SYNO_MODEL, _SYNO_SERIAL), (_QNAP_MODEL, _QNAP_SERIAL)):
        try:
            model = _text(await snmp.get(model_oid))
            if model:
                dev.model = model[:120]
                serial = _text(await snmp.get(serial_oid))
                if serial:
                    dev.service_tag = serial[:128]
        except Exception:
            continue
    usable, used = _capacity_gb(await snmp.table())
    if usable:
        dev.capacity_usable_gb = usable
        dev.capacity_used_gb = used
    dev.extra = extra
    return True


async def _enrich_physical(snmp: _Snmp, dev: PhysicalServer) -> bool:
    descr = _text(await snmp.get(_SYSDESCR))
    name = _text(await snmp.get(_SYSNAME))
    dev.hardware_status = HardwareStatus.OK
    extra = dict(dev.extra or {})
    if descr:
        extra["snmp_sysdescr"] = descr[:300]
    if name and not dev.dns_name:
        dev.dns_name = name
    for oid in (_ENT_SERIAL,):
        try:
            serial = _text(await snmp.get(oid))
        except Exception:
            serial = None
        if serial and not dev.service_tag:
            dev.service_tag = serial[:128]
    try:
        mem_kb = _int(await snmp.get(_HR_MEM))
        if mem_kb and not dev.ram_mb:
            dev.ram_mb = mem_kb // 1024
    except Exception:
        pass
    dev.extra = extra
    return True


def _target_ip(dev: StorageDevice | PhysicalServer) -> str:
    """Erreichbare Adresse: Cato-übersetzte IP (extra.reachable_ip) sonst die Mgmt-IP."""
    return str(dev.reachable_ip) if dev.reachable_ip else str(dev.mgmt_ip)


async def snmp_enrich(session: AsyncSession) -> SnmpSummary:
    communities = await _communities(session)
    summary = SnmpSummary(community_found=bool(communities))
    if not communities:
        return summary

    storage = (
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
    physical = (
        (
            await session.execute(
                select(PhysicalServer).where(
                    PhysicalServer.deleted_at.is_(None), PhysicalServer.mgmt_ip.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )
    summary.storage_total = len(storage)
    summary.physical_total = len(physical)

    sem = asyncio.Semaphore(25)

    async def do_storage(dev: StorageDevice) -> None:
        async with sem:
            for community in communities:
                try:
                    await _enrich_storage(_Snmp(_target_ip(dev), community), dev)
                    summary.storage_enriched += 1
                    return
                except Exception:
                    continue
            summary.no_response.append(f"storage:{dev.name}")

    async def do_physical(dev: PhysicalServer) -> None:
        async with sem:
            for community in communities:
                try:
                    await _enrich_physical(_Snmp(_target_ip(dev), community), dev)
                    summary.physical_enriched += 1
                    return
                except Exception:
                    continue
            summary.no_response.append(f"phys:{dev.hostname}")

    await asyncio.gather(*[do_storage(d) for d in storage], *[do_physical(d) for d in physical])
    await session.commit()
    return summary
