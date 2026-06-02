import pytest

from netbuddy.adapters import (
    Capability,
    CiscoIosAdapter,
    UnknownAdapterError,
    available_adapters,
    get_adapter_class,
)


def test_cisco_ios_is_registered() -> None:
    assert get_adapter_class("cisco_ios") is CiscoIosAdapter


def test_unknown_adapter_raises() -> None:
    with pytest.raises(UnknownAdapterError):
        get_adapter_class("does_not_exist")


def test_available_adapters_reports_cisco_capabilities() -> None:
    catalogue = available_adapters()
    assert catalogue["cisco_ios"] == frozenset(
        {
            Capability.READ_SYSTEM_INFO,
            Capability.READ_INTERFACES,
            Capability.READ_LLDP,
            Capability.READ_MAC_TABLE,
        }
    )
