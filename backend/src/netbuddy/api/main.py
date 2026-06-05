from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from loguru import logger

from netbuddy.api.deps import authorize
from netbuddy.api.routes import (
    adapters,
    auth,
    credentials,
    device_credentials,
    devices,
    discovery,
    health,
    sites,
    topology,
    users,
)
from netbuddy.core.config import get_settings
from netbuddy.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    logger.info("Starting {app}", app=settings.app_name)
    yield
    logger.info("Shutting down {app}", app=settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
        dependencies=[Depends(authorize)],  # globale RBAC-Policy (siehe api/deps.py)
    )
    app.include_router(health.router)
    app.include_router(devices.router)
    app.include_router(credentials.router)
    app.include_router(adapters.router)
    app.include_router(sites.router)
    app.include_router(topology.router)
    app.include_router(discovery.router)
    app.include_router(device_credentials.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    return app


app = create_app()
