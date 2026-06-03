import pytest

from netbuddy.adapters.converters import apply_pipeline, build_converter


def test_simple_converters() -> None:
    assert build_converter("strip_or_none")("  x ") == "x"
    assert build_converter("strip_or_none")("   ") is None
    assert build_converter("first")(["a", "b"]) == "a"
    assert build_converter("first")([]) is None
    assert build_converter("first")("solo") == "solo"
    assert build_converter("first_word")("up (connected)") == "up"
    assert build_converter("int_or_none")("1500") == 1500
    assert build_converter("int_or_none")("All") is None
    assert build_converter("kbit_to_mbps")("1000000 Kbit") == 1000
    assert build_converter("kbit_to_mbps")("n/a") is None
    assert build_converter("lower")("DYNAMIC") == "dynamic"


def test_lookup_converter() -> None:
    conv = build_converter(
        {"lookup": {"table": {"up": "up", "administratively down": "down"}, "default": "unknown"}}
    )
    assert conv("up") == "up"
    assert conv("Administratively Down") == "down"  # case-insensitiv
    assert conv("weird") == "unknown"
    assert conv("") == "unknown"


def test_enum_value_converter() -> None:
    conv = build_converter({"enum_value": {"values_of": "MacEntryType", "default": "dynamic"}})
    assert conv("STATIC") == "static"
    assert conv("dynamic") == "dynamic"
    assert conv("bogus") == "dynamic"


def test_pipeline_chains_left_to_right() -> None:
    result = apply_pipeline(
        "Up (connected)",
        ["first_word", {"lookup": {"table": {"up": "up"}, "default": "unknown"}}],
    )
    assert result == "up"


def test_unknown_converter_raises() -> None:
    with pytest.raises(ValueError, match="Unbekannter Converter"):
        build_converter("does_not_exist")
    with pytest.raises(ValueError, match="parametrisierter Converter"):
        build_converter({"nope": {}})
