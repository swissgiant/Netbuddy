from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters import connect
from netbuddy.adapters.base import SwitchAdapter
from netbuddy.db.models import Credential, Device
from netbuddy.db.session import get_session
from netbuddy.services.validation import DeviceValidationReport, validate_device

SessionDep = Annotated[AsyncSession, Depends(get_session)]

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
