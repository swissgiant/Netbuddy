from netbuddy.adapters.base import AdapterError, SwitchAdapter
from netbuddy.adapters.capabilities import Capability

_REGISTRY: dict[str, type[SwitchAdapter]] = {}


class UnknownAdapterError(AdapterError):
    """Es gibt keinen registrierten Adapter für die angefragte `adapter_id`."""

    def __init__(self, adapter_id: str) -> None:
        super().__init__(f"Kein Adapter registriert für {adapter_id!r}")
        self.adapter_id = adapter_id


def register_adapter(cls: type[SwitchAdapter]) -> type[SwitchAdapter]:
    """Klassendekorator: registriert einen Adapter unter seiner `adapter_id`."""
    adapter_id = cls.adapter_id
    existing = _REGISTRY.get(adapter_id)
    if existing is not None and existing is not cls:
        raise ValueError(f"adapter_id {adapter_id!r} bereits von {existing!r} belegt")
    _REGISTRY[adapter_id] = cls
    return cls


def get_adapter_class(adapter_id: str) -> type[SwitchAdapter]:
    """Liefert die Adapter-Klasse zur `adapter_id` oder wirft :class:`UnknownAdapterError`."""
    try:
        return _REGISTRY[adapter_id]
    except KeyError as exc:
        raise UnknownAdapterError(adapter_id) from exc


def available_adapters() -> dict[str, frozenset[Capability]]:
    """Mappt jede registrierte `adapter_id` auf ihre gemeldeten Capabilities."""
    return {adapter_id: cls.capabilities() for adapter_id, cls in _REGISTRY.items()}
