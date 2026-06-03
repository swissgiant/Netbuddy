from typing import Any

from pydantic import BaseModel

from netbuddy.adapters.converters import apply_pipeline
from netbuddy.adapters.profile import FieldSpec


def _field_value(spec: FieldSpec, row: dict[str, Any]) -> Any:
    if spec.mode == "const":
        return spec.const
    value = apply_pipeline(row.get(spec.source) if spec.source else None, spec.via)
    if value is None:
        return spec.default
    return value


def build_dto[T: BaseModel](
    dto_cls: type[T], fields: dict[str, FieldSpec], row: dict[str, Any]
) -> T:
    """Baut ein DTO aus einer geparsten Zeile gemäß Feld-Specs.

    Pydantic übernimmt die finale Validierung/Coercion (z.B. ``"up"`` → ``AdminStatus.UP``).
    """
    kwargs = {name: _field_value(spec, row) for name, spec in fields.items()}
    return dto_cls(**kwargs)
