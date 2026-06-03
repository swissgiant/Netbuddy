import importlib.resources
import io
from typing import Any, cast

import textfsm
from ntc_templates.parse import parse_output


def _parse_ntc(ntc_platform: str | None, command: str, data: str) -> list[dict[str, Any]]:
    if ntc_platform is None:
        raise ValueError("parser 'ntc' braucht ein 'ntc_platform' im Profil")
    parsed = parse_output(platform=ntc_platform, command=command, data=data)
    return cast(list[dict[str, Any]], parsed)


def parse_textfsm_text(template: str, data: str) -> list[dict[str, Any]]:
    """Parst ``data`` mit einem TextFSM-Template-Text; Header werden kleingeschrieben."""
    fsm = textfsm.TextFSM(io.StringIO(template))
    headers = [name.lower() for name in fsm.header]
    return [dict(zip(headers, row, strict=True)) for row in fsm.ParseText(data)]


def _parse_textfsm(template_file: str, data: str) -> list[dict[str, Any]]:
    """Lädt ein mitgeliefertes TextFSM-Template (für Vendor ohne ntc-Abdeckung) und parst."""
    template = (
        importlib.resources.files("netbuddy.adapters") / "cli_templates" / template_file
    ).read_text(encoding="utf-8")
    return parse_textfsm_text(template, data)


def parse(
    parser: str,
    *,
    ntc_platform: str | None,
    command: str,
    data: str,
) -> list[dict[str, Any]]:
    """Dispatcht auf den im Profil benannten Parser.

    ``"ntc"`` → ntc-templates; ``"textfsm:<datei>"`` → custom Template aus ``cli_templates/``.
    """
    if parser == "ntc":
        return _parse_ntc(ntc_platform, command, data)
    if parser.startswith("textfsm:"):
        return _parse_textfsm(parser.removeprefix("textfsm:"), data)
    raise ValueError(f"Unbekannter Parser {parser!r}")
