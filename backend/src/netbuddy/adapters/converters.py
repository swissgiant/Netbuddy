import enum
import re
from collections.abc import Callable
from typing import Any

from netbuddy.db.models import AdminStatus, DeviceType, MacEntryType, OperStatus

# Enums, die Profile per Namen referenzieren dürfen (z.B. enum_value: {values_of: MacEntryType}).
_ENUMS: dict[str, type[enum.Enum]] = {
    "AdminStatus": AdminStatus,
    "DeviceType": DeviceType,
    "MacEntryType": MacEntryType,
    "OperStatus": OperStatus,
}

Converter = Callable[[Any], Any]


def _strip_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first(value: Any) -> Any:
    """Erstes Element einer (ntc-)Liste bzw. den Wert selbst; leer → None."""
    if isinstance(value, list):
        return _strip_or_none(value[0]) if value else None
    return _strip_or_none(value)


def _first_word(value: Any) -> str | None:
    text = _strip_or_none(value)
    if text is None:
        return None
    return text.split(maxsplit=1)[0]


def _int_or_none(value: Any) -> int | None:
    text = _strip_or_none(value)
    if text is None or not text.isdigit():
        return None
    return int(text)


def _kbit_to_mbps(value: Any) -> int | None:
    """``"1000000 Kbit"`` → 1000 (Mbit/s)."""
    text = _strip_or_none(value)
    if text is None:
        return None
    match = re.match(r"(\d+)\s*Kbit", text, re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1)) // 1000


def _lower(value: Any) -> str | None:
    text = _strip_or_none(value)
    return text.lower() if text is not None else None


def _leading_int(value: Any) -> int | None:
    """Führende Ziffern → int; z.B. ``"1000M"`` → 1000, ``"1000Mb/s"`` → 1000, ``"auto"`` → None."""
    text = _strip_or_none(value)
    if text is None:
        return None
    match = re.match(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _ip_or_none(value: Any) -> str | None:
    """IP-Adresse oder None; verwirft Platzhalter wie ``0.0.0.0`` (PCs melden das via LLDP)."""
    text = _strip_or_none(value)
    if text is None or text == "0.0.0.0":
        return None
    return text


# Converter ohne Argumente.
_SIMPLE: dict[str, Converter] = {
    "strip_or_none": _strip_or_none,
    "first": _first,
    "first_word": _first_word,
    "int_or_none": _int_or_none,
    "ip_or_none": _ip_or_none,
    "kbit_to_mbps": _kbit_to_mbps,
    "leading_int": _leading_int,
    "lower": _lower,
}


def _make_lookup(*, table: dict[str, Any], default: Any = None) -> Converter:
    """Mappt den (lowercased) Eingabewert über eine Tabelle; sonst ``default``."""

    def convert(value: Any) -> Any:
        text = _strip_or_none(value)
        if text is None:
            return default
        return table.get(text.lower(), default)

    return convert


def _make_enum_value(*, values_of: str, default: str) -> Converter:
    """Gibt den (lowercased) Wert zurück, falls er ein gültiger Enum-Wert ist, sonst ``default``."""
    try:
        enum_cls = _ENUMS[values_of]
    except KeyError as exc:
        raise ValueError(f"Unbekanntes Enum {values_of!r} in enum_value-Converter") from exc
    valid = {str(member.value) for member in enum_cls}

    def convert(value: Any) -> str:
        text = _strip_or_none(value)
        if text is not None and text.lower() in valid:
            return text.lower()
        return default

    return convert


# Converter mit Argumenten (Factories).
_FACTORIES: dict[str, Callable[..., Converter]] = {
    "lookup": _make_lookup,
    "enum_value": _make_enum_value,
}


def build_converter(spec: str | dict[str, Any]) -> Converter:
    """Löst eine Converter-Spec (Name oder ``{name: args}``) zu einer Funktion auf."""
    if isinstance(spec, str):
        try:
            return _SIMPLE[spec]
        except KeyError as exc:
            raise ValueError(f"Unbekannter Converter {spec!r}") from exc
    if len(spec) != 1:
        raise ValueError(f"Converter-Spec braucht genau einen Key, bekam: {spec!r}")
    ((name, args),) = spec.items()
    try:
        factory = _FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"Unbekannter parametrisierter Converter {name!r}") from exc
    return factory(**args)


def apply_pipeline(value: Any, specs: list[str | dict[str, Any]]) -> Any:
    """Wendet eine Liste von Converter-Specs links→rechts an."""
    for spec in specs:
        value = build_converter(spec)(value)
    return value
