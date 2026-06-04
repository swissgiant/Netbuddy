from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

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
