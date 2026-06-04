from pathlib import Path

from netbuddy.adapters import MockTransport, build_adapter
from netbuddy.services.validation import (
    CapabilityStatus,
    DeviceValidationReport,
    validate_adapter,
)

_FIXTURES = Path(__file__).parent.parent / "adapters" / "fixtures" / "dell_os10"
_COMMANDS = {
    "show version": "show_version.txt",
    "show license status": "show_license_status.txt",
    "show interface status": "show_interface_status.txt",
    "show lldp neighbors detail": "show_lldp_neighbors_detail.txt",
    "show mac address-table": "show_mac_address-table.txt",
}


def _responses() -> dict[str, str]:
    return {cmd: (_FIXTURES / f).read_text() for cmd, f in _COMMANDS.items()}


def _status(report: DeviceValidationReport, capability_value: str) -> CapabilityStatus:
    return next(c.status for c in report.capabilities if c.capability.value == capability_value)


async def test_all_ok_with_coverage() -> None:
    report = await validate_adapter(build_adapter("dell_os10", MockTransport(_responses())))
    assert report.healthy is True
    assert all(c.status is CapabilityStatus.OK for c in report.capabilities)
    sysinfo = next(c for c in report.capabilities if c.capability.value == "read_system_info")
    assert sysinfo.row_count == 1
    assert sysinfo.coverage["model"] == 1.0
    assert sysinfo.coverage["hostname"] == 0.0  # OS10 zeigt Hostname nicht im show-Output


async def test_empty_command_yields_empty_status() -> None:
    responses = {**_responses(), "show interface status": ""}
    report = await validate_adapter(build_adapter("dell_os10", MockTransport(responses)))
    assert _status(report, "read_interfaces") is CapabilityStatus.EMPTY
    assert report.healthy is True  # empty ist kein Fehler


async def test_missing_command_yields_error_and_unhealthy() -> None:
    responses = {k: v for k, v in _responses().items() if k != "show mac address-table"}
    report = await validate_adapter(build_adapter("dell_os10", MockTransport(responses)))
    mac = next(c for c in report.capabilities if c.capability.value == "read_mac_table")
    assert mac.status is CapabilityStatus.ERROR
    assert mac.message is not None
    assert report.healthy is False
