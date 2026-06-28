from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from loguru import logger
from starlette.middleware.sessions import SessionMiddleware

from netbuddy.api.deps import authorize
from netbuddy.api.routes import (
    adapters,
    audit,
    auth,
    credentials,
    device_credentials,
    devices,
    discovery,
    health,
    poe,
    search,
    sites,
    topology,
    unifi,
    users,
    vlans,
    vpn,
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
    # Kurzlebige, signierte Session nur für den OIDC-Redirect-Flow (State/Nonce); der
    # eigentliche Login läuft weiter über das nb_session-Cookie. Secret = Fernet-Key (vorhanden).
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.fernet_key.get_secret_value(),
        session_cookie="nb_oidc",
        same_site="lax",
        https_only=settings.use_secure_cookies,
        max_age=600,
    )
    app.include_router(health.router)
    app.include_router(devices.router)
    app.include_router(credentials.router)
    app.include_router(adapters.router)
    app.include_router(sites.router)
    app.include_router(vlans.router)
    app.include_router(topology.router)
    app.include_router(discovery.router)
    app.include_router(device_credentials.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(vpn.router)
    app.include_router(unifi.router)
    app.include_router(audit.router)
    app.include_router(search.router)
    app.include_router(poe.router)
    return app


app = create_app()
