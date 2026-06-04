from typing import Any

from pydantic import BaseModel

from netbuddy.adapters.base import CapabilityNotSupportedError
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.adapters.mapping import build_dto
from netbuddy.adapters.parsers import parse
from netbuddy.adapters.profile import CapabilitySpec, SourceSpec, VendorProfile
from netbuddy.adapters.transport import CommandTransport


class DeclarativeAdapter:
    """Vendor-Adapter, der ein :class:`VendorProfile` interpretiert.

    Erfüllt das :class:`~netbuddy.adapters.base.SwitchAdapter`-Protocol; ein Vendor wird allein
    durch sein YAML-Profil + Fixtures definiert, nicht durch eigenen Code.
    """

    def __init__(self, profile: VendorProfile, transport: CommandTransport) -> None:
        self._profile = profile
        self._transport = transport
        self.adapter_id = profile.adapter_id

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(self._profile.capabilities)

    def _capability(self, capability: Capability) -> CapabilitySpec:
        spec = self._profile.capabilities.get(capability)
        if spec is None:
            raise CapabilityNotSupportedError(self.adapter_id, capability)
        return spec

    async def _parse_source(self, source: SourceSpec) -> list[dict[str, Any]]:
        raw = await self._transport.send_command(source.command)
        return parse(
            source.parser,
            ntc_platform=self._profile.ntc_platform,
            command=source.command,
            data=raw,
        )

    async def _merged_row(self, spec: CapabilitySpec) -> dict[str, Any]:
        """Erste Zeile jeder Quelle zu einem Dict mergen (leere Felder werden aufgefüllt)."""
        merged: dict[str, Any] = {}
        for source in spec.sources:
            rows = await self._parse_source(source)
            row0 = rows[0] if rows else {}
            for key, value in row0.items():
                if merged.get(key) in (None, ""):
                    merged[key] = value
        return merged

    async def _list_rows(
        self, capability: Capability
    ) -> tuple[CapabilitySpec, list[dict[str, Any]]]:
        spec = self._capability(capability)
        if len(spec.sources) != 1:
            raise ValueError(
                f"{capability} (Liste) erlaubt genau eine Quelle, hat {len(spec.sources)}"
            )
        return spec, await self._parse_source(spec.sources[0])

    @staticmethod
    def _drop_empty[T: BaseModel](items: list[T], fields: list[str]) -> list[T]:
        if not fields:
            return items
        return [it for it in items if all(getattr(it, f) is not None for f in fields)]

    async def get_system_info(self) -> SystemInfo:
        spec = self._capability(Capability.READ_SYSTEM_INFO)
        return build_dto(SystemInfo, spec.fields, await self._merged_row(spec))

    async def get_interfaces(self) -> list[InterfaceData]:
        spec, rows = await self._list_rows(Capability.READ_INTERFACES)
        items = [build_dto(InterfaceData, spec.fields, row) for row in rows]
        return self._drop_empty(items, spec.drop_when_empty)

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        spec, rows = await self._list_rows(Capability.READ_LLDP)
        items = [build_dto(LldpNeighborData, spec.fields, row) for row in rows]
        return self._drop_empty(items, spec.drop_when_empty)

    async def get_mac_table(self) -> list[MacEntryData]:
        spec, rows = await self._list_rows(Capability.READ_MAC_TABLE)
        items = [build_dto(MacEntryData, spec.fields, row) for row in rows]
        return self._drop_empty(items, spec.drop_when_empty)
