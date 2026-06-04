"""Generischer Conformance-Test über ALLE registrierten Vendor-Profile.

Für jede Profil-/Capability-Kombination wird der zugehörige Befehl gegen eine Fixture-Datei
(``fixtures/<adapter_id>/<command mit _ statt Leerzeichen>.txt``) geparst und das Ergebnis
auf gültige DTOs geprüft. Ein neues Vendor-Profil ist erst „fertig", wenn es hier grün ist —
das ist das Qualitätsgate für handgeschriebene wie KI-/doku-abgeleitete Profile.
"""

from pathlib import Path

import pytest

from netbuddy.adapters import MockTransport, available_adapters, build_adapter
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.dto import (
    InterfaceData,
    LldpNeighborData,
    MacEntryData,
    SystemInfo,
)
from netbuddy.adapters.registry import adapter_kind, get_profile

_FIXTURES = Path(__file__).parent / "fixtures"

# Capability → (Methodenname, erwarteter DTO-Typ, ist Liste?)
_METHODS = {
    Capability.READ_SYSTEM_INFO: ("get_system_info", SystemInfo, False),
    Capability.READ_INTERFACES: ("get_interfaces", InterfaceData, True),
    Capability.READ_LLDP: ("get_lldp_neighbors", LldpNeighborData, True),
    Capability.READ_MAC_TABLE: ("get_mac_table", MacEntryData, True),
}


def _fixture_file(adapter_id: str, command: str) -> Path:
    return _FIXTURES / adapter_id / f"{command.replace(' ', '_')}.txt"


def _cases() -> list[tuple[str, Capability]]:
    # Nur CLI/Profil-Adapter haben Fixtures; API-Adapter (z.B. unifi) sind hier nicht relevant.
    return [
        (adapter_id, capability)
        for adapter_id in available_adapters()
        if adapter_kind(adapter_id) == "profile"
        for capability in get_profile(adapter_id).capabilities
    ]


@pytest.mark.parametrize(
    ("adapter_id", "capability"),
    _cases(),
    ids=[f"{a}:{c.value}" for a, c in _cases()],
)
async def test_profile_capability_parses_to_valid_dtos(
    adapter_id: str, capability: Capability
) -> None:
    spec = get_profile(adapter_id).capabilities[capability]
    responses: dict[str, str] = {}
    for source in spec.sources:
        fixture = _fixture_file(adapter_id, source.command)
        assert fixture.exists(), f"Fehlende Fixture für {adapter_id}/{source.command!r}: {fixture}"
        responses[source.command] = fixture.read_text()

    adapter = build_adapter(adapter_id, MockTransport(responses))
    method_name, dto_type, is_list = _METHODS[capability]
    result = await getattr(adapter, method_name)()

    if is_list:
        assert isinstance(result, list)
        assert result, f"{adapter_id}/{capability} lieferte keine Einträge"
        assert all(isinstance(item, dto_type) for item in result)
    else:
        assert isinstance(result, dto_type)
