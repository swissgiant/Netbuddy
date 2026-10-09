"""Roher asyncssh-Shell-Transport für CLIs, die scraplis Treiber nicht sauber bedienen.

Gedacht für Vendor mit „eigenwilligen" Terminals:

- **ArubaOS-Switch / ProCurve** (HP 2530/2920/2540/5400R): VT100-Bildschirmsteuerung mit
  Escape-Sequenzen, ``Press any key to continue``-Banner nach dem Login, Pager ``-- MORE --``,
  Pager-Abschaltung ``no page``.
- **Huawei VRP** (S6730, CloudEngine): Prompt ``<name>`` bzw. ``[name]`` (scraplis Generic-
  Prompt-Pattern kennt keine spitzen Klammern), Pager ``---- More ----``, Abschaltung
  ``screen-length 0 temporary``.
- **Cisco Small Business** (SG300/CBS350): manche Geräte fragen nach dem SSH-Login nochmal
  in-band ``User Name:``/``Password:``; Pager ``More: <space>``, Abschaltung ``terminal datadump``.

Hält eine Shell offen, blättert selbst durch den Pager, entfernt Echo/ANSI/Prompt und liefert
sauberen Befehls-Output an die Adapter-/TextFSM-Schicht. Read-only-Guard wie beim Scrapli-
Transport; ``send_config`` ist der explizite, nicht geguardete Schreibpfad (LLDP/VLAN).
"""

import asyncio
import re
from dataclasses import dataclass
from types import TracebackType

import asyncssh

from netbuddy.adapters.connection import ConnectionParams
from netbuddy.adapters.scrapli_transport import _is_read_only
from netbuddy.adapters.transport import TransportError

# Prompt-Zeile: `name#`, `name>`, `name(config)#`, Huawei `<name>` / `[name-Gi0/0/1]`.
_PROMPT = re.compile(r"^(<[^<>\s]+>|\[[^\[\]\s]+\]|[\w\-.()/:]{1,80}[#>])\s*$")
# ANSI/VT100: CSI-Sequenzen, Zeichensatz-Umschaltung, OSC, Einzel-Escapes (ESC E = Newline).
_ANSI_NL = re.compile(r"\x1bE")
# "Zeile löschen" (ESC[2K): ProCurve überschreibt damit die Pager-Zeile → Zeileninhalt davor weg.
_ERASE_LINE = re.compile(r"[^\r\n]*\x1b\[2K")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>()][A-Za-z0-9]?|\x1b\][^\x07]*\x07|\x1b[A-Za-z]")

# Alte Firmware (ProCurve 2510/2530 mit OpenSSH 3.x, Cisco SB) kann nur Legacy-Algorithmen —
# asyncssh bietet die nicht von sich aus an; zweiter Versuch mit erweiterter Liste.
_LEGACY_KEX = ["diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1"]
_LEGACY_KEX += ["diffie-hellman-group-exchange-sha1"]
_LEGACY_ENC = ["aes128-cbc", "aes256-cbc", "3des-cbc"]
_LEGACY_MAC = ["hmac-sha1", "hmac-md5"]
_LEGACY_HOSTKEY = ["ssh-rsa", "rsa-sha2-256", "rsa-sha2-512", "ssh-dss"]
_LEGACY_HOSTKEY += ["ecdsa-sha2-nistp256", "ssh-ed25519"]


@dataclass(frozen=True)
class ShellDialect:
    """Terminal-Eigenheiten einer CLI-Familie (siehe :data:`DIALECTS`)."""

    paging_command: str | None
    pagers: tuple[str, ...]
    banner_continue: bool = False  # "Press any key to continue" nach dem Login wegdrücken
    inband_login: bool = False  # Gerät fragt nach SSH-Auth nochmal "User Name:"/"Password:"
    line_end: str = "\n"


DIALECTS: dict[str, ShellDialect] = {
    "aruba_procurve": ShellDialect(
        "no page", ("-- MORE --", "Press any key to continue"), banner_continue=True
    ),
    "huawei_vrp": ShellDialect("screen-length 0 temporary", ("---- More ----",)),
    "cisco_sb": ShellDialect("terminal datadump", ("More: <space>",), inband_login=True),
}


async def connect_with_legacy_fallback(
    host: str, *, port: int, username: str, password: str | None, connect_timeout: float = 20.0
) -> asyncssh.SSHClientConnection:
    """SSH-Verbindung; schlägt der Algorithmus-Handshake fehl, nochmal mit Legacy-Algorithmen."""
    opts: dict[str, object] = {
        "port": port,
        "username": username,
        "password": password,
        "known_hosts": None,
        "connect_timeout": connect_timeout,
    }
    try:
        return await asyncssh.connect(host, **opts)
    except (asyncssh.KeyExchangeFailed, asyncssh.ConnectionLost, OSError):
        kex = [a.decode() for a in asyncssh.kex.get_kex_algs()] + _LEGACY_KEX
        enc = [a.decode() for a in asyncssh.encryption.get_encryption_algs()] + _LEGACY_ENC
        mac = [a.decode() for a in asyncssh.mac.get_mac_algs()] + _LEGACY_MAC
        return await asyncssh.connect(
            host,
            kex_algs=kex,
            encryption_algs=enc,
            mac_algs=mac,
            server_host_key_algs=_LEGACY_HOSTKEY,
            **opts,
        )


def strip_ansi(text: str) -> str:
    """VT100-/ANSI-Steuersequenzen entfernen (ESC E = Zeilenschaltung, ESC[2K = Zeile löschen)."""
    text = _ERASE_LINE.sub("", _ANSI_NL.sub("\n", text))
    return _ANSI.sub("", text).replace("\x00", "")


def clean_output(raw: str, command: str, pagers: tuple[str, ...]) -> str:
    """Echo, Pager-Zeilen, ANSI-Sequenzen, Login-Hinweise und die Prompt-Zeile entfernen."""
    out: list[str] = []
    lines = strip_ansi(raw).replace("\r", "").split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if (
            index < 4
            and (stripped == command.strip() or stripped.endswith(command.strip()))
            and len(stripped) <= len(command) + 80
        ):
            continue  # Echo (ggf. mit vorangestelltem Prompt)
        if index < 4 and stripped.startswith(("Last login", 'User "')):
            continue
        if any(p.lower() in stripped.lower() for p in pagers):
            continue
        if _PROMPT.match(stripped):
            continue
        out.append(line.rstrip())
    return "\n".join(out).strip("\n")


class RawShellTransport:
    """Persistente SSH-Shell mit Pager-/Banner-Handling (siehe Modul-Docstring)."""

    def __init__(self, params: ConnectionParams, dialect: ShellDialect) -> None:
        self._params = params
        self._dialect = dialect
        self._conn: asyncssh.SSHClientConnection | None = None
        self._proc: asyncssh.SSHClientProcess[str] | None = None

    async def __aenter__(self) -> "RawShellTransport":
        p = self._params
        password = p.password.get_secret_value() if p.password else None
        self._conn = await connect_with_legacy_fallback(
            p.host, port=p.port, username=p.username, password=password
        )
        try:
            self._proc = await self._conn.create_process(term_type="vt100", term_size=(250, 60))
            banner = await self._read(3.0)
            if self._dialect.banner_continue and "Press any key" in banner:
                self._write("")
                banner += await self._read(2.0)
            if self._dialect.inband_login and "User Name:" in banner:
                self._write(p.username)
                await self._read(2.0)
                self._write(password or "")
                await self._read(3.0)
            if self._dialect.paging_command:
                self._write(self._dialect.paging_command)
                await self._read(1.5)
        except BaseException:
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

    def _write(self, line: str) -> None:
        assert self._proc is not None
        self._proc.stdin.write(line + self._dialect.line_end)

    async def _read(self, wait: float = 3.0, *, max_seconds: float = 240.0) -> str:
        """Liest bis zum CLI-Prompt (oder ``wait`` s Stille); blättert durch den Pager."""
        assert self._proc is not None
        buf = ""
        loop = asyncio.get_event_loop()
        started = loop.time()
        while loop.time() - started < max_seconds:
            try:
                chunk = await asyncio.wait_for(self._proc.stdout.read(16384), timeout=wait)
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            if any(p in chunk for p in self._dialect.pagers):
                self._proc.stdin.write(" ")
                continue
            tail = strip_ansi(buf).replace("\r", "").rstrip("\n").split("\n")[-1]
            if _PROMPT.match(tail.strip()):
                break
        return buf

    async def send_command(self, command: str) -> str:
        if not _is_read_only(command):
            raise TransportError(f"Nur lesende Befehle erlaubt, abgelehnt: {command!r}")
        self._write(command)
        wait = 6.0 if ("running" in command or "current-configuration" in command) else 3.0
        return clean_output(await self._read(wait), command, self._dialect.pagers)

    async def send_config(self, lines: list[str]) -> str:
        """Schreibpfad (NICHT read-only-guarded) — nur für autorisierte Änderungen."""
        results: list[str] = []
        for line in lines:
            self._write(line)
            results.append(strip_ansi(await self._read(2.5)))
        return "\n".join(results)
