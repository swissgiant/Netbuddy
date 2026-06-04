from typing import Any, Literal

from netbuddy.adapters.base import AdapterError, SwitchAdapter
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.declarative import DeclarativeAdapter
from netbuddy.adapters.profile import VendorProfile, load_profiles_from_package
from netbuddy.adapters.transport import CommandTransport

# CLI/TextFSM-Vendor: adapter_id → Profil (aus adapters/profiles/*.yaml).
_PROFILES: dict[str, VendorProfile] = load_profiles_from_package()

# API-Vendor (UniFi/Meraki/…): adapter_id → Adapter-Klasse (Code, kein Profil).
_API_ADAPTERS: dict[str, type[Any]] = {}


class UnknownAdapterError(AdapterError):
    """Es gibt weder ein Profil noch einen API-Adapter für die angefragte `adapter_id`."""

    def __init__(self, adapter_id: str) -> None:
        super().__init__(f"Kein Adapter registriert für {adapter_id!r}")
        self.adapter_id = adapter_id


def register_api_adapter(cls: type[Any]) -> type[Any]:
    """Klassendekorator: registriert einen API-Adapter unter seiner `adapter_id`."""
    _API_ADAPTERS[cls.adapter_id] = cls
    return cls


def adapter_kind(adapter_id: str) -> Literal["profile", "api"]:
    """Sagt, ob `adapter_id` ein CLI-Profil oder ein API-Adapter ist (sonst Fehler)."""
    if adapter_id in _PROFILES:
        return "profile"
    if adapter_id in _API_ADAPTERS:
        return "api"
    raise UnknownAdapterError(adapter_id)


def get_profile(adapter_id: str) -> VendorProfile:
    """Liefert das Vendor-Profil zur `adapter_id` oder wirft :class:`UnknownAdapterError`."""
    try:
        return _PROFILES[adapter_id]
    except KeyError as exc:
        raise UnknownAdapterError(adapter_id) from exc


def get_api_adapter_class(adapter_id: str) -> type[Any]:
    """Liefert die API-Adapter-Klasse zur `adapter_id` oder wirft :class:`UnknownAdapterError`."""
    try:
        return _API_ADAPTERS[adapter_id]
    except KeyError as exc:
        raise UnknownAdapterError(adapter_id) from exc


def build_adapter(adapter_id: str, transport: CommandTransport) -> SwitchAdapter:
    """Baut einen CLI-Adapter (DeclarativeAdapter) über dem gegebenen Transport."""
    return DeclarativeAdapter(get_profile(adapter_id), transport)


def available_adapters() -> dict[str, frozenset[Capability]]:
    """Mappt jede registrierte `adapter_id` (CLI **und** API) auf ihre Capabilities."""
    catalogue: dict[str, frozenset[Capability]] = {
        adapter_id: frozenset(profile.capabilities) for adapter_id, profile in _PROFILES.items()
    }
    for adapter_id, cls in _API_ADAPTERS.items():
        catalogue[adapter_id] = frozenset(cls.capabilities_set)
    return catalogue


def provenance_for(adapter_id: str) -> str | None:
    """Provenance/Herkunft eines Adapters (Profil-Feld bzw. API-Klassen-Attribut)."""
    if adapter_id in _PROFILES:
        return _PROFILES[adapter_id].provenance
    if adapter_id in _API_ADAPTERS:
        return getattr(_API_ADAPTERS[adapter_id], "provenance", None)
    return None
