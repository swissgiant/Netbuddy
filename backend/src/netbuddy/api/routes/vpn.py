"""VPN-Generierung (Firewall-Schreibpfad) — Dry-Run-Vorschau.

`POST /vpn/plan` (ein Tunnel) und `POST /vpn/mesh-plan` (Full-Mesh) liefern die geplanten
FortiOS-Schreib-Operationen je Firewall, **ohne** etwas an den Geräten zu ändern (reiner Plan).
Das eigentliche Anwenden (Backup → ausführen → Rollback) folgt als separater, autorisierter
Schritt, sobald die Ziel-Firewalls erreichbar sind. Pre-Shared-Keys werden maskiert.
"""

import copy

from fastapi import APIRouter
from pydantic import BaseModel

from netbuddy.services.vpn_provision import (
    DEFAULT_DH_GROUPS,
    DEFAULT_IKE_VERSION,
    DEFAULT_PHASE1_PROPOSAL,
    DEFAULT_PHASE2_PROPOSAL,
    FirewallPlan,
    VpnEnd,
    VpnMeshPlan,
    VpnPlan,
    VpnTunnelSpec,
    plan_full_mesh,
    plan_site_to_site,
)

router = APIRouter(prefix="/vpn", tags=["vpn"])

_MASK = "********"


def _mask(firewalls: list[FirewallPlan]) -> None:
    """Ersetzt jedes `psksecret` in den geplanten Bodies durch eine Maske (kein Secret-Leak)."""
    for fw in firewalls:
        for op in fw.operations:
            if "psksecret" in op.body:
                op.body = {**copy.deepcopy(op.body), "psksecret": _MASK}


class MeshRequest(BaseModel):
    """Full-Mesh-Anfrage: alle Tunnel-Enden + optionale Krypto-Defaults."""

    ends: list[VpnEnd]
    ike_version: int = DEFAULT_IKE_VERSION
    phase1_proposal: str = DEFAULT_PHASE1_PROPOSAL
    phase2_proposal: str = DEFAULT_PHASE2_PROPOSAL
    dh_groups: str = DEFAULT_DH_GROUPS


@router.post("/plan", response_model=VpnPlan)
async def vpn_plan(spec: VpnTunnelSpec) -> VpnPlan:
    """Dry-Run: Schreib-Plan für einen Site-to-Site-Tunnel (keine Geräte-Änderung)."""
    plan = plan_site_to_site(spec)
    masked = plan.model_copy(deep=True)
    _mask(masked.firewalls)
    return masked


@router.post("/mesh-plan", response_model=VpnMeshPlan)
async def vpn_mesh_plan(req: MeshRequest) -> VpnMeshPlan:
    """Dry-Run: Full-Mesh-Plan (jede FW zu jeder), je Firewall aggregiert."""
    plan = plan_full_mesh(
        req.ends,
        ike_version=req.ike_version,
        phase1_proposal=req.phase1_proposal,
        phase2_proposal=req.phase2_proposal,
        dh_groups=req.dh_groups,
    )
    masked = plan.model_copy(deep=True)
    _mask(masked.firewalls)
    return masked
