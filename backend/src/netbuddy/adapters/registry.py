from netbuddy.adapters.base import AdapterError, SwitchAdapter
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.declarative import DeclarativeAdapter
from netbuddy.adapters.profile import VendorProfile, load_profiles_from_package
from netbuddy.adapters.transport import CommandTransport

# adapter_id → Profil, beim Import aus adapters/profiles/*.yaml geladen.
_PROFILES: dict[str, VendorProfile] = load_profiles_from_package()


class UnknownAdapterError(AdapterError):
    """Es gibt kein Vendor-Profil für die angefragte `adapter_id`."""

    def __init__(self, adapter_id: str) -> None:
        super().__init__(f"Kein Profil registriert für {adapter_id!r}")
        self.adapter_id = adapter_id


def get_profile(adapter_id: str) -> VendorProfile:
    """Liefert das Vendor-Profil zur `adapter_id` oder wirft :class:`UnknownAdapterError`."""
    try:
        return _PROFILES[adapter_id]
    except KeyError as exc:
        raise UnknownAdapterError(adapter_id) from exc


def build_adapter(adapter_id: str, transport: CommandTransport) -> SwitchAdapter:
    """Baut einen einsatzbereiten Adapter für die `adapter_id` über dem gegebenen Transport."""
    return DeclarativeAdapter(get_profile(adapter_id), transport)


def available_adapters() -> dict[str, frozenset[Capability]]:
    """Mappt jede registrierte `adapter_id` auf ihre Capabilities (für Frontend-Graying)."""
    return {
        adapter_id: frozenset(profile.capabilities) for adapter_id, profile in _PROFILES.items()
    }
