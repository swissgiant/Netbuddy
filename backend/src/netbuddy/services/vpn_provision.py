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

import ipaddress
import secrets
from typing import Any, Protocol

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
    # idempotent = über Tunnel geteiltes Objekt (z.B. Adress-Objekt): existiert es bereits,
    # wird es NICHT neu angelegt und NICHT zurückgerollt (gehört evtl. einem anderen Tunnel).
    ensure: bool = False


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


def _fortimask(cidr: str) -> str:
    """CIDR → FortiOS-Format ``"ip netmask"`` (10.121.0.0/16 → '10.121.0.0 255.255.0.0')."""
    net = ipaddress.ip_network(cidr, strict=False)
    return f"{net.network_address} {net.netmask}"


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
                body={"name": an, "subnet": _fortimask(subnet)},
                summary=f"Adress-Objekt {an} ({subnet})",
                rollback_path=f"{_CMDB}/firewall/address/{an}",
                ensure=True,  # geteilt über Tunnel — existiert evtl. schon
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
                        "auto-negotiate": "enable",  # Tunnel kommt sofort hoch
                        "src-subnet": _fortimask(lsub),
                        "dst-subnet": _fortimask(rsub),
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
                body={
                    "dst": _fortimask(rsub),
                    "device": name,
                    "comment": f"NetBuddy VPN → {remote.site}",
                },
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


# --- Anwenden (Increment 2: Write → Rollback) ------------------------------------------------


class WriteClient(Protocol):
    """Schreibfähiger API-Client (vom Apply genutzt; in Tests fake-bar)."""

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any: ...
    async def post_json(self, path: str, body: dict[str, Any]) -> Any: ...
    async def put_json(self, path: str, body: dict[str, Any]) -> Any: ...
    async def delete(self, path: str) -> Any: ...


async def _exists(client: WriteClient, path: str, name: str) -> bool:
    """True, wenn ein cmdb-Objekt mit diesem Namen schon existiert (GET 200)."""
    try:
        await client.get_json(f"{path}/{name}")
        return True
    except Exception:
        return False


class ApplyOutcome(BaseModel):
    """Ergebnis eines Apply-Laufs auf EINER Firewall."""

    success: bool
    applied: list[str]  # Zusammenfassungen erfolgreich angewandter Operationen
    rolled_back: list[str]  # bei Fehler zurückgenommene Operationen
    error: str | None = None
    # DELETE-Pfade der angelegten Objekte (für Cross-FW-Rollback, wenn das ANDERE Ende scheitert)
    handles: list[str] = []


async def rollback_handles(client: WriteClient, handles: list[str]) -> list[str]:
    """Nimmt zuvor erfolgreich angelegte Objekte zurück (umgekehrte Reihenfolge)."""
    undone: list[str] = []
    for path in reversed(handles):
        try:
            await client.delete(path)
            undone.append(path)
        except Exception:
            pass
    return undone


async def apply_operations(client: WriteClient, operations: list[FortiOp]) -> ApplyOutcome:
    """Führt die geplanten Operationen der Reihe nach aus; bei Fehler **Rollback** in
    umgekehrter Reihenfolge (DELETE der bereits angelegten Objekte). Read-only-Voraussetzung:
    vorher ein Config-Backup ziehen (macht der Orchestrator/Endpoint).
    """
    # je angelegtem Objekt den DELETE-Pfad merken: aus der POST-Antwort die FortiOS-`mkey`
    # (Name bzw. Auto-ID von Routen/Policies) lesen → vollständiger Rollback auch ohne
    # vorhersehbaren Namen. Fallback: rollback_path aus dem Plan.
    created: list[tuple[FortiOp, str | None]] = []
    applied: list[str] = []
    try:
        for op in operations:
            # geteilte Objekte (ensure) nur anlegen, wenn sie noch nicht existieren — und dann
            # NICHT in die Rollback-Liste (gehören evtl. einem anderen Tunnel).
            nm = op.body.get("name")
            if op.ensure and nm and await _exists(client, op.path, nm):
                applied.append(f"(vorhanden) {op.summary}")
                continue
            if op.method == "POST":
                resp = await client.post_json(op.path, op.body)
            elif op.method == "PUT":
                resp = await client.put_json(op.path, op.body)
            else:
                raise ValueError(f"Unbekannte Methode: {op.method}")
            mkey = str(resp.get("mkey")) if isinstance(resp, dict) and resp.get("mkey") else None
            del_path = f"{op.path}/{mkey}" if mkey else op.rollback_path
            created.append((op, del_path))
            applied.append(op.summary)
        return ApplyOutcome(
            success=True,
            applied=applied,
            rolled_back=[],
            handles=[p for _, p in created if p],
        )
    except Exception as exc:
        rolled: list[str] = []
        for op, del_path in reversed(created):
            if del_path:
                try:
                    await client.delete(del_path)
                    rolled.append(op.summary)
                except Exception:
                    pass
        return ApplyOutcome(
            success=False,
            applied=applied,
            rolled_back=rolled,
            error=f"{type(exc).__name__}: {exc}",
        )


def detect_lan_interface(cmdb_interfaces: list[dict[str, Any]], subnet: str) -> str | None:
    """Findet das interne Interface, dessen IP im Standort-Subnetz liegt (für die Policy).

    FortiOS liefert `ip` als ``"10.121.10.1 255.255.255.0"``. Tunnel-Interfaces werden ignoriert.
    """
    net = ipaddress.ip_network(subnet, strict=False)
    for row in cmdb_interfaces:
        parts = str(row.get("ip") or "").split()
        if not parts or row.get("type") == "tunnel" or not row.get("name"):
            continue
        try:
            addr = ipaddress.ip_address(parts[0])
        except ValueError:
            continue
        if addr in net:
            return str(row["name"])
    return None
