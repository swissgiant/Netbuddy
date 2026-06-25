"""VPN-Generierung (Firewall-Schreibpfad) — Dry-Run-Vorschau.

`POST /vpn/plan` liefert die geplanten FortiOS-Schreib-Operationen für beide Tunnel-Enden,
**ohne** etwas an den Geräten zu ändern (reiner Plan). Das eigentliche Anwenden (Backup →
ausführen → Rollback) folgt als separater, autorisierter Schritt, sobald die Ziel-Firewalls
erreichbar sind. Pre-Shared-Key wird in der Vorschau maskiert.
"""

import copy

from fastapi import APIRouter

from netbuddy.services.vpn_provision import VpnPlan, VpnTunnelSpec, plan_site_to_site

router = APIRouter(prefix="/vpn", tags=["vpn"])

_MASK = "********"


def _mask_psk(plan: VpnPlan) -> VpnPlan:
    """Ersetzt jedes `psksecret` in den geplanten Bodies durch eine Maske (kein Secret-Leak)."""
    masked = plan.model_copy(deep=True)
    for fw in masked.firewalls:
        for op in fw.operations:
            if "psksecret" in op.body:
                op.body = {**copy.deepcopy(op.body), "psksecret": _MASK}
    return masked


@router.post("/plan", response_model=VpnPlan)
async def vpn_plan(spec: VpnTunnelSpec) -> VpnPlan:
    """Dry-Run: erzeugt den Schreib-Plan für beide Firewalls (keine Geräte-Änderung)."""
    return _mask_psk(plan_site_to_site(spec))
