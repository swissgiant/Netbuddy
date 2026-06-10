# NetBuddy — Gap-Analyse (Stand Juni 2026)

## 1. Wo wir stehen (Kurzfassung)

**Zielsäule 1 — VLANs automatisiert standortübergreifend ausrollen: ~15 %.** Das *Fundament* für sichere Schreibzugriffe existiert und ist real erprobt: Config-Backup mit SHA256-Dedupe und Diff (`backend/src/netbuddy/services/backup.py`), Audit-Log (`services/audit.py`), RBAC (operator+ für Writes, `api/deps.py`) und ein erster, live funktionierender Schreibpfad (LLDP-Enable auf fs_centec via `services/lldp_control.py` + `ScrapliTransport.send_config()`, S29 auf bls-sw-53 validiert). Aber von VLANs selbst existiert **nichts**: keine `READ_VLANS`-Capability, kein `VlanData`-DTO, kein `Vlan`-ORM-Modell, kein `read_vlan` in irgendeinem der 6 CLI-Profile, kein Endpoint, keine GUI, kein Orchestrator (der in CLAUDE.md:78 erwähnte „VLAN-Orchestrator" ist ein Ghost). Standortübergreifend wird es noch dünner: Firewalls sind read-only mit 2 von 6 Capabilities (Fortigate, unvalidiert), VPN-Tunnel sind weder modelliert noch lesbar, WatchGuard/PaloAlto/Cato-Adapter fehlen komplett. Restore/Rollback und Dry-Run — laut CLAUDE.md Pflicht vor Schreibzugriff — sind nicht implementiert.

**Zielsäule 2 — Devices finden, per Name auflösen, Switch+Port anzeigen: ~65 %.** Die Pipeline steht Ende-zu-Ende und läuft live auf Dell OS10 und FS Centec: Discovery (Interfaces/LLDP/MAC/ARP, `services/discovery.py`), rekursiver LLDP-Crawl mit Auto-Add (`services/crawl.py`), ARP→IP→Reverse-DNS-Korrelation (`services/hosts.py`), Endgerät-Suche per Name/IP/MAC → Switch+Port+VLAN (`services/locate.py`, `GET /search`), OUI-Herstellervermutung (39k Präfixe), ARQ-Worker für periodische Discovery, GUI mit Topologie-Graph und 1-Klick-Geräteanlage. Die Lücken sind Flächendeckung, nicht Architektur: `read_arp` und LLDP-`mgmt_address` nur in 2 von 6 CLI-Profilen (Dell OS6 — mehrfach im Fleet! — FS Centec, FS Ruijie, Aruba CX fehlen), API-Adapter ohne ARP, Namensauflösung nur manuell statt periodisch, MAC-OUI-basierte Geräteerkennung (Alex' offener Wunsch) fehlt, und der Crawl legt alles hartcodiert als SWITCH ohne Adapter-Fallback an. Querschnitts-Risiko für beide Säulen: Packaging (Profile/Templates/oui.csv nicht im Wheel deklariert) und fehlendes Production-Deployment.

## 2. Blocker — was das Ziel aktuell unmöglich macht

**B1 — VLAN-Datenpfad existiert in keiner Schicht (Read).**
*Was fehlt:* `Capability.READ_VLANS` (`adapters/capabilities.py` hat nur 6 Read-Capabilities), `VlanData`-DTO (`adapters/dto.py` — vlan_id existiert nur als Nebenfeld in `MacEntryData`/`ArpData`), `Vlan`-ORM-Modell (`db/models/` hat keins), Discovery-Integration (`services/discovery.py` prüft die Capability nicht), `GET /devices/{id}/vlans` (fehlt in `api/routes/devices.py`), `read_vlan`-Befehl in 0 von 6 Profilen (`adapters/profiles/*.yaml`), kein einziges `*vlan*`-TextFSM in `adapters/cli_templates/`.
*Warum blockierend:* Ohne VLANs lesen → kein Inventar → kein Soll/Ist-Abgleich → kein sicheres Schreiben. Das ist die komplette Vorstufe zum Produktziel.
*Was zu tun ist:* Die ganze Kette in einem Paket: Capability + DTO (vlan_id, name, status, mtu) + ORM (PK device_id+vlan_id) + Migration + Discovery-Upsert + Endpoint + `show vlan`-Parser je Profil mit Fixtures (Conformance-Test erzwingt das automatisch).

**B2 — Kein Multi-Device-Transaktionsmodell (VLAN-Orchestrator).**
*Was fehlt:* `services/lldp_control.py` zeigt das Backup→Write→Verify-Muster für **ein** Gerät; es gibt keine generalisierte `ConfigTransaction` über mehrere Geräte (Backup alle → Write alle → Verify alle → bei Teilfehler Rollback alle). CLAUDE.md:78 verspricht den Orchestrator in `services/`, er existiert nicht.
*Warum blockierend:* „VLAN unternehmensweit ausrollen" ist per Definition eine Multi-Switch-Operation; ohne Transaktionalität hinterlässt jeder Teilfehler inkonsistente Netze.
*Was zu tun ist:* `services/vlan_orchestrator.py` (bzw. generische `ConfigTransaction`): Geräte-Liste + Commands pro Profil, Dry-Run, Backups, serielle/parallele Ausführung mit Fehlersammlung, Rollback-Queue; Ergebnis `{ok, failed, rolled_back}`. Tests mit Fehler-Injektion (Gerät 3 von 5 scheitert).

**B3 — Restore/Rollback nicht implementiert.**
*Was fehlt:* `services/backup.py` kann nur `backup_device()` + `diff_latest()`. Kein `restore_device()`, kein `POST /devices/{id}/backups/{backup_id}/restore`, keine Restore-Sequenz in den Profilen (nur `backup_command`).
*Warum blockierend:* Backup ohne Restore ist kein Rollback-Anker — und CLAUDE.md macht funktionierende Backup-Logik zur Bedingung für Schreibzugriff. B2 (Rollback bei Teilfehler) hängt direkt daran.
*Was zu tun ist:* `restore_device(session, device, adapter, backup_id)` → Backup laden → `send_config()` → Re-Read-Verify → Audit `device.restore`; Restore-Template pro Profil (Centec/Cisco unterscheiden sich); live auf fs_centec testen.

**B4 — Kein Dry-Run-Modus.**
*Was fehlt:* `send_config()` schreibt direkt; kein `dry_run`-Parameter, kein `validate_command`-Feld in `LldpControlSpec`/Profilen (`adapters/profile.py`).
*Warum blockierend:* CLAUDE.md Phase 3 fordert Dry-Run explizit; ohne Preview ist ein Multi-Switch-VLAN-Rollout auf Produktiv-Hardware nicht verantwortbar.
*Was zu tun ist:* Dry-Run-Konzept im Write-Pfad (Befehle rendern + anzeigen ohne Senden, optional vendor-spezifische Validierungsbefehle), als Flag in B2/B3 von Anfang an mitdesignen.

**B5 — Firewall/VPN-Seite praktisch leer.**
*Was fehlt:* `adapters/fortigate.py` meldet nur `{READ_SYSTEM_INFO, READ_INTERFACES}` (unvalidiert, nie gegen echte FortiGate getestet — dabei ist FortiOS „fast überall" im Fleet, `docs/fleet-and-adapters.md`). Kein VpnTunnel-Modell in `db/models/`, keine `READ_VPN_TUNNELS`/FW-VLAN-Capability, kein Site↔Site-Konzept (Site hat nur name/code/description, kein Gateway-Bezug), WatchGuard/PaloAlto/Cato ohne jeden Stub.
*Warum blockierend:* „Standortübergreifend über Firewalls/VPN" ist ohne Tunnel-Sichtbarkeit und FW-VLAN-Lesefähigkeit nicht einmal anzeigbar, geschweige denn orchestrierbar.
*Was zu tun ist:* Erst read: Fortigate live validieren, dann erweitern (VLAN-Interfaces via `/api/v2/cmdb/system/interface`, Tunnel via `/api/v2/cmdb/vpn.ipsec/phase1-interface`), VpnTunnel-Modell (local_site, remote_site, firewall, type, status), Site-Gateway-Verknüpfung, Topologie um Site↔Site-Kanten. Write erst danach.

**B6 — Autodiscovery-Reichweite: `mgmt_address` + `read_arp` nur in 2/6 Profilen.**
*Was fehlt:* Nur `cisco_ios.yaml` + `dell_os10.yaml` parsen die LLDP-Management-IP und ARP. `dell_os6.yaml` (N2248PX-ON mehrfach im Fleet!), `fs_centec.yaml` (live!), `fs_ruijie.yaml`, `aruba_cx.yaml` enden nach `read_mac_table`.
*Warum blockierend (für Zielsäule 2):* Ohne mgmt_address kann der Crawl Nachbarn hinter diesen Switches nicht automatisch anlegen; ohne ARP keine Name↔IP↔MAC-Auflösung für Endgeräte an einem Großteil der Flotte — `GET /search` per Name läuft dort ins Leere.
*Was zu tun ist:* TextFSM-Templates + Capability-Blöcke für die 4 fehlenden Profile (`show ip arp` / `show arp`, LLDP-Detail-Mgmt-Address); Fixtures aus echten Captures, live gegen bls-sw-53 und Dell OS6 validieren.

**B7 — Packaging: ~~Profile/Templates/oui.csv fehlen im Build~~ — GEPRÜFT: FEHLALARM.**
*Nachverifiziert (S30):* `uv build` + Wheel-Inspektion zeigt 6 profiles/*.yaml, 27 cli_templates/*.textfsm und data/oui.csv im Wheel — das uv-Build-Backend nimmt alle Dateien unter `src/netbuddy/` automatisch mit. Kein Handlungsbedarf; bei einem Wechsel des Build-Backends erneut prüfen (`uv build` und Wheel-Inhalt auf profiles/cli_templates/oui.csv greppen).

**B8 — Kein Production-Deployment (Dockerfiles, TLS, Worker, Migrations).**
*Was fehlt:* `docker/docker-compose.yml` enthält nur Dev-Infra (postgres, redis, adminer). Kein Backend-/Frontend-Dockerfile, kein Reverse-Proxy/TLS (Credentials + Session-Tokens gehen plaintext), ARQ-Worker nicht als Service orchestriert (manueller Start, kein Restart), `alembic upgrade head` läuft nicht im Entrypoint (`api/main.py` lifespan macht es nicht), Session-Cookie ohne `secure=True` (`api/routes/auth.py:42`), Fernet-Key-Generierung undokumentiert (`.env.example` mit Platzhalter → Crash beim ersten Credential-Write).
*Warum blockierend:* Zielumgebung laut CLAUDE.md ist „On-Prem VM via Docker Compose" — aktuell nicht deploybar.
*Was zu tun ist:* backend/frontend-Dockerfiles (multi-stage), Prod-Compose mit backend + worker + nginx/TLS + Healthchecks, Migrations im Entrypoint, `use_secure_cookies`-Setting, Key-Gen-Doku/Skript.

## 3. Nicht verdrahtet / halbfertig

**Backend-Features ohne GUI:**
- **Backups:** `GET /devices/{id}/backups`, `/backups/{backup_id}`, `/config-diff` existieren — Frontend ruft nur `POST /backup` auf. Kein Backup-Tab, kein Diff-Viewer (`frontend/src/views/DeviceDetail.tsx`).
- **Validierungs-Historie:** `GET /devices/{id}/validation` wird nie aufgerufen; DeviceDetail zeigt nur das Ergebnis des letzten POST (`DeviceDetail.tsx:45`).
- **Audit-Log:** `GET /audit` (admin) hat keine View.
- **Assistiertes Onboarding:** `POST /devices/{id}/suggest-profile` komplett ohne UI-Verdrahtung (`api.ts` hat keine Funktion dafür).
- **Crawl-Fehler:** nur Anzahl gerendert, Details (`errors: {device, error}[]`) verworfen (`DevicesView.tsx:203`).
- **Capabilities/Provenance:** weder in der Geräte-Tabelle noch im Device-Detail sichtbar (nur `adapter_id`-Text, `DeviceDetail.tsx:137`).

**Capability-/Adapter-Lücken (read-seitig, pro Vendor — Details Matrix unten):**
- `lldp_control` (Write) nur in `fs_centec.yaml`; alle anderen Profile geben 400 auf `POST /devices/{id}/lldp/enable`.
- Cisco IOS und Aruba CX komplett unvalidiert; dell_os6/fs_ruijie nur sysinfo live, Rest doku-abgeleitet.
- API-Adapter: UniFi ohne ARP, Meraki ohne MAC-Table (plus toter Code: `get_mac_table()` raised, ist aber gar nicht in `capabilities_set`, `meraki.py:32-34` vs. `:106`), Fortigate ohne LLDP/MAC — nirgends dokumentiert, ob Absicht oder TODO.
- `aruba_cx.yaml:35-36`: case-sensitives `lookup {"yes": up}` — kippt bei `Yes` in den unknown-Fallback.

**Discovery/Crawl halbfertig:**
- Crawl legt neue Geräte hart als `DeviceType.SWITCH` an (`services/crawl.py:123`) — Firewalls werden falsch klassifiziert; ohne `system_description` bleibt `adapter_id` leer statt OUI-Fallback (FS→fs_centec, Dell→dell_os10, …) → Gerät read-only unbenutzbar.
- Periodische Discovery aktualisiert ARP, ruft aber nie `correlate_hosts()` — Namensauflösung bleibt manueller Button (`workers/discovery_worker.py`).
- MAC-Table-OUI-Geräteerkennung (LLDP-lose Geräte vorschlagen) — Alex' angefragtes Feature, nicht begonnen.
- UniFi: nur per-Device-Match (`match_ip`), keine Controller-Bulk-Discovery, obwohl ein Controller 50+ Geräte verwaltet.

**Sonstiges:**
- `ScrapliTransport.send_config()` hat bewusst keinen Read-only-Guard — okay solange nur der LLDP-Endpoint ihn nutzt, aber ein Design-Risiko, sobald weitere Write-Pfade entstehen; `LldpControlSpec` ist LLDP-hartcodiert statt generischer WriteOpSpec (`adapters/profile.py:87-106`).
- `Credential.extra` (org_id/site für API-Adapter) wird von `unifi.py:36` erwartet, ist aber über `POST /credentials` nicht eingebbar.
- `locate()` filtert weder statische MAC-Einträge noch VLAN-Kontext — Cross-VLAN-/Uplink-Falschtreffer möglich.
- Audit-Actions sind ad-hoc-Strings (`device.lldp_enable`), kein Namespace/Enum, Details ohne backup_id/Fehlertext.

## 4. Capability-Matrix

✅ live-validiert · ⚠️ implementiert, aber unvalidiert (Doku-/Research-abgeleitet) · ❌ fehlt

| Adapter/Profil | SysInfo | Interfaces | LLDP | MAC-Table | ARP | Config/Backup | LLDP-Mgmt-IP | LLDP-Write | VLANs (r/w) |
|---|---|---|---|---|---|---|---|---|---|
| dell_os10 (CLI) | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ❌ | ❌ |
| fs_centec (CLI) | ✅ | ✅ | ✅¹ | ✅ | ❌ | ✅² | ❌ | ✅ | ❌ |
| dell_os6 (CLI) | ✅ | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ |
| fs_ruijie (CLI) | ✅ | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ |
| cisco_ios (CLI) | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ |
| aruba_cx (CLI) | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ |
| unifi (API) | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | n/a | ❌ | ❌ |
| meraki (API) | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | n/a | ❌ | ❌ |
| fortigate (API, FW) | ⚠️ | ⚠️ | ❌ | n/a | ❌ | ❌ | n/a | n/a | ❌ |
| watchguard / paloalto / cato | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

¹ live geprüft, S29 (LLDP-Enable wirksam, Core sieht bls-sw-53). ² im LLDP-Write-Pfad als Backup-Anker live genutzt.
**Die VLAN-Spalte ist durchgehend ❌ — das ist die Kernlücke zum Produktziel.** VPN-Tunnel: in keinem Adapter vorhanden.

## 5. Empfohlene Reihenfolge

**S30 — ARP + LLDP-Mgmt-IP flächendeckend (Discovery/Namensauflösung komplettieren).**
`read_arp` + `mgmt_address`-Mapping für fs_centec, fs_ruijie, dell_os6, aruba_cx (TextFSM + Fixtures aus echten Captures; live-Validierung auf bls-sw-53 und einem N2248PX-ON).
*Akzeptanz:* `read_arp` in 6/6 CLI-Profilen, Conformance grün mit neuen Fixtures, `GET /search?q=<name>` findet ein Endgerät hinter dem FS S5800, Crawl legt einen Nachbarn hinter einem OS6-Switch automatisch mit Mgmt-IP an.

**S31 — Discovery-Härtung + Geräteerkennungs-Lücken.**
(a) Worker ruft `correlate_hosts()` periodisch auf (Config-Flag), (b) Crawl: `device_type` aus Adapter-Erkennung statt hardcoded SWITCH, OUI-basierter Adapter-Fallback ohne system_description, (c) MAC-Table-OUI-Vorschläge (`suggest_devices_from_mac_table()` + GUI-Karte neben LLDP-Vorschlägen), (d) Crawl-Fehlerdetails im GUI als aufklappbare Tabelle.
*Akzeptanz:* Hostnamen aktualisieren sich ohne manuellen Button; ein LLDP-loser FS-Switch erscheint als Vorschlag mit Vendor-Vermutung; Fortigate via Crawl wird als FIREWALL angelegt.

**S32 — Write-Fundament: Restore, Dry-Run, ConfigTransaction.**
`restore_device()` + `POST /devices/{id}/backups/{backup_id}/restore` (operator+, Audit `device.restore`), Dry-Run-Flag im Write-Pfad (Commands rendern/anzeigen ohne Senden), generische `ConfigTransaction` (Multi-Device Backup→Write→Verify→Rollback, Fehlersammlung), Audit-Action-Namespace statt ad-hoc-Strings. GUI: Backup-Tab (Liste/Inhalt/Diff) in DeviceDetail.
*Akzeptanz:* Restore live auf bls-sw-53 demonstriert (Backup → triviale Änderung → Restore → Diff leer); Transaktionstest mit injiziertem Fehler bei Gerät 3/5 rollt 1–2 zurück; jeder Write erscheint im Audit-Log mit backup_id.

**S33 — VLAN read (komplette Kette).**
`Capability.READ_VLANS`, `VlanData`-DTO, `Vlan`-ORM + Migration, Discovery-Upsert, `GET /devices/{id}/vlans`, `read_vlan` in allen 6 Profilen (`show vlan`-TextFSM + Fixtures), GUI: VlansView read-only (VLAN-ID, Name, Status, Switch-Count, Site-Filter).
*Akzeptanz:* Conformance 6×READ_VLANS grün; live-Discovery auf Dell Core + FS S5800 persistiert echte VLANs; VlansView zeigt sie konsolidiert über Geräte.

**S34 — VLAN write, ein Vendor (fs_centec, nach Alex' Freigabe — Phase F-Gate).**
`VlanControlSpec` (create/delete/name-Templates) analog `LldpControlSpec`, Service nutzt S32-Pattern (Dry-Run → Backup → Write → Verify), Endpoint + GUI-Dialog für ein Gerät.
*Akzeptanz:* VLAN auf bls-sw-53 per GUI angelegt + verifiziert + gelöscht; Dry-Run zeigt exakt die CLI-Zeilen vorab; Audit + Backup vorhanden; Restore-Pfad als Fallback getestet.

**S35 — VLAN-Orchestrator: Multi-Switch-Rollout.**
`vlan_orchestrator.py` auf Basis ConfigTransaction: VLAN-Definition → Ziel-Auswahl (Geräte/Sites) → Rollout mit Fortschritt + Rollback bei Teilfehler; `VlanControlSpec` für dell_os10 als zweiten Vendor; GUI: „VLAN anlegen auf N Switches".
*Akzeptanz:* VLAN auf FS + Dell in einem Vorgang ausgerollt; simulierter Fehler auf Gerät 2 rollt Gerät 1 zurück; Ergebnisreport {ok/failed/rolled_back} im GUI.

**S36 — Firewall/VPN read (Fortigate zuerst).**
Fortigate live validieren (API-Token aus Fleet), erweitern um FW-VLAN-Interfaces + VPN-Tunnel (READ_VPN_TUNNELS, `VpnTunnel`-Modell: local/remote_site, firewall, type, status), Site um Gateway-Bezug (z. B. `primary_firewall_id`), Topologie um Site↔Site-Tunnel-Kanten.
*Akzeptanz:* Echte FortiGate im Inventar mit Interfaces+VLANs+Tunneln; Topologie zeigt zwei Sites über einen IPsec-Tunnel verbunden; Provenance auf „live-validiert".

**S37 — Standortübergreifender Rollout (Nordstern) + weitere Firewalls.**
Fortigate-VLAN-Write (`PUT /api/v2/cmdb/...`, gleiches Backup/Verify/Dry-Run-Muster), Orchestrator erweitert um FW-Schritt (VLAN auf Switches Site A + B **und** FW/Tunnel-Konfig konsistent); WatchGuard/Cato/PaloAlto als Skeleton-Adapter nach realem Bedarf.
*Akzeptanz:* Ein VLAN landet in einem Vorgang auf Switches zweier Sites + zugehöriger Firewall-Konfig, atomar mit Rollback; alles im Audit-Log.

**S38 — Betrieb/Deployment.**
Package-Data-Fix in `pyproject.toml` + Wheel-Smoke-Test (kann bei Gelegenheit auch früher als Quick-Win), backend/frontend-Dockerfiles, Prod-Compose (backend, worker, nginx/TLS, Healthchecks, restart-Policies), Alembic im Entrypoint, `secure=True`-Cookies via `use_secure_cookies`-Setting, Fernet-Key-Doku/Skript, GitHub-Actions (ruff/mypy/pytest), pg_dump-Backup-Doku.
*Akzeptanz:* Frische VM: `.env` befüllen → `docker compose up -d` → App über HTTPS erreichbar, Worker läuft, Migrationen automatisch, Wheel enthält profiles/cli_templates/oui.csv nachweislich.

## 6. Bewusst verschoben

Fürs Produktziel **nicht** nötig und daher zurückgestellt: **STP/RSTP-Analyzer** (Kernfeature #4, aber orthogonal zu VLAN-Rollout und Lokalisierung), **KI-gestützte Adapter-Generierung** (Phase 5), **NetBIOS/mDNS/DHCP-Namensfallback** (erst wenn Reverse-DNS-Pfad in der Fläche steht), **Monitoring/Prometheus + Secrets-Rotation** (Solo-On-Prem, Doku reicht vorerst), **UniFi-Controller-ORM-Modell und Bulk-Discovery-Vertiefung** (Crawl über LLDP deckt das meiste ab), **semantische Config-Versionierung** (Zeilen-Diff genügt), **Meraki-MAC-Table-Recherche** (API vermutlich nicht vorhanden, nur dokumentieren), sowie weiterhin kein Kubernetes, keine Microservices, kein erweitertes RBAC über die drei Rollen hinaus.
