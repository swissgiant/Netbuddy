import pytest
from pydantic import ValidationError

from netbuddy.adapters import MockTransport, build_adapter
from netbuddy.adapters.profile import load_profile

_SHORTHAND = """
adapter_id: test_shorthand
capabilities:
  read_system_info:
    command: "show version"
    parser: "ntc"
    fields:
      hostname: { from: hostname }
"""

_MULTISOURCE = """
adapter_id: test_multi
ntc_platform: cisco_ios
capabilities:
  read_interfaces:
    sources:
      - { command: "show a", parser: ntc }
      - { command: "show b", parser: ntc }
    fields:
      name: { from: interface }
"""


def test_command_shorthand_normalizes_to_single_source() -> None:
    profile = load_profile(_SHORTHAND)
    spec = profile.capabilities[next(iter(profile.capabilities))]
    assert len(spec.sources) == 1
    assert spec.sources[0].command == "show version"
    assert spec.sources[0].parser == "ntc"


def test_capability_without_command_or_sources_is_invalid() -> None:
    with pytest.raises(ValidationError):
        load_profile(
            "adapter_id: bad\ncapabilities:\n  read_system_info:\n    fields: {name: {from: x}}\n"
        )


async def test_list_capability_rejects_multiple_sources() -> None:
    # read_interfaces ist list-arity → mehr als eine Quelle ist zur Laufzeit ein Fehler.
    profile = load_profile(_MULTISOURCE)
    from netbuddy.adapters.declarative import DeclarativeAdapter

    adapter = DeclarativeAdapter(profile, MockTransport({"show a": "", "show b": ""}))
    with pytest.raises(ValueError, match="genau eine Quelle"):
        await adapter.get_interfaces()


def test_build_adapter_unknown_profile_via_registry() -> None:
    from netbuddy.adapters import UnknownAdapterError

    with pytest.raises(UnknownAdapterError):
        build_adapter("nope", MockTransport({}))
