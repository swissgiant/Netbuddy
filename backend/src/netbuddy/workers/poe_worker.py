"""ARQ-Worker für das geplante (periodische) PoE-Auto-Recover.

Start (separater Prozess, Redis muss laufen):

    uv run arq netbuddy.workers.poe_worker.WorkerSettings

Konfiguration über `.env`: `redis_url`, `scheduled_poe_recover_minutes` (0 = aus → nur Button).
Findet „hängende" AP-Ports (PoE Fault/Searching + Link down + UniFi offline) und bounct sie
(shut/no shut) — mit Rate-Limit, damit ein hart-toter Port nicht endlos gebounct wird.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from loguru import logger

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.factory import connect
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.core.config import get_settings
from netbuddy.core.logging import setup_logging
from netbuddy.db.models import Credential, Device
from netbuddy.db.session import SessionLocal
from netbuddy.services.poe_recover import auto_recover


@asynccontextmanager
async def _live_connection(
    device: Device, credential: Credential
) -> AsyncIterator[tuple[SwitchAdapter, ScrapliTransport]]:
    adapter, transport = connect(device, credential)
    async with transport:
        yield adapter, transport


async def scheduled_poe_recover(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ-Job: hängende AP-Ports fleet-weit finden und per Bounce erholen."""
    async with SessionLocal() as session:
        events = await auto_recover(session, _live_connection, actor="worker")
        await session.commit()
    by_action: dict[str, int] = {}
    for e in events:
        by_action[e.action] = by_action.get(e.action, 0) + 1
    logger.info("PoE-Auto-Recover: {n} Ports bearbeitet {detail}", n=len(events), detail=by_action)
    return {"events": len(events), "by_action": by_action}


def _cron_jobs() -> list[Any]:
    minutes = get_settings().scheduled_poe_recover_minutes
    if minutes <= 0:
        return []
    return [cron(scheduled_poe_recover, minute=set(range(0, 60, minutes)))]


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Any]]] = [scheduled_poe_recover]
    cron_jobs: ClassVar[list[Any]] = _cron_jobs()
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(get_settings().redis_url)

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        setup_logging()
        logger.info(
            "PoE-Recover-Worker gestartet (Intervall: {m} min)",
            m=get_settings().scheduled_poe_recover_minutes,
        )
