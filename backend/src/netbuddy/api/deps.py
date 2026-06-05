from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters import connect
from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.connection import onboarding_params
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.adapters.transport import CommandTransport
from netbuddy.db.models import Credential, Device, User, UserRole
from netbuddy.db.session import get_session
from netbuddy.services.auth import COOKIE_NAME, resolve_token
from netbuddy.services.validation import DeviceValidationReport, validate_device

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# --- Auth/RBAC --------------------------------------------------------------------------------

# Ohne Login erreichbar (Login/Setup selbst, Health, API-Doku).
_PUBLIC_PATHS = {"/health", "/openapi.json", "/auth/login", "/auth/setup", "/auth/setup-status"}
_ROLE_RANK: dict[UserRole, int] = {UserRole.VIEWER: 0, UserRole.OPERATOR: 1, UserRole.ADMIN: 2}


async def get_current_user(request: Request, session: SessionDep) -> User | None:
    """Liest den Login-Token: explizites `Authorization: Bearer` gewinnt vor dem Cookie."""
    token: str | None = None
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header.removeprefix("Bearer ")
    if not token:
        token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return await resolve_token(session, token)


CurrentUserDep = Annotated[User | None, Depends(get_current_user)]


async def authorize(request: Request, user: CurrentUserDep) -> User | None:
    """Globale RBAC-Policy: GET = viewer+, Mutationen/„suchen" = operator+, /users = admin.

    `/auth/*` (logout/me) verlangt nur einen gültigen Login, unabhängig von der Rolle.
    """
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith(("/docs", "/redoc")):
        return None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
    if path.startswith("/auth/"):
        return user
    if path.startswith("/users"):
        required = UserRole.ADMIN
    elif request.method == "GET":
        required = UserRole.VIEWER
    else:
        required = UserRole.OPERATOR
    if _ROLE_RANK[user.role] < _ROLE_RANK[required]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Rolle {user.role} reicht nicht (benötigt: {required})",
        )
    return user


# Live-Validierung als injizierbare Dependency: Tests überschreiben das, um ohne echtes
# Gerät zu prüfen (DI-Override statt echtem SSH).
DeviceValidator = Callable[
    [Device, Credential], Awaitable[tuple[DeviceValidationReport, dict[str, str]]]
]


def get_device_validator() -> DeviceValidator:
    return validate_device


ValidatorDep = Annotated[DeviceValidator, Depends(get_device_validator)]


# Live-Adapter als async Context-Manager (öffnet/schließt den Transport). Injizierbar, damit
# Discovery-Endpoints in Tests ohne echtes Gerät laufen.
LiveAdapter = Callable[[Device, Credential], AbstractAsyncContextManager[SwitchAdapter]]


@asynccontextmanager
async def _default_live_adapter(
    device: Device, credential: Credential
) -> AsyncIterator[SwitchAdapter]:
    adapter, transport = connect(device, credential)
    async with transport:
        yield adapter


def get_live_adapter() -> LiveAdapter:
    return _default_live_adapter


LiveAdapterDep = Annotated[LiveAdapter, Depends(get_live_adapter)]


# Generischer Transport fürs assistierte Onboarding (unbekanntes Gerät). Injizierbar für Tests.
OnboardingTransport = Callable[[Device, Credential], AbstractAsyncContextManager[CommandTransport]]


@asynccontextmanager
async def _default_onboarding_transport(
    device: Device, credential: Credential
) -> AsyncIterator[CommandTransport]:
    transport = ScrapliTransport(onboarding_params(device, credential))
    async with transport:
        yield transport


def get_onboarding_transport() -> OnboardingTransport:
    return _default_onboarding_transport


OnboardingTransportDep = Annotated[OnboardingTransport, Depends(get_onboarding_transport)]
