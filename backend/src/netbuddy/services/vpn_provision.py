"""VPN-Generierung für FortiGate (route-based IPsec, IKEv2) — erster Firewall-Schreibpfad.

Erzeugt für einen Site-to-Site-Tunnel die konkreten FortiOS-`cmdb`-Operationen auf **beiden**
Enden (phase1-interface, phase2-interface, statische Route, Firewall-Policy). Spiegelt die
bestehenden Tunnel (IKEv2, gemeinsames Pre-Shared-Key auf beiden Seiten).

Bewusst zweistufig (Wunsch: „Dry-Run zuerst"):
  1. `plan_site_to_site(spec)` ist **rein** (keine Geräte-Calls) → liefert die Vorschau:
     je Firewall die geordnete Liste der Schreib-Operationen. Voll testbar ohne Hardware.
  2. Das Anwenden (Backup → ausführen → bei Fehler Rollback) baut auf diesem Plan auf
     (separater Schritt, sobald die Ziel-Firewalls erreichbar sind).

Read-only-Discovery bleibt unberührt; dieser Modul ist der **Write**-Pfad und wird nur über
einen autorisierten Endpoint ausgelöst.
"""

import secrets
from typing import Any

from pydantic import BaseModel, Field

# FortiOS-Defaults, an den bestehenden BLS-Tunneln orientiert (IKEv2).
DEFAULT_IKE_VERSION = 2
DEFAULT_PHASE1_PROPOSAL = "aes256-sha256 aes128-sha256"
DEFAULT_PHASE2_PROPOSAL = "aes256-sha256 aes128-sha256"
DEFAULT_DH_GROUPS = "14"  # MODP-2048

_CMDB = "/api/v2/cmdb"


class VpnEnd(BaseModel):
    """Ein Tunnel-Ende = eine Firewall."""

    site: str  # Standort-Label (z.B. "Grosuplje")
    device_id: str  # NetBuddy-Device-ID der Firewall
    wan_interface: str  # lokales Egress-Interface (z.B. "x3")
    public_ip: str  # EIGENE öffentliche Gateway-IP — Peers nutzen sie als remote-gw
    local_subnets: list[str] = Field(min_length=1)  # Netze hinter dieser FW
    lan_interface: str | None = None  # internes Interface für die Policy (optional)
    code: str | None = None  # kurzer Standort-Code (z.B. "SUL"); für Full-Mesh-Tunnelnamen


class VpnTunnelSpec(BaseModel):
    """Eingaben für einen Site-to-Site-Tunnel."""

    name: str  # Basisname, z.B. "GROSU-CUSANO" (max. 15 Zeichen FortiOS-Limit für phase1-Name)
    end_a: VpnEnd
    end_b: VpnEnd
    psk: str | None = None  # leer → wird stark generiert (auf beiden Enden identisch)
    ike_version: int = DEFAULT_IKE_VERSION
    phase1_proposal: str = DEFAULT_PHASE1_PROPOSAL
    phase2_proposal: str = DEFAULT_PHASE2_PROPOSAL
    dh_groups: str = DEFAULT_DH_GROUPS


class FortiOp(BaseModel):
    """Eine geplante FortiOS-Schreib-Operation (Dry-Run-Vorschau / später ausführbar)."""

    method: str  # POST | PUT
    path: str  # cmdb-Pfad
    body: dict[str, Any]
    summary: str  # menschenlesbare Kurzbeschreibung
    rollback_path: str | None = None  # DELETE-Pfad zum Zurücknehmen (falls anlegend)


class FirewallPlan(BaseModel):
    """Geplante Operationen für eine Firewall."""

    site: str
    device_id: str
    operations: list[FortiOp]


class VpnPlan(BaseModel):
    """Vollständiger Dry-Run-Plan für beide Firewalls."""

    tunnel_name: str
    psk_generated: bool  # True = PSK wurde automatisch erzeugt
    firewalls: list[FirewallPlan]


def _addr_name(subnet: str) -> str:
    """Stabiler Name für ein Adress-Objekt aus einem Subnetz (FortiOS-konform)."""
    return "net_" + subnet.replace("/", "_").replace(".", "_").replace(":", "_")


def _ops_for_end(spec: VpnTunnelSpec, local: VpnEnd, remote: VpnEnd, psk: str) -> list[FortiOp]:
    """Erzeugt die cmdb-Operationen für EIN Tunnel-Ende (lokal = `local`)."""
    name = spec.name
    remote_subnets = remote.local_subnets
    ops: list[FortiOp] = []

    # 1) phase1-interface (route-based: net-device disable, explizite Selektoren via phase2)
    ops.append(
        FortiOp(
            method="POST",
            path=f"{_CMDB}/vpn.ipsec/phase1-interface",
            body={
                "name": name,
                "type": "static",
                "interface": local.wan_interface,
                "ike-version": str(spec.ike_version),
                "remote-gw": remote.public_ip,  # Gegenstelle = Peer-FW
                "psksecret": psk,
                "proposal": spec.phase1_proposal,
                "dhgrp": spec.dh_groups,
                "peertype": "any",
                "net-device": "disable",
                "comments": f"NetBuddy: {local.site} <-> {remote.site}",
            },
            summary=f"IPsec Phase1 '{name}' → {remote.site} via {local.wan_interface}",
            rollback_path=f"{_CMDB}/vpn.ipsec/phase1-interface/{name}",
        )
    )

    # 2) Adress-Objekte (lokal + remote) für Routen/Policy
    for subnet in [*local.local_subnets, *remote_subnets]:
        an = _addr_name(subnet)
        ops.append(
            FortiOp(
                method="POST",
                path=f"{_CMDB}/firewall/address",
                body={"name": an, "subnet": subnet},
                summary=f"Adress-Objekt {an} ({subnet})",
                rollback_path=f"{_CMDB}/firewall/address/{an}",
            )
        )

    # 3) phase2-interface je (lokales, entferntes) Subnetz-Paar
    for i, lsub in enumerate(local.local_subnets):
        for j, rsub in enumerate(remote_subnets):
            p2 = f"{name}_{i}_{j}"
            ops.append(
                FortiOp(
                    method="POST",
                    path=f"{_CMDB}/vpn.ipsec/phase2-interface",
                    body={
                        "name": p2,
                        "phase1name": name,
                        "proposal": spec.phase2_proposal,
                        "src-subnet": lsub,
                        "dst-subnet": rsub,
                    },
                    summary=f"IPsec Phase2 {p2}: {lsub} ↔ {rsub}",
                    rollback_path=f"{_CMDB}/vpn.ipsec/phase2-interface/{p2}",
                )
            )

    # 4) statische Route je entferntem Subnetz über das Tunnel-Interface
    for rsub in remote_subnets:
        ops.append(
            FortiOp(
                method="POST",
                path=f"{_CMDB}/router/static",
                body={"dst": rsub, "device": name, "comment": f"NetBuddy VPN → {remote.site}"},
                summary=f"Route {rsub} → Tunnel {name}",
            )
        )

    # 5) Firewall-Policy (beide Richtungen) — nur wenn das interne Interface bekannt ist
    if local.lan_interface:
        local_addr = [{"name": _addr_name(s)} for s in local.local_subnets]
        remote_addr = [{"name": _addr_name(s)} for s in remote_subnets]
        ops.append(
            FortiOp(
                method="POST",
                path=f"{_CMDB}/firewall/policy",
                body={
                    "name": f"{name}_out",
                    "srcintf": [{"name": local.lan_interface}],
                    "dstintf": [{"name": name}],
                    "srcaddr": local_addr,
                    "dstaddr": remote_addr,
                    "action": "accept",
                    "schedule": "always",
                    "service": [{"name": "ALL"}],
                },
                summary=f"Policy {name}_out: {local.lan_interface} → Tunnel (lokal→remote)",
            )
        )
        ops.append(
            FortiOp(
                method="POST",
                path=f"{_CMDB}/firewall/policy",
                body={
                    "name": f"{name}_in",
                    "srcintf": [{"name": name}],
                    "dstintf": [{"name": local.lan_interface}],
                    "srcaddr": remote_addr,
                    "dstaddr": local_addr,
                    "action": "accept",
                    "schedule": "always",
                    "service": [{"name": "ALL"}],
                },
                summary=f"Policy {name}_in: Tunnel → {local.lan_interface} (remote→lokal)",
            )
        )
    return ops


def generate_psk() -> str:
    """Starkes Pre-Shared-Key (URL-safe, ~32 Zeichen)."""
    return secrets.token_urlsafe(24)


def plan_site_to_site(spec: VpnTunnelSpec) -> VpnPlan:
    """Erzeugt den vollständigen Dry-Run-Plan für beide Firewalls (rein, keine Geräte-Calls)."""
    psk = spec.psk or generate_psk()
    return VpnPlan(
        tunnel_name=spec.name,
        psk_generated=spec.psk is None,
        firewalls=[
            FirewallPlan(
                site=spec.end_a.site,
                device_id=spec.end_a.device_id,
                operations=_ops_for_end(spec, spec.end_a, spec.end_b, psk),
            ),
            FirewallPlan(
                site=spec.end_b.site,
                device_id=spec.end_b.device_id,
                operations=_ops_for_end(spec, spec.end_b, spec.end_a, psk),
            ),
        ],
    )


def _code(end: VpnEnd) -> str:
    """Kurzer Standort-Code für den FortiOS-Tunnelnamen (≤15 Zeichen)."""
    return (end.code or end.site[:3]).upper()


class MeshTunnel(BaseModel):
    """Ein Tunnel-Paar im Mesh (Name + die zwei beteiligten Standorte)."""

    name: str
    site_a: str
    site_b: str


class VpnMeshPlan(BaseModel):
    """Dry-Run-Plan für ein Full-Mesh: je Firewall die Operationen aller ihrer Paare."""

    tunnels: list[MeshTunnel]
    psk_generated: bool
    firewalls: list[FirewallPlan]


def plan_full_mesh(
    ends: list[VpnEnd],
    *,
    ike_version: int = DEFAULT_IKE_VERSION,
    phase1_proposal: str = DEFAULT_PHASE1_PROPOSAL,
    phase2_proposal: str = DEFAULT_PHASE2_PROPOSAL,
    dh_groups: str = DEFAULT_DH_GROUPS,
    psk: str | None = None,
) -> VpnMeshPlan:
    """Full-Mesh: erzeugt für jedes Standort-Paar einen Tunnel (eigenes PSK je Paar).

    Aggregiert die Operationen pro Firewall — jede FW bekommt einen Tunnel zu jeder anderen.
    Rein/ohne Geräte-Calls (Dry-Run). N Standorte → N*(N-1)/2 Tunnel.
    """
    if len({e.device_id for e in ends}) < 2:
        raise ValueError("Full-Mesh braucht mindestens zwei unterschiedliche Firewalls")

    by_dev: dict[str, FirewallPlan] = {
        e.device_id: FirewallPlan(site=e.site, device_id=e.device_id, operations=[]) for e in ends
    }
    tunnels: list[MeshTunnel] = []
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            a, b = ends[i], ends[j]
            tname = f"{_code(a)}-{_code(b)}"[:15]
            pair_psk = psk or generate_psk()
            spec = VpnTunnelSpec(
                name=tname,
                end_a=a,
                end_b=b,
                psk=pair_psk,
                ike_version=ike_version,
                phase1_proposal=phase1_proposal,
                phase2_proposal=phase2_proposal,
                dh_groups=dh_groups,
            )
            by_dev[a.device_id].operations.extend(_ops_for_end(spec, a, b, pair_psk))
            by_dev[b.device_id].operations.extend(_ops_for_end(spec, b, a, pair_psk))
            tunnels.append(MeshTunnel(name=tname, site_a=a.site, site_b=b.site))

    return VpnMeshPlan(tunnels=tunnels, psk_generated=psk is None, firewalls=list(by_dev.values()))
