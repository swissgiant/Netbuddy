from typing import Protocol, runtime_checkable

from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)


class AdapterError(RuntimeError):
    """Basisklasse für Adapter-Fehler."""


class CapabilityNotSupportedError(AdapterError):
    """Eine angeforderte Read-Methode wird von diesem Adapter nicht unterstützt."""

    def __init__(self, adapter_id: str, capability: Capability) -> None:
        super().__init__(f"Adapter {adapter_id!r} unterstützt {capability} nicht")
        self.adapter_id = adapter_id
        self.capability = capability


@runtime_checkable
class SwitchAdapter(Protocol):
    """Einheitliche, vendor-unabhängige Read-Schnittstelle zu einem Switch.

    Standard-Implementierung ist :class:`~netbuddy.adapters.declarative.DeclarativeAdapter`,
    der ein YAML-Vendor-Profil interpretiert. Welche Methoden wirklich nutzbar sind, meldet
    :meth:`capabilities`; ein Aufruf einer nicht gemeldeten Methode wirft
    :class:`CapabilityNotSupportedError`.
    """

    adapter_id: str

    def capabilities(self) -> frozenset[Capability]: ...

    async def get_system_info(self) -> SystemInfo: ...

    async def get_interfaces(self) -> list[InterfaceData]: ...

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]: ...

    async def get_mac_table(self) -> list[MacEntryData]: ...
