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


class RecordingTransport:
    """Dekoriert einen Transport und merkt sich jeden Befehl + dessen Roh-Output.

    Nützlich für die Validierung: das geparste Ergebnis kommt vom Adapter, der rohe
    CLI-Output (als Referenz-Capture) steht danach in :attr:`calls`.
    """

    def __init__(self, inner: "CommandTransport") -> None:
        self._inner = inner
        self.calls: dict[str, str] = {}

    async def send_command(self, command: str) -> str:
        output = await self._inner.send_command(command)
        self.calls[command] = output
        return output


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
