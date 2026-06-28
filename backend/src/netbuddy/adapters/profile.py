import importlib.resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from netbuddy.adapters.capabilities import Capability


class FieldSpec(BaseModel):
    """Wie ein DTO-Feld befüllt wird: aus einem geparsten Key (+Converter) oder als Konstante.

    YAML-Formen::

        hostname:   { from: hostname, via: [strip_or_none], default: "" }
        vendor:     { const: cisco }
        name:       interface          # Shorthand == { from: interface }
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    mode: Literal["const", "from"]
    const: Any = None
    source: str | None = Field(default=None, alias="from")
    via: list[str | dict[str, Any]] = Field(default_factory=list)
    default: Any = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, str):  # Shorthand: nackter String == from
            data = {"from": data}
        if isinstance(data, dict) and "mode" not in data:
            data = {**data, "mode": "const" if "const" in data else "from"}
        return data

    @model_validator(mode="after")
    def _check(self) -> "FieldSpec":
        if self.mode == "from" and self.source is None:
            raise ValueError("FieldSpec mit mode=from braucht ein 'from'")
        if self.mode == "const" and self.const is None:
            raise ValueError("FieldSpec mit mode=const braucht einen 'const'-Wert")
        return self


class SourceSpec(BaseModel):
    """Eine Befehl-/Parser-Quelle innerhalb einer Capability."""

    model_config = ConfigDict(extra="forbid")

    command: str
    parser: str = "ntc"  # "ntc" | "textfsm:<datei>"


class CapabilitySpec(BaseModel):
    """Eine Read-Capability: eine oder mehrere Quellen + Feld-Mapping.

    Kurzform (eine Quelle) per ``command:``/``parser:`` bleibt gültig und wird zu
    ``sources=[{command, parser}]`` normalisiert. Mehrere Quellen via ``sources:`` —
    bei single-arity Capabilities (system_info) werden die geparsten ersten Zeilen
    gemergt, bei list-arity ist genau eine Quelle erlaubt (Prüfung im Adapter).
    """

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceSpec]
    drop_when_empty: list[str] = Field(default_factory=list)
    fields: dict[str, FieldSpec]

    @model_validator(mode="before")
    @classmethod
    def _normalize_sources(cls, data: Any) -> Any:
        if isinstance(data, dict) and "sources" not in data:
            command = data.pop("command", None)
            parser = data.pop("parser", "ntc")
            if command is not None:
                data = {**data, "sources": [{"command": command, "parser": parser}]}
        return data

    @model_validator(mode="after")
    def _check_sources(self) -> "CapabilitySpec":
        if not self.sources:
            raise ValueError("CapabilitySpec braucht mindestens eine Quelle")
        return self


class LldpControlSpec(BaseModel):
    """Optionaler Schreibpfad, um LLDP zu prüfen und (global + pro Port) zu aktivieren.

    Bewusst eng: nur LLDP. ``enabled_marker`` ist ein Regex gegen die ``status_command``-Ausgabe.
    ``enable_interface`` wird je physischem Interface im jeweiligen Interface-Kontext gesendet
    (``interface_enter`` füllt ``{name}``). Schreibzugriff nur über den expliziten, autorisierten
    LLDP-Endpoint — nie über den read-only Discovery-/Validierungspfad.
    """

    model_config = ConfigDict(extra="forbid")

    status_command: str
    enabled_marker: str  # Regex; matcht → LLDP global aktiv
    config_enter: list[str] = Field(default_factory=lambda: ["configure terminal"])
    config_exit: list[str] = Field(default_factory=lambda: ["end"])  # Centec: "exit"
    enable_global: list[str] = Field(default_factory=list)
    enable_interface: list[str] = Field(default_factory=list)
    interface_enter: str = "interface {name}"
    interface_exit: str = "exit"


class PoeControlSpec(BaseModel):
    """Optionaler PoE-Pfad: Status lesen (``show power inline``) + einen Port erholen.

    Read: ``status_command`` (PoE pro Port) + ``link_command`` (Link-Status pro Port). Der
    konkrete Ausgabe-Parser wird per ``parser`` (Code-Parser-Key, derzeit nur ``dell_os6``)
    gewählt. Write (Recovery) ist ein **Port-Bounce** = ``recover_down`` (z.B. ``shutdown``)
    → ``recover_wait_seconds`` warten → ``recover_up`` (z.B. ``no shutdown``); kappt Link+PoE
    und erzwingt eine vollständige Neuverhandlung. Schreibzugriff nur über den autorisierten
    PoE-Endpoint, nie über den read-only-Pfad.
    """

    model_config = ConfigDict(extra="forbid")

    status_command: str = "show power inline"
    link_command: str = "show interfaces status"
    parser: str = "dell_os6"
    config_enter: list[str] = Field(default_factory=lambda: ["configure"])
    config_exit: list[str] = Field(default_factory=lambda: ["end"])
    interface_enter: str = "interface {name}"
    interface_exit: str = "exit"
    recover_down: list[str] = Field(default_factory=lambda: ["shutdown"])
    recover_up: list[str] = Field(default_factory=lambda: ["no shutdown"])
    recover_wait_seconds: int = 5


class VendorProfile(BaseModel):
    """Deklarative Beschreibung eines Vendor-Adapters (ein YAML pro Vendor)."""

    model_config = ConfigDict(extra="forbid")

    adapter_id: str
    ntc_platform: str | None = None
    provenance: str | None = None  # z.B. "vendor docs, unvalidated" / "lab-validated"
    backup_command: str | None = None  # liefert die laufende Konfig (READ_CONFIG)
    lldp_control: LldpControlSpec | None = None  # optionaler LLDP-Schreibpfad (write)
    poe_control: PoeControlSpec | None = None  # optionaler PoE-Status-/Recovery-Pfad
    capabilities: dict[Capability, CapabilitySpec]


def load_profile(text: str) -> VendorProfile:
    """Parst ein YAML-Profil zu einem validierten :class:`VendorProfile`."""
    return VendorProfile.model_validate(yaml.safe_load(text))


def load_profiles_from_package() -> dict[str, VendorProfile]:
    """Lädt alle ``*.yaml`` aus dem ``netbuddy.adapters.profiles``-Verzeichnis."""
    root = importlib.resources.files("netbuddy.adapters") / "profiles"
    profiles: dict[str, VendorProfile] = {}
    for entry in root.iterdir():
        if entry.name.endswith((".yaml", ".yml")):
            profile = load_profile(entry.read_text(encoding="utf-8"))
            profiles[profile.adapter_id] = profile
    return profiles
