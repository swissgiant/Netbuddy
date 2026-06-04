import re

from pydantic import BaseModel

from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.transport import CommandTransport

# Capability → Schlüsselwörter, an denen ein passender `show`-Befehl in der Hilfe erkannt wird.
_KEYWORDS: dict[Capability, tuple[str, ...]] = {
    Capability.READ_SYSTEM_INFO: ("version",),
    Capability.READ_INTERFACES: ("interface",),
    Capability.READ_LLDP: ("lldp", "neighbor"),
    Capability.READ_MAC_TABLE: ("mac", "address-table", "mac-address"),
}

_HELP_COMMAND = "show ?"
# Zeile der Hilfe: "  version    System hardware and software status" → (wort, beschreibung)
_HELP_LINE = re.compile(r"^\s*(\S+)\s{2,}(.+?)\s*$")


class CapabilitySuggestion(BaseModel):
    capability: Capability
    command: str | None  # bester Kandidat aus der Hilfe (None = nichts gefunden)
    matched_help: str | None = None  # die Hilfe-Beschreibung, an der es erkannt wurde
    raw_excerpt: str | None = None  # roher Output des Kandidaten (Referenz für Template/KI)


class ProfileDraft(BaseModel):
    """Vorschlag aus assistiertem Onboarding: Kandidaten-Befehle + Roh-Output je Capability.

    Liefert die **Befehle** (per Geräte-Hilfe gefunden) und deren Output — die Ableitung eines
    funktionierenden TextFSM-/KI-Parsers daraus ist der nächste Schritt (CLAUDE.md Phase 5).
    """

    suggested_adapter_id: str | None = None
    capabilities: list[CapabilitySuggestion]


def parse_show_help(text: str) -> list[tuple[str, str]]:
    """Parst `show ?`-Ausgabe zu (Befehlswort, Beschreibung)-Paaren."""
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _HELP_LINE.match(line)
        if match:
            word, description = match.group(1), match.group(2)
            if word not in {"WORD", "<cr>"}:
                entries.append((word, description))
    return entries


def pick_candidates(entries: list[tuple[str, str]]) -> dict[Capability, tuple[str, str]]:
    """Wählt je Capability den ersten Hilfe-Eintrag, dessen Wort/Beschreibung passt."""
    chosen: dict[Capability, tuple[str, str]] = {}
    for capability, keywords in _KEYWORDS.items():
        for word, description in entries:
            haystack = f"{word} {description}".lower()
            if any(kw in haystack for kw in keywords):
                chosen[capability] = (f"show {word}", description)
                break
    return chosen


async def suggest_profile(
    transport: CommandTransport, *, suggested_adapter_id: str | None = None
) -> ProfileDraft:
    """Fragt die Geräte-Hilfe ab, findet Kandidaten-Befehle je Capability und holt deren Output.

    Read-only. Der zurückgegebene Draft ist Ausgangspunkt für ein neues Profil/Template.
    """
    help_text = await transport.send_command(_HELP_COMMAND)
    candidates = pick_candidates(parse_show_help(help_text))

    suggestions: list[CapabilitySuggestion] = []
    for capability in _KEYWORDS:
        picked = candidates.get(capability)
        if picked is None:
            suggestions.append(CapabilitySuggestion(capability=capability, command=None))
            continue
        command, description = picked
        try:
            raw = await transport.send_command(command)
        except Exception as exc:  # Kandidat existiert laut Hilfe, scheitert aber → festhalten
            suggestions.append(
                CapabilitySuggestion(
                    capability=capability,
                    command=command,
                    matched_help=description,
                    raw_excerpt=f"<error> {type(exc).__name__}: {exc}",
                )
            )
            continue
        suggestions.append(
            CapabilitySuggestion(
                capability=capability,
                command=command,
                matched_help=description,
                raw_excerpt=raw,
            )
        )
    return ProfileDraft(suggested_adapter_id=suggested_adapter_id, capabilities=suggestions)
