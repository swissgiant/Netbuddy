"""ARQ-Worker für die geplante (periodische) Discovery.

Start (separater Prozess, Redis muss laufen):

    uv run arq netbuddy.workers.discovery_worker.WorkerSettings

Konfiguration über `.env`: `redis_url`, `scheduled_discovery_minutes` (0 = aus).
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from loguru import logger

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.factory import connect
from netbuddy.core.config import get_settings
from netbuddy.core.logging import setup_logging
from netbuddy.db.models import Credential, Device
from netbuddy.db.session import SessionLocal
from netbuddy.services.discovery import run_scheduled_discovery


@asynccontextmanager
async def _live_adapter(device: Device, credential: Credential) -> AsyncIterator[SwitchAdapter]:
    adapter, transport = connect(device, credential)
    async with transport:
        yield adapter


async def scheduled_discovery(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ-Job: alle aktiven Geräte mit SSH-Credential read-only discovern + persistieren."""
    async with SessionLocal() as session:
        summary = await run_scheduled_discovery(session, _live_adapter)
        await session.commit()
    logger.info(
        "Scheduled discovery: {n} Geräte, {ok} ok, {err} Fehler",
        n=summary["devices"],
        ok=len(summary["ok"]),
        err=len(summary["errors"]),
    )
    return summary


def _cron_jobs() -> list[Any]:
    minutes = get_settings().scheduled_discovery_minutes
    if minutes <= 0:
        return []
    return [cron(scheduled_discovery, minute=set(range(0, 60, minutes)))]


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Any]]] = [scheduled_discovery]
    cron_jobs: ClassVar[list[Any]] = _cron_jobs()
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().redis_url)

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        setup_logging()
        logger.info(
            "Discovery-Worker gestartet (Intervall: {m} min)",
            m=get_settings().scheduled_discovery_minutes,
        )
