# NetBuddy — Status-Snapshot (19. Juni 2026)

Punktgenauer Überblick: wo das Projekt steht, was am echten Fleet funktioniert, und was
als Nächstes kommt. Lebende Detail-Datei bleibt `STATUS.md`, die Roadmap `docs/gap-analysis.md`.

## Ziel (zur Erinnerung)
1. **VLANs automatisiert standortübergreifend** ausrollen — über Switches *und* Firewalls/VPN.
2. **Geräte finden/erkennen, per Name auflösen, Verbindungsort (Switch+Port) anzeigen.**

## Erfüllungsgrad
- **Säule 2 (Erkennen/Auflösen/Anzeigen): ~90 %.** Discovery, Crawl, ARP→IP→DNS, Suche,
  OUI-Herstellervermutung, Topologie mit Standort-Containern + VPN-Kanten, sortierbare Tabellen —
  alles am echten Fleet live. Offen: Restabdeckung (mehr Geräte aufnehmen), aktiver IP-Scan optional.
- **Säule 1 (VLAN-Write/Orchestrierung): ~15 %.** Schreib-*Fundament* existiert (Backup, Audit,
  RBAC, erster enger LLDP-Write). VLAN-Datenmodell/Write/Orchestrator + Restore/Dry-Run fehlen noch
  (Roadmap S32→S37).

## Was am echten Fleet live validiert ist
| Gerät | Adapter | Zugang | gelesen |
|---|---|---|---|
| BLS-SW-Core2 (Dell S5248F-ON) | dell_os10 | SSH | sysinfo, if (56), lldp (31), mac (338), arp (97) |
| BLS-SW-52 (Dell N2248PX-ON) | dell_os6 | **Telnet** (enable-Mode) | sysinfo, if (51), mac (193), arp (20), lldp (7) |
| bls-sw-53 (FS S5800-48MBQ) | fs_centec | SSH | sysinfo, if (54), mac (411), lldp (8) |
| BLS-FW1 (FortiGate FG200F 7.4.12) | fortigate | REST :10443 | sysinfo, if (31), arp (273), **10 VPN-Tunnel** |

Topologie zeigt die echten WAN-Tunnel: Sulgen↔USA / Cusano / Grosuplje (Partner-Tunnel
ausgeblendet via „berücksichtigen"-Schalter).

## Architektur in einem Absatz
Modular-Monolith: FastAPI + async SQLAlchemy/Postgres, Redis/ARQ für geplante Jobs. Zwei
Adapter-Klassen — **deklarative YAML-Profile** (CLI/TextFSM, ein Vendor = Profil + Fixtures +
Conformance-Test, kein Code) und **API-Adapter** (JSON/XML/GraphQL). Transport: Scrapli
(SSH/Telnet, read-only-Guard; getrennter SSH-Write-Pfad) bzw. HttpxApiClient. Frontend:
React/Vite + Cytoscape. Geheimnisse Fernet-verschlüsselt, RBAC (viewer/operator/admin), Audit-Log.

## Vendor-Abdeckung
- **CLI-Profile (6):** cisco_ios, dell_os10, dell_os6, fs_ruijie, fs_centec, aruba_cx — alle mit
  `read_arp` + LLDP-Mgmt-IP. (cisco/fs_ruijie/aruba doku-abgeleitet, noch nicht am Gerät bestätigt.)
- **API-Adapter (6):** unifi, meraki, fortigate (live), paloalto (PAN-OS XML), cato (GraphQL),
  watchguard (bewusst Skeleton — Fireware-Session-Login noch nicht angebunden).

## Roadmap (docs/gap-analysis.md)
S30/S31 ✅ Discovery komplett · S32 Restore + **Dry-Run** + Multi-Device-`ConfigTransaction`
(Fundament) · S33 VLAN **read** · S34 VLAN write fs_centec (Freigabe-Gate) · S35 Multi-Switch-
Orchestrator · S36 ✅ (vorgezogen: Fortigate/VPN, sortierbare Tabellen) · S37 standortübergreifender
Rollout über die Firewalls · S38 Prod-Deployment.

> Wichtig: einen **echten Dry-Run gibt es noch nicht** (nur Backup→Write→Verify). Er ist der erste
> Baustein von S32, bevor VLANs geschrieben werden.

## Lokal starten / Dev-Server
```bash
# DB/Redis
cd docker && ./scripts/dev-up.sh   # bzw. docker compose up -d
# Backend (API :8000)
cd backend && uv run uvicorn netbuddy.api.main:app --host 0.0.0.0 --port 8000
# Frontend (GUI :5173)
cd frontend && npm run dev
# Gates
cd backend && uv run ruff check . && uv run mypy src/ tests/ && uv run pytest
```
GUI: http://localhost:5173/ (WSL-Fallback: http://<hostname -I>:5173/).

Diese **zwei Hintergrund-Server (Backend :8000, Frontend :5173) laufen dauerhaft** — das ist
gewollt, damit die App im Browser erreichbar bleibt; es sind keine hängenden/verwaisten Prozesse.
