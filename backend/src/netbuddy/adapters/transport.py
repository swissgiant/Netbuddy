from typing import Protocol


class TransportError(RuntimeError):
    """Raised when a transport cannot satisfy a command."""


class CommandTransport(Protocol):
    """Abstrahiert das Absetzen eines CLI-Befehls und liefert dessen Rohtext.

    Adapter sprechen nie direkt SSH/SNMP — sie bekommen einen Transport
    injiziert. Die echte Scrapli/Netmiko-Implementierung folgt später; bis
    dahin (und in Tests) dient :class:`MockTransport`.
    """

    async def send_command(self, command: str) -> str: ...


class MockTransport:
    """Transport mit fest hinterlegten Antworten — für Tests und lokale Demos.

    Beispiel::

        transport = MockTransport({"show version": "..."})
        adapter = CiscoIosAdapter(transport)
    """

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    async def send_command(self, command: str) -> str:
        try:
            return self._responses[command]
        except KeyError as exc:
            raise TransportError(f"Kein Mock-Output für Befehl: {command!r}") from exc
