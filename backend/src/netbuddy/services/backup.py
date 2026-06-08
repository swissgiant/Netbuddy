import difflib
import hashlib
from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.db.models import ConfigBackup, Device


class BackupResult(BaseModel):
    changed: bool  # False = identisch zur letzten Sicherung (nicht neu gespeichert)
    sha256: str
    size: int


async def _latest(session: AsyncSession, device_id: object) -> ConfigBackup | None:
    stmt = (
        select(ConfigBackup)
        .where(ConfigBackup.device_id == device_id)
        .order_by(ConfigBackup.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def backup_device(
    session: AsyncSession, device: Device, adapter: SwitchAdapter
) -> BackupResult:
    """Holt die laufende Konfiguration read-only und speichert sie, wenn sie sich geändert hat."""
    content = await adapter.get_config()
    digest = hashlib.sha256(content.encode()).hexdigest()
    latest = await _latest(session, device.id)
    if latest is not None and latest.sha256 == digest:
        return BackupResult(changed=False, sha256=digest, size=len(content))
    session.add(ConfigBackup(device_id=device.id, content=content, sha256=digest))
    await session.flush()
    return BackupResult(changed=True, sha256=digest, size=len(content))


async def diff_latest(session: AsyncSession, device_id: object) -> str:
    """Unified-Diff der beiden jüngsten Sicherungen (leer, wenn <2 vorhanden)."""
    stmt = (
        select(ConfigBackup)
        .where(ConfigBackup.device_id == device_id)
        .order_by(ConfigBackup.created_at.desc())
        .limit(2)
    )
    rows: Sequence[ConfigBackup] = (await session.execute(stmt)).scalars().all()
    if len(rows) < 2:
        return ""
    newer, older = rows[0], rows[1]
    diff = difflib.unified_diff(
        older.content.splitlines(),
        newer.content.splitlines(),
        fromfile=f"backup {older.created_at:%Y-%m-%d %H:%M}",
        tofile=f"backup {newer.created_at:%Y-%m-%d %H:%M}",
        lineterm="",
    )
    return "\n".join(diff)
