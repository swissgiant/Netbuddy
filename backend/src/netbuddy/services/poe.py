"""PoE-Status lesen und (autorisiert) einen Port erholen.

Vendor-agnostisch: das Vendor-Profil schaltet PoE per ``poe_control`` frei und wählt über
``poe_control.parser`` einen der hier registrierten Ausgabe-Parser. Aktuell implementiert:
``dell_os6`` (Dell N-Series PX, ``show power inline``). Weitere Vendor (z.B. lokaler UniFi-
Controller) docken über einen neuen Parser-Key an, ohne den Aufrufer zu ändern.
"""

import asyncio
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.profile import PoeControlSpec
from netbuddy.db.models import PoeEvent

# Rate-Limit: einen Port nicht endlos bouncen (hart-toter AP/Kabel) — nach N Versuchen im Fenster
# wird übersprungen und für manuelle Prüfung markiert.
RECOVER_MAX_ATTEMPTS = 3
RECOVER_WINDOW = timedelta(minutes=30)
_RATE_LIMITED_ACTIONS = ("recovered", "no_change", "error")

# PoE-Status-Klassen (lowercase verglichen).
DELIVERING = frozenset({"on"})
# Echter Stör-Zustand: PD erkannt, Power verweigert/abgeschaltet.
FAULT_STATES = frozenset({"fault", "error", "denied", "overload", "otherfault", "short"})
# Sucht ein PD — leerer Port ODER (auf einem AP-Port) ein stromloser AP.
SEARCHING_STATES = frozenset({"searching"})

# Ausgaben, die belegen, dass das Board gar keine PoE-Hardware hat / der Befehl nicht greift.
_NO_POE_MARKERS = ("doesn't support poe", "does not support poe", "invalid input", "incomplete")


class PoePort(BaseModel):
    """PoE-Sicht eines physischen Ports (eine Zeile aus ``show power inline``)."""

    port: str
    poe_state: str | None = None  # auto | never | off  (administrativer PoE-Modus)
    poe_status: str  # On | Searching | Fault | Test-Fail | Off | ...  (operativer Zustand)
    poe_class: str | None = None
    power_mw: int | None = None
    link_up: bool | None = None  # aus dem Link-Status-Befehl angereichert

    @property
    def delivering(self) -> bool:
        return self.poe_status.lower() in DELIVERING

    @property
    def faulted(self) -> bool:
        return self.poe_status.lower() in FAULT_STATES

    @property
    def searching(self) -> bool:
        return self.poe_status.lower() in SEARCHING_STATES


class WriteTransport(Protocol):
    """Transport, der lesen UND (autorisiert) schreiben kann."""

    async def send_command(self, command: str) -> str: ...
    async def send_config(self, lines: list[str]) -> str: ...


class StuckCandidate(BaseModel):
    """Ein AP-Port, der wahrscheinlich „hängt": PD erkannt/erwartet, aber ohne Strom + Link."""

    device_id: uuid.UUID
    hostname: str
    port: str
    poe_status: str
    poe_state: str | None = None
    link_up: bool | None = None
    ap_mac: str | None = None
    ap_name: str | None = None
    reason: str
    # Quelle + Recovery-Kontext: cli = Dell-CLI (Bounce), unifi = UniFi-API (power-cycle).
    source: str = "cli"
    switch_mac: str | None = None
    site: str | None = None
    port_idx: int | None = None


def is_stuck(port: PoePort, ap_status: str | None) -> bool:
    """Stuck-Kriterium: (Fault ODER Searching) + Link DOWN + zugehöriger AP laut UniFi offline.

    Bewusst eng: ein gesundes, selbst-versorgtes Gerät hält den Link (``link_up`` True) und wird
    so NIE als stuck gewertet — auch wenn sein PoE-Status ``Fault`` ist (Nicht-PoE-Gerät am
    PoE-Port). Searching/Fault zählt nur, wenn an dem Port laut Inventar ein AP gehört und dieser
    offline ist. Der Aufrufer ruft dies nur für Ports mit zugeordnetem AP auf.
    """
    if ap_status != "offline":
        return False
    if port.link_up is not False:  # True oder None → nicht eindeutig tot → nicht anfassen
        return False
    return port.faulted or port.searching


# --- Parser ----------------------------------------------------------------------------------

_PORT_RE = re.compile(r"^\s*([A-Za-z]{2}\d+/\d+/\d+)\s+(.*)$")
_STATE_RE = re.compile(r"\b(auto|never|off)\b", re.IGNORECASE)
_LINK_RE = re.compile(r"\b(Up|Down)\b")


def _parse_dell_os6_power(output: str) -> dict[str, PoePort]:
    """``show power inline`` (Dell N-Series PX): pro Port eine Zeile.

    ``Gi1/0/4   <Powered Device>  auto  Low  Fault  Unknown/Unknown  <power>``. Die
    Powered-Device-Spalte (optional, kann Leerzeichen haben) steht VOR der State-Spalte
    (``auto``/``never``); danach folgen Priority, Status, Class[, Power]. Wir verankern an
    der State-Spalte und nehmen Status = zweites Token danach.
    """
    ports: dict[str, PoePort] = {}
    for line in output.splitlines():
        m = _PORT_RE.match(line)
        if not m:
            continue
        port, rest = m.group(1), m.group(2)
        sm = _STATE_RE.search(rest)
        if not sm:
            continue  # Header/Trenner/keine PoE-Zeile
        toks = rest[sm.start() :].split()
        if len(toks) < 3:
            continue
        state, _priority, statusv = toks[0].lower(), toks[1], toks[2]
        poe_class = None
        if len(toks) >= 4 and "/" in toks[3]:
            poe_class = toks[3]
        power_mw = None
        if toks and toks[-1].isdigit():
            power_mw = int(toks[-1])
        ports[port] = PoePort(
            port=port,
            poe_state=state,
            poe_status=statusv,
            poe_class=poe_class,
            power_mw=power_mw,
        )
    return ports


def _parse_dell_os6_link(output: str) -> dict[str, bool]:
    """``show interfaces status`` (Dell N-Series): Link-State-Spalte = Up/Down je Port."""
    links: dict[str, bool] = {}
    for line in output.splitlines():
        m = _PORT_RE.match(line)
        if not m:
            continue
        lm = _LINK_RE.search(m.group(2))
        if lm:
            links[m.group(1)] = lm.group(1) == "Up"
    return links


class _Parser:
    def __init__(
        self,
        power: Callable[[str], dict[str, PoePort]],
        link: Callable[[str], dict[str, bool]],
    ) -> None:
        self.power = power
        self.link = link


_PARSERS: dict[str, _Parser] = {
    "dell_os6": _Parser(_parse_dell_os6_power, _parse_dell_os6_link),
}


def _has_no_poe(output: str) -> bool:
    low = output.lower()
    return any(marker in low for marker in _NO_POE_MARKERS)


async def scan_poe(transport: WriteTransport, spec: PoeControlSpec) -> list[PoePort]:
    """Liest read-only den PoE- + Link-Status aller Ports eines Switches.

    Gibt eine leere Liste zurück, wenn das Board keine PoE-Hardware hat (manche Modelle einer
    Serie sind PoE, andere nicht) oder der Parser-Key unbekannt ist.
    """
    parser = _PARSERS.get(spec.parser)
    if parser is None:
        return []
    power_out = await transport.send_command(spec.status_command)
    if _has_no_poe(power_out):
        return []
    ports = parser.power(power_out)
    if not ports:
        return []
    link_out = await transport.send_command(spec.link_command)
    links = parser.link(link_out)
    for p in ports.values():
        p.link_up = links.get(p.port)
    return list(ports.values())


class PoeRecoverResult(BaseModel):
    """Ergebnis eines Port-Bounce: Status vorher/nachher + ob der Port wieder versorgt/aktiv ist."""

    port: str
    status_before: str | None = None
    status_after: str | None = None
    recovered: bool = False
    detail: str = ""


async def _port_status(
    transport: WriteTransport, spec: PoeControlSpec, port: str
) -> PoePort | None:
    for p in await scan_poe(transport, spec):
        if p.port == port:
            return p
    return None


async def recover_port(
    transport: WriteTransport, spec: PoeControlSpec, port: str
) -> PoeRecoverResult:
    """Erholt EINEN PoE-Port per Bounce: ``recover_down`` → warten → ``recover_up`` (shut/no shut).

    ⚠️ Schreibzugriff auf echte Hardware. Aufrufer ist für Berechtigung/Audit/Rate-Limit
    verantwortlich. Liest Vorher/Nachher zur Verifikation; ``recovered`` = Port liefert wieder
    Strom ODER hat wieder Link.
    """
    before = await _port_status(transport, spec, port)

    def seq(commands: list[str]) -> list[str]:
        return [
            *spec.config_enter,
            spec.interface_enter.format(name=port),
            *commands,
            spec.interface_exit,
            *spec.config_exit,
        ]

    await transport.send_config(seq(spec.recover_down))
    await asyncio.sleep(spec.recover_wait_seconds)
    await transport.send_config(seq(spec.recover_up))
    await asyncio.sleep(spec.recover_wait_seconds)

    after = await _port_status(transport, spec, port)
    recovered = after is not None and (after.delivering or after.link_up is True)
    return PoeRecoverResult(
        port=port,
        status_before=before.poe_status if before else None,
        status_after=after.poe_status if after else None,
        recovered=recovered,
        detail=f"{spec.recover_down} -> wait {spec.recover_wait_seconds}s -> {spec.recover_up}",
    )


async def recent_attempts(session: AsyncSession, device_id: uuid.UUID, port: str) -> int:
    since = datetime.now(UTC) - RECOVER_WINDOW
    count = (
        await session.execute(
            select(func.count())
            .select_from(PoeEvent)
            .where(
                PoeEvent.device_id == device_id,
                PoeEvent.port == port,
                PoeEvent.created_at >= since,
                PoeEvent.action.in_(_RATE_LIMITED_ACTIONS),
            )
        )
    ).scalar()
    return int(count or 0)


async def recover_with_policy(
    session: AsyncSession,
    device_id: uuid.UUID,
    transport: WriteTransport,
    spec: PoeControlSpec,
    port: str,
    *,
    ap_mac: str | None = None,
    ap_name: str | None = None,
    actor: str | None = None,
) -> PoeEvent:
    """Erholt einen Port mit Rate-Limit + Audit-Eintrag — gemeinsame Logik für Endpoint & Worker.

    Schreibt in jedem Fall genau einen :class:`PoeEvent` (auch bei Skip/Fehler) und gibt ihn zurück.
    Committet NICHT — der Aufrufer entscheidet über die Transaktion.
    """
    if await recent_attempts(session, device_id, port) >= RECOVER_MAX_ATTEMPTS:
        event = PoeEvent(
            device_id=device_id,
            port=port,
            ap_mac=ap_mac,
            ap_name=ap_name,
            action="skipped_ratelimit",
            actor=actor,
            detail=f"Rate-Limit: >= {RECOVER_MAX_ATTEMPTS} Versuche in {RECOVER_WINDOW}",
        )
        session.add(event)
        return event

    try:
        result = await recover_port(transport, spec, port)
        event = PoeEvent(
            device_id=device_id,
            port=port,
            ap_mac=ap_mac,
            ap_name=ap_name,
            action="recovered" if result.recovered else "no_change",
            status_before=result.status_before,
            status_after=result.status_after,
            actor=actor,
            detail=result.detail,
        )
    except Exception as exc:
        event = PoeEvent(
            device_id=device_id,
            port=port,
            ap_mac=ap_mac,
            ap_name=ap_name,
            action="error",
            actor=actor,
            detail=str(exc)[:500],
        )
    session.add(event)
    return event
