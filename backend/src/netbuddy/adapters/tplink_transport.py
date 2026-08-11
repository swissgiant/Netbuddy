"""CLI-Transport für TP-Link JetStream/Omada (z.B. TL-SG2428P).

Diese Switches sind speziell: die CLI verlangt **`\\r`** als Zeilenende (nicht `\\n`) und
pagt lange Ausgaben mit ``Press any key to continue (Q to quit)`` — nicht abschaltbar. Beides
kommt scraplis ``send_command`` nicht zurecht (Timeout). Daher ein eigener, schlanker Transport
auf roher ``asyncssh``-Shell: hält die Session offen, schaltet ggf. in den Enable-Mode, blättert
selbst durch den Pager und liefert sauberen Befehls-Output an die Adapter/TextFSM-Schicht.
"""

import asyncio
import re
from types import TracebackType

import asyncssh

from netbuddy.adapters.connection import ConnectionParams
from netbuddy.adapters.scrapli_transport import _is_read_only
from netbuddy.adapters.transport import TransportError

_PROMPT = re.compile(r"[>#]\s*$")
_PAGER = "press any key to continue"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class TplinkTransport:
    """Persistente SSH-Shell zu einem TP-Link-JetStream-Switch (CR-Zeilenende + Pager)."""

    def __init__(self, params: ConnectionParams) -> None:
        self._params = params
        self._conn: asyncssh.SSHClientConnection | None = None
        self._proc: asyncssh.SSHClientProcess[str] | None = None

    async def __aenter__(self) -> "TplinkTransport":
        p = self._params
        self._conn = await asyncssh.connect(
            p.host,
            port=p.port,
            username=p.username,
            password=p.password.get_secret_value() if p.password else None,
            known_hosts=None,
        )
        try:
            self._proc = await self._conn.create_process(term_type="vt100")
            await self._read(5.0)  # Login-Banner/erster Prompt
            if p.enable_required:
                self._proc.stdin.write("enable\r")
                await self._read()
        except BaseException:
            # Wirft __aenter__ nach connect(), läuft __aexit__ nie → SSH-Verbindung leakt.
            self._conn.close()
            self._conn = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
            self._conn.close()

    async def _read(self, wait: float = 3.0) -> str:
        """Liest bis zum CLI-Prompt; blättert dabei selbst durch den Pager (Space)."""
        assert self._proc is not None
        buf = ""
        while True:
            try:
                chunk = await asyncio.wait_for(self._proc.stdout.read(4096), timeout=wait)
            except TimeoutError:
                break
            buf += chunk
            if _PAGER in chunk.lower():
                self._proc.stdin.write(" ")  # nächste Seite
                continue
            tail = buf.splitlines()[-1] if buf.splitlines() else ""
            if _PROMPT.search(_ANSI.sub("", tail)):
                break
        return buf

    @staticmethod
    def _clean(raw: str, command: str) -> str:
        """Echo, Pager-Zeilen, ANSI-Sequenzen und die Prompt-Zeile entfernen."""
        out: list[str] = []
        for line in raw.splitlines():
            line = _ANSI.sub("", line.replace("\x00", "")).rstrip()
            stripped = line.strip()
            if stripped == command.strip():
                continue
            if _PAGER in stripped.lower():
                continue
            if _PROMPT.search(line) and len(stripped) < 40:
                continue  # Prompt-Zeile (z.B. "SG2428P#")
            out.append(line)
        return "\n".join(out).strip("\n")

    async def send_command(self, command: str) -> str:
        if not _is_read_only(command):
            raise TransportError(f"Nur lesende Befehle erlaubt, abgelehnt: {command!r}")
        assert self._proc is not None
        self._proc.stdin.write(command + "\r")
        return self._clean(await self._read(), command)

    async def send_config(self, lines: list[str]) -> str:
        """Schreibpfad (NICHT read-only-guarded) — nur für autorisierte Änderungen."""
        assert self._proc is not None
        results: list[str] = []
        for line in lines:
            self._proc.stdin.write(line + "\r")
            results.append(await self._read())
        return "\n".join(results)
