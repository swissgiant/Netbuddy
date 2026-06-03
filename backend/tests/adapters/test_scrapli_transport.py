from dataclasses import dataclass, field
from pathlib import Path

import pytest

from netbuddy.adapters import (
    ConnectionParams,
    ScrapliTransport,
    TransportError,
    build_adapter,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "cisco_ios"


@dataclass
class _Result:
    result: str


@dataclass
class _FakeDriver:
    """Steht für eine Scrapli-Async-Verbindung — ohne echte Hardware."""

    responses: dict[str, str] = field(default_factory=dict)
    opened: bool = False
    closed: bool = False
    commands: list[str] = field(default_factory=list)

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def send_command(self, command: str) -> _Result:
        self.commands.append(command)
        return _Result(result=self.responses.get(command, ""))


def _params() -> ConnectionParams:
    return ConnectionParams(host="10.0.0.1", username="svc", platform="cisco_iosxe")


def _transport_with(driver: _FakeDriver) -> ScrapliTransport:
    return ScrapliTransport(_params(), driver_factory=lambda _params: driver)


async def test_context_manager_opens_and_closes() -> None:
    driver = _FakeDriver(responses={"show version": "ok"})
    transport = _transport_with(driver)

    assert not driver.opened
    async with transport:
        assert driver.opened and not driver.closed
        assert await transport.send_command("show version") == "ok"
    assert driver.closed


async def test_send_command_rejects_non_read_commands() -> None:
    driver = _FakeDriver()
    transport = _transport_with(driver)
    for blocked in ("configure terminal", "conf t", "reload", "write memory"):
        with pytest.raises(TransportError, match="Nur lesende Befehle"):
            await transport.send_command(blocked)
    assert driver.commands == []  # nichts ging an den Driver raus


async def test_adapter_runs_against_fake_driver_end_to_end() -> None:
    # Der Adapter spricht über den echten ScrapliTransport, nur der Driver ist fake.
    responses = {
        "show version": (_FIXTURES / "show_version.txt").read_text(),
        "show interfaces": (_FIXTURES / "show_interfaces.txt").read_text(),
    }
    driver = _FakeDriver(responses=responses)
    transport = _transport_with(driver)
    adapter = build_adapter("cisco_ios", transport)

    async with transport:
        info = await adapter.get_system_info()
        interfaces = await adapter.get_interfaces()

    assert info.hostname == "sw-lab-01"
    assert [i.name for i in interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
    ]
    assert driver.commands == ["show version", "show interfaces"]
