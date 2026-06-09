import pytest

from netbuddy.adapters import (
    Capability,
    DeclarativeAdapter,
    MockTransport,
    UnknownAdapterError,
    available_adapters,
    build_adapter,
    get_profile,
)

_CISCO_CAPS = frozenset(
    {
        Capability.READ_SYSTEM_INFO,
        Capability.READ_INTERFACES,
        Capability.READ_LLDP,
        Capability.READ_MAC_TABLE,
        Capability.READ_ARP,
    }
)


def test_cisco_profile_is_registered() -> None:
    profile = get_profile("cisco_ios")
    assert profile.adapter_id == "cisco_ios"
    assert frozenset(profile.capabilities) == _CISCO_CAPS


def test_build_adapter_returns_declarative_adapter() -> None:
    adapter = build_adapter("cisco_ios", MockTransport({}))
    assert isinstance(adapter, DeclarativeAdapter)
    assert adapter.adapter_id == "cisco_ios"
    assert adapter.capabilities() >= _CISCO_CAPS  # + READ_CONFIG (backup_command gesetzt)


def test_unknown_adapter_raises() -> None:
    with pytest.raises(UnknownAdapterError):
        get_profile("does_not_exist")
    with pytest.raises(UnknownAdapterError):
        build_adapter("does_not_exist", MockTransport({}))


def test_available_adapters_reports_cisco_capabilities() -> None:
    assert available_adapters()["cisco_ios"] == _CISCO_CAPS
