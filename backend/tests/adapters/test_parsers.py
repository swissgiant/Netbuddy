from pathlib import Path

import pytest

from netbuddy.adapters.parsers import parse, parse_textfsm_text

_FIXTURES = Path(__file__).parent / "fixtures" / "cisco_ios"

_DUMMY_TEMPLATE = """Value HOSTNAME (\\S+)
Value VERSION (\\S+)

Start
  ^${HOSTNAME}\\s+${VERSION} -> Record
"""


def test_parse_ntc_returns_rows() -> None:
    data = (_FIXTURES / "show_version.txt").read_text()
    rows = parse("ntc", ntc_platform="cisco_ios", command="show version", data=data)
    assert rows[0]["hostname"] == "sw-lab-01"


def test_parse_ntc_without_platform_raises() -> None:
    with pytest.raises(ValueError, match="ntc_platform"):
        parse("ntc", ntc_platform=None, command="show version", data="")


def test_parse_textfsm_text_lowercases_headers() -> None:
    rows = parse_textfsm_text(_DUMMY_TEMPLATE, "sw1 15.2\nsw2 16.1\n")
    assert rows == [
        {"hostname": "sw1", "version": "15.2"},
        {"hostname": "sw2", "version": "16.1"},
    ]


def test_parse_unknown_parser_raises() -> None:
    with pytest.raises(ValueError, match="Unbekannter Parser"):
        parse("nope", ntc_platform=None, command="x", data="")
