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
from netbuddy.adapters.profile import CapabilitySpec, VendorProfile
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

    async def _rows(self, capability: Capability) -> tuple[CapabilitySpec, list[dict[str, Any]]]:
        spec = self._profile.capabilities.get(capability)
        if spec is None:
            raise CapabilityNotSupportedError(self.adapter_id, capability)
        raw = await self._transport.send_command(spec.command)
        rows = parse(
            spec.parser,
            ntc_platform=self._profile.ntc_platform,
            command=spec.command,
            data=raw,
        )
        return spec, rows

    @staticmethod
    def _drop_empty[T: BaseModel](items: list[T], fields: list[str]) -> list[T]:
        if not fields:
            return items
        return [it for it in items if all(getattr(it, f) is not None for f in fields)]

    async def get_system_info(self) -> SystemInfo:
        spec, rows = await self._rows(Capability.READ_SYSTEM_INFO)
        row = rows[0] if rows else {}
        return build_dto(SystemInfo, spec.fields, row)

    async def get_interfaces(self) -> list[InterfaceData]:
        spec, rows = await self._rows(Capability.READ_INTERFACES)
        items = [build_dto(InterfaceData, spec.fields, row) for row in rows]
        return self._drop_empty(items, spec.drop_when_empty)

    async def get_lldp_neighbors(self) -> list[LldpNeighborData]:
        spec, rows = await self._rows(Capability.READ_LLDP)
        items = [build_dto(LldpNeighborData, spec.fields, row) for row in rows]
        return self._drop_empty(items, spec.drop_when_empty)

    async def get_mac_table(self) -> list[MacEntryData]:
        spec, rows = await self._rows(Capability.READ_MAC_TABLE)
        items = [build_dto(MacEntryData, spec.fields, row) for row in rows]
        return self._drop_empty(items, spec.drop_when_empty)
