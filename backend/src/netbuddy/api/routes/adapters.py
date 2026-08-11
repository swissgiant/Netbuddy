from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from netbuddy.adapters import available_adapters, provenance_for
from netbuddy.api.deps import SessionDep
from netbuddy.db.models import ValidationCheck

router = APIRouter(prefix="/adapters", tags=["adapters"])


class CapabilityStatusInfo(BaseModel):
    capability: str
    validated: bool  # mind. ein Gerät mit Status "ok"
    last_status: str | None = None
    last_checked_at: datetime | None = None
    devices_checked: int = 0


class AdapterInfo(BaseModel):
    adapter_id: str
    provenance: str | None
    capabilities: list[CapabilityStatusInfo]


@router.get("", response_model=list[AdapterInfo])
async def list_adapters(session: SessionDep) -> list[AdapterInfo]:
    """Capability-Katalog je Profil + Live-Validierungs-Status (was funktioniert schon)."""
    # Nur die benötigten Spalten — raw_excerpt (roher CLI-Output, TEXT) würde sonst bei jedem
    # Seitenaufbau komplett mitgeladen (Topologie + Geräteliste rufen diesen Endpoint).
    result = await session.execute(
        select(
            ValidationCheck.adapter_id,
            ValidationCheck.capability,
            ValidationCheck.status,
            ValidationCheck.checked_at,
        )
    )
    checks = result.all()

    # (adapter_id, capability) → Liste der Checks (Row-Tuples mit Attributzugriff)
    by_key: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for check in checks:
        by_key[(check.adapter_id, check.capability)].append(check)

    adapters: list[AdapterInfo] = []
    for adapter_id, caps in sorted(available_adapters().items()):
        cap_infos: list[CapabilityStatusInfo] = []
        for capability in sorted(c.value for c in caps):
            rows = by_key.get((adapter_id, capability), [])
            latest = max(rows, key=lambda r: r.checked_at, default=None)
            cap_infos.append(
                CapabilityStatusInfo(
                    capability=capability,
                    # `empty` zählt als validiert: Befehl lief sauber, Gerät hat nur keine
                    # Einträge (z.B. ARP auf L2-Switch) — technisch grün.
                    validated=any(r.status in ("ok", "empty") for r in rows),
                    last_status=latest.status if latest else None,
                    last_checked_at=latest.checked_at if latest else None,
                    devices_checked=len(rows),
                )
            )
        adapters.append(
            AdapterInfo(
                adapter_id=adapter_id, provenance=provenance_for(adapter_id), capabilities=cap_infos
            )
        )
    return adapters
