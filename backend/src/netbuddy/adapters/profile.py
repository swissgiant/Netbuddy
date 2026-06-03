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


class CapabilitySpec(BaseModel):
    """Eine Read-Capability: welcher Befehl, welcher Parser, welches Feld-Mapping."""

    model_config = ConfigDict(extra="forbid")

    command: str
    parser: str = "ntc"  # "ntc" | "textfsm:<datei>"
    drop_when_empty: list[str] = Field(default_factory=list)
    fields: dict[str, FieldSpec]


class VendorProfile(BaseModel):
    """Deklarative Beschreibung eines Vendor-Adapters (ein YAML pro Vendor)."""

    model_config = ConfigDict(extra="forbid")

    adapter_id: str
    ntc_platform: str | None = None
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
