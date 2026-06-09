import asyncio
import re
from collections.abc import Callable
from types import TracebackType
from typing import Protocol

import asyncssh
from scrapli import AsyncScrapli
from scrapli.driver.generic import AsyncGenericDriver

from netbuddy.adapters.connection import ConnectionParams
from netbuddy.adapters.transport import TransportError

# Sentinel-Plattform für Vendor ohne scrapli-Core-Treiber → AsyncGenericDriver.
_GENERIC = "generic"

# Prompt-Ende einer CLI-Zeile (exec/config/interface): endet auf > oder # (+ optional Space).
_PROMPT_END = re.compile(r"[>#]\s*$")

# Nur lesende Befehle dürfen über diesen Transport laufen (read-only first).
_READ_ONLY_PREFIXES = ("show", "display")
# Hilfe-/Discovery-Befehle (für assistiertes Onboarding) sind ebenfalls lesend.
_HELP_COMMANDS = {"?", "help", "list"}


def _is_read_only(command: str) -> bool:
    text = command.strip().lower()
    return text.startswith(_READ_ONLY_PREFIXES) or text in _HELP_COMMANDS or text.endswith("?")


class _CommandResult(Protocol):
    result: str


class _AsyncDriver(Protocol):
    """Strukturelle Sicht auf die von uns genutzten Scrapli-Async-Methoden."""

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def send_command(self, command: str) -> _CommandResult: ...


DriverFactory = Callable[[ConnectionParams], _AsyncDriver]


def _build_async_scrapli(params: ConnectionParams) -> _AsyncDriver:
    password = params.password.get_secret_value() if params.password else ""
    if params.platform == _GENERIC:
        # Kein Vendor-Treiber: GenericDriver kennt keine Privilege-Escalation (auth_secondary),
        # reicht aber für read-only `show`/`display`.
        return AsyncGenericDriver(
            host=params.host,
            port=params.port,
            auth_username=params.username,
            auth_password=password,
            transport="asyncssh",
            auth_strict_key=False,
        )
    return AsyncScrapli(
        host=params.host,
        port=params.port,
        platform=params.platform,
        auth_username=params.username,
        auth_password=password,
        auth_secondary=(
            params.enable_password.get_secret_value() if params.enable_password else ""
        ),
        transport="asyncssh",
        auth_strict_key=False,
    )


class ScrapliTransport:
    """Echter async SSH-Transport auf Scrapli-Basis.

    Implementiert das :class:`~netbuddy.adapters.transport.CommandTransport`-Protocol
    und ist zugleich ein async Context-Manager, damit die Verbindung einmal geöffnet
    und über mehrere Adapter-Aufrufe gehalten wird::

        transport = ScrapliTransport(params_from_credential(device, credential))
        async with transport:
            info = await CiscoIosAdapter(transport).get_system_info()

    Der ``driver_factory`` ist injizierbar, damit Tests ohne echte Hardware laufen.
    """

    def __init__(
        self,
        params: ConnectionParams,
        *,
        driver_factory: DriverFactory = _build_async_scrapli,
    ) -> None:
        self._driver = driver_factory(params)
        self._paging_command = params.paging_command
        self._params = params

    async def open(self) -> None:
        await self._driver.open()
        # Pager direkt am Treiber abschalten (am Read-only-Guard vorbei: reine Session-
        # Einstellung). Ohne das hängt der GenericDriver bei langen Ausgaben am `--More--`.
        if self._paging_command:
            await self._driver.send_command(self._paging_command)

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> "ScrapliTransport":
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def send_command(self, command: str) -> str:
        if not _is_read_only(command):
            raise TransportError(f"Nur lesende Befehle erlaubt, abgelehnt: {command!r}")
        response = await self._driver.send_command(command)
        return response.result

    async def send_config(self, lines: list[str]) -> str:
        """Expliziter Schreibpfad (NICHT read-only-guarded) — nur für autorisierte Änderungen.

        Sendet die Zeilen **wörtlich** (inkl. ``configure terminal``/``exit`` etc. — der Aufrufer
        bzw. das Profil liefert die komplette Sequenz). Nutzt eine eigene interaktive
        asyncssh-Shell statt des scrapli-GenericDrivers: Letzterer kommt mit Config-Mode-Prompt-
        Wechseln (``(config)#``/``(config-if)#``) nicht zurecht. Aufrufer ist für die
        Berechtigung verantwortlich (LLDP-Endpoint mit Backup + Audit), nicht dieser Transport.
        """
        p = self._params
        password = p.password.get_secret_value() if p.password else None
        async with asyncssh.connect(
            p.host,
            port=p.port,
            username=p.username,
            password=password,
            known_hosts=None,
        ) as conn:
            proc = await conn.create_process(term_type="vt100")

            async def read_to_prompt(wait: float = 2.5) -> str:
                """Liest bis zum nächsten CLI-Prompt (oder ``wait`` s Stille als Fallback)."""
                buf = ""
                try:
                    while not _PROMPT_END.search(buf):
                        buf += await asyncio.wait_for(proc.stdout.read(4096), timeout=wait)
                except TimeoutError:
                    pass
                return buf

            await read_to_prompt(5.0)  # Login-Banner/erster Prompt
            # Pro Zeile senden UND lesen — nicht alle Zeilen am Stück (sonst füllt sich der
            # Kanal und das Gerät trennt: BrokenPipe). Kurzer Timeout hält es flott.
            results: list[str] = []
            for line in lines:
                proc.stdin.write(line + "\n")
                results.append(await read_to_prompt())
            proc.stdin.write("exit\n")
        return "\n".join(results)
