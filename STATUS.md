# NetBuddy — Aktueller Stand

**Stand:** 24. Juni 2026, Phase 1+ — Discovery/Erkennung am echten Fleet feature-komplett; **S38 Deployment fertig** (Prod-Docker-Stack End-to-End getestet, `docs/deployment.md`) → Ziel-VM Ubuntu 26.04 (4 vCPU/8 GB/100 GB) wird bereitgestellt. Roadmap Richtung VLAN-Write in `docs/gap-analysis.md`.

Projektkontext und Konventionen stehen in `CLAUDE.md`. Diese Datei dokumentiert nur den **aktuellen Fortschritt** und was als Nächstes ansteht. Letzter Commit `d30993b` (S36).

## Was läuft gerade

| Komponente | Status |
|---|---|
| Docker-Dev-Stack (postgres + redis + adminer) | `healthy`; Endpoints lt. README |
| Alembic-Head | `8c7971315c66` (`interface parent_name + vlan_id`) — 11 Migrationen |
| `ruff` / `mypy --strict` / `pytest` | Alle drei grün (**193 Tests**) |
| Dev-Server (laufen im Hintergrund für die GUI) | Backend `uv run uvicorn netbuddy.api.main:app` (:8000), Frontend `npm run dev` (:5173) — bewusst dauerhaft an, damit die App im Browser erreichbar ist |
| **Live-validierte Vendor** (echtes Fleet) | **dell_os10** (Core, SSH), **dell_os6** (N2248PX, **Telnet**: enable-Mode + User:-Prompt), **fs_centec** (S5800, SSH), **fortigate** (FG200F 7.4.12, REST :10443) |
| CLI-Profile (6) | cisco_ios, dell_os10, dell_os6, fs_ruijie, fs_centec, aruba_cx — alle mit `read_arp` + LLDP-Mgmt-IP; fs_ruijie/cisco/aruba doku-abgeleitet (unvalidiert) |
| API-Adapter (6) | unifi, meraki, **fortigate** (sysinfo/interfaces/arp/lldp/**vpn-tunnels**, live), paloalto (PAN-OS XML), cato (GraphQL), watchguard (Skeleton ohne Caps) |
| Transport | `ScrapliTransport` (SSH **+ Telnet** read-only; Write-Pfad SSH-only via interaktivem asyncssh); API via `HttpxApiClient` (vendor-korrekte Auth-Header) |
| GUI (React/Vite/Cytoscape) | Topologie (Standorte=Container, VPN-Kanten ab Firewall, stabiles Layout, Auto-Zoom), Geräte (Inventar+Detail mit Faceplate/Interface-Baum/Tabs), **Discovery** (eigene Kategorie), Standorte (IP-Segmente+Namens-Regel), Credentials, Benutzer — alle Tabellen sortierbar |
| Erster Schreibpfad (eng, freigegeben) | LLDP aktivieren (Backup→write→verify, profil-gesteuert, nur SSH) — **echter Write/VLAN noch GESPERRT bis S32-Fundament** |
| ARQ-Worker | geplante Discovery + Host-Korrelation: `uv run arq netbuddy.workers.discovery_worker.WorkerSettings` |

## Was bereits gebaut wurde

### Session 1 — FastAPI-Skelett
- Modulstruktur `api/`, `api/routes/`, `core/`, `db/`, `services/`, `adapters/`, `workers/`
- `core/config.py` (pydantic-settings), `core/logging.py` (Loguru)
- `api/main.py` mit `create_app()` + Lifespan
- `api/routes/health.py` → `GET /health` antwortet `{"status":"ok","app":"NetBuddy"}`
- `pyproject.toml` ruff/mypy/pytest konfiguriert
- `backend/.env`, `backend/.env.example`, Repo-Root `.gitignore`
- `tests/test_health.py` (httpx + ASGITransport)

### Session 2 — Dev-Infrastruktur
- `docker/docker-compose.yml` (postgres:16-alpine, redis:7-alpine, adminer; Healthchecks; named volume `pgdata`)
- `scripts/dev-up.sh`, `scripts/dev-down.sh`
- `.env.docker.example` + `.env.docker` (gitignored)
- README mit "Development Setup"-Abschnitt
- `backend/.env` → DATABASE_URL zeigt auf Docker-Postgres

### Session 3 — Phase-1-Schema + Fernet
- `core/config.py` erweitert um `fernet_key: SecretStr`
- `db/base.py` (`Base`, `TimestampMixin`, `SoftDeleteMixin`)
- `db/session.py` (async engine + `SessionLocal` + `get_session()` Dependency)
- `db/types.py` (`EncryptedString` TypeDecorator, `enum_values` helper)
- `db/models/*.py` — 7 Aggregate: `Device`, `Credential`, `DeviceCredential`, `Interface`, `LldpNeighbor`, `MacAddressEntry`, `DiscoveryRun`
- `alembic/` initialisiert (async template), `env.py` zieht URL aus Settings, `render_item`-Callback für `EncryptedString`-Import in Migrationen
- Migration `c31556efa8b2_phase1_initial_schema.py` — Upgrade/Downgrade reversibel (Enums werden im `downgrade()` explizit gedropt)
- `tests/conftest.py` — separate Test-DB `netbuddy_test`, `create_all`/`drop_all` per Test
- `tests/db/test_models.py` — 3 Tests: Device+Credential-Link, EncryptedString-Roundtrip, Soft-Delete

### Session 4 — Erstes DB-Endpoint + Git
- **Git-Sicherung:** 5 thematische Commits, gepusht auf `origin` (`github.com/swissgiant/Netbuddy`, HTTPS via `gh`)
- `api/deps.py` — wiederverwendbare `SessionDep` (`Annotated[AsyncSession, Depends(get_session)]`, vermeidet B008)
- `api/routes/devices.py` — `GET /devices` (paginiert via `limit`/`offset`, nach Hostname sortiert, Soft-Deleted ausgeblendet) + `GET /devices/{id}` (404 bei fehlend/gelöscht); `DeviceRead`-Schema (`from_attributes`, `mgmt_ip` als `IPvAnyAddress`)
- `tests/conftest.py` — `api_client`-Fixture: httpx-Client mit `get_session`-Override gegen die Test-DB
- `tests/api/test_devices.py` — 6 Endpoint-Tests
- `pyproject.toml` — mypy-Override für `asyncpg` (keine Stubs), damit die Gate auch `tests/` abdeckt

### Session 5 — Vendor-Abstraction-Layer + Cisco-IOS-Adapter
- `adapters/capabilities.py` — `Capability(StrEnum)`: `READ_SYSTEM_INFO` / `READ_INTERFACES` / `READ_LLDP` / `READ_MAC_TABLE`
- `adapters/dto.py` — vendor-neutrale Pydantic-DTOs (`SystemInfo`, `InterfaceData`, `LldpNeighborData`, `MacEntryData`); Enums aus `db/models` wiederverwendet (Single Source of Truth)
- `adapters/transport.py` — `CommandTransport`-Protocol (`async send_command`) + `MockTransport` (Canned-Output); echter SSH-Transport bewusst noch nicht
- `adapters/base.py` — `SwitchAdapter`-Protocol (alle 4 Read-Methoden) + `AdapterError`/`CapabilityNotSupportedError`
- `adapters/registry.py` — `@register_adapter`, `get_adapter_class`, `available_adapters`, `UnknownAdapterError`
- `adapters/cisco_ios.py` — `CiscoIosAdapter`, read-only, parst `show version`/`interfaces`/`lldp neighbors detail`/`mac address-table` via **ntc-templates** → DTOs; defensive Enum-Mappings (Fallback `UNKNOWN`/`DYNAMIC`)
- `pyproject.toml` — `ntc-templates`-Dependency + mypy-Override für `ntc_templates.*`/`textfsm.*`
- Tests: `tests/adapters/` mit Fixture-Dateien (`fixtures/cisco_ios/*.txt`); 8 neue Tests (Registry + 4 Read-Methoden + Leer-Output)
- **Read-only-first gewahrt:** kein echter Geräte-Zugriff im Code — Transport wird injiziert, getestet gegen Mock

### Session 6 — Echter Scrapli-Transport + ConnectionParams (read-only, kein Live-Zugriff)
- `adapters/connection.py` — `ConnectionParams` (Pydantic, Passwörter als `SecretStr`) + `params_from_credential(device, credential)`; Plattform-Map `cisco_ios → cisco_iosxe` (unbekannt → `ValueError`)
- `adapters/scrapli_transport.py` — `ScrapliTransport`: async Context-Manager, hält die Verbindung über mehrere Adapter-Aufrufe offen; baut `AsyncScrapli(..., transport="asyncssh", auth_strict_key=False)`; **injizierbarer `driver_factory`** → Tests ohne Hardware; **Read-only-Guard** lehnt Nicht-`show`/`display`-Befehle mit `TransportError` ab
- `pyproject.toml` — `scrapli[asyncssh]`-Dependency (scrapli 2026.02.20, getypt → kein mypy-Override nötig)
- Tests: `test_connection.py` (Mapping, fehlende Passwörter, unbekannte adapter_id) + `test_scrapli_transport.py` (ctx-Manager open/close, Guard, E2E `CiscoIosAdapter` gegen Fake-Driver mit den `show`-Fixtures) — 6 neue Tests
- **Read-only-first gewahrt:** weiterhin kein echter Geräte-Zugriff im Code — der Fake-Driver ersetzt die Verbindung in allen Tests

### Session 7 — Refactor auf deklarative Vendor-Profile (Framework first)
- **Motivation:** Multi-Vendor (Dell, FS.com, …) + spätere KI-Adapter-Generierung. Handgeschriebener Code pro Vendor skaliert nicht.
- `adapters/profile.py` — Pydantic-Schema (`VendorProfile`/`CapabilitySpec`/`FieldSpec`, Shorthand-Normalisierung) + YAML-Loader (`load_profile`, `load_profiles_from_package`)
- `adapters/converters.py` — benannte Transform-Registry: `strip_or_none`, `first`, `first_word`, `int_or_none`, `kbit_to_mbps`, `lower`, parametrisiert `lookup`/`enum_value`; `build_converter` + `apply_pipeline`
- `adapters/parsers.py` — `parse()`-Dispatcher: `ntc` (ntc-templates) + `textfsm:<datei>` (custom Template aus `cli_templates/`, für Vendor ohne ntc-Abdeckung wie FS.com); `parse_textfsm_text` als testbarer Kern
- `adapters/mapping.py` — `build_dto` (Source + Converter-Pipeline → DTO, Pydantic validiert/coerced)
- `adapters/declarative.py` — `DeclarativeAdapter`: interpretiert ein Profil über einem Transport, erfüllt `SwitchAdapter`; `drop_when_empty`-Filter; `CapabilityNotSupportedError` für fehlende Capabilities
- `adapters/profiles/cisco_ios.yaml` — Cisco als erstes Profil (ersetzt den handgeschriebenen `CiscoIosAdapter`, der **entfernt** wurde)
- `base.py` — `SwitchAdapter`-Protocol auf Instanz-`adapter_id` + Instanz-`capabilities()` umgestellt
- `registry.py` — Profil-Registry: autoload `profiles/*.yaml`, `get_profile`, `build_adapter`, `available_adapters` (aus Profilen); `register_adapter`/`get_adapter_class`/`CiscoIosAdapter` entfallen
- Dependency `pyyaml` + dev `types-PyYAML`
- Tests: Cisco-Assertions **unverändert** gegen den deklarativen Adapter (Äquivalenz-Beweis); neu `test_converters`, `test_parsers`, **`test_conformance`** (parametrisiert über alle Profile × Capabilities, lädt `fixtures/<adapter_id>/<befehl>.txt`, prüft gültige DTOs) — das Qualitätsgate für jedes künftige (auch KI-)Profil
- **Offen/Deployment-Notiz:** sicherstellen, dass `profiles/*.yaml` + `cli_templates/` beim Docker-Build mit ins Package kommen (im Dev/editable-Lauf funktioniert es bereits)

### Session 8 — Multi-Source-Framework + 4 CLI-Profile aus echtem Fleet (Phase A1)
- **U3 Multi-Source-Capabilities**: `CapabilitySpec.sources: list[{command,parser}]` (Kurzform `command/parser` bleibt gültig → cisco_ios.yaml unverändert). single-arity (system_info) merged mehrere Befehle; list-arity einquellig (Laufzeit-Guard). Parser jetzt pro Quelle. Plus `leading_int`-Converter, `provenance`-Feld am Profil, `SystemInfo.hostname` Default `""`.
- **4 neue Vendor-Profile** (custom TextFSM in `cli_templates/`, Fixtures in `tests/adapters/fixtures/<id>/`):
  - `dell_os10` (S5248F-ON): sysinfo aus `show version` + `show license status`
  - `dell_os6` (N2248PX-ON): sysinfo aus `show version` (einquellig)
  - `fs_ruijie` (N8560-48BC, `Gi 0/x`)
  - `fs_centec` (S5800, `eth-0-x`)
- **System-Info aller vier gegen ECHTE Captures validiert** (Sammelmodus); interfaces/lldp/mac doku-/research-abgeleitet (`provenance: … unvalidated`), werden per Live-Probe (Phase A2) bestätigt.
- Tests: `test_vendor_profiles` (gezielte Feld-Assertions je Vendor), `test_profile` (Kurzform↔sources, list-arity-Guard), `test_conformance` deckt jetzt 5 Profile × Capabilities. **62 Tests grün.**
- Adapter-Registry meldet jetzt 5 `adapter_id`s: cisco_ios, dell_os10, dell_os6, fs_centec, fs_ruijie.

### Session 9 — Live-Read-only Foundation + Validierungs-Tool (Phase A2)
- **U1/U2 Live-Transport**: `connection.py` mappt Dell/FS → `"generic"`; `ScrapliTransport` baut für unbekannte Plattformen `AsyncGenericDriver` (read-only `show`, keine Privilege-Logik), sonst Core-Treiber. `adapters/factory.py` `connect(device, credential)` (entkoppelt vom Transport).
- **Validierungs-Kern** `services/validation.py`: `validate_adapter(adapter)` fährt jede Capability, Status `ok`/`empty`/`error` + Zeilenzahl + **Feld-Abdeckung** + Meldung; bricht nicht ab. `validate_device(device, credential)` = Live-Pfad über `RecordingTransport` (liefert Report + rohen Output als Referenz-Capture).
- **`ValidationCheck`-Modell** + Migration `843563cc7225` (device_id, adapter_id, capability, command, status, row_count, detail JSONB, raw_excerpt, checked_at; unique (device_id, capability)).
- **Endpoints (das Tool, ohne Code):** `POST /credentials` + `GET /credentials`; `POST /devices`, `POST /devices/import` (Bulk für 30+); **`POST /devices/{id}/validate`** (read-only live, persistiert Status); `GET /devices/{id}/validation`; **`GET /adapters`** (Capability-Katalog + `provenance` + Validierungs-Status je Profil/Capability). Validierung als injizierbare Dependency (`get_device_validator`) → Tests ohne echtes Gerät.
- **Tests:** `services/test_validation` (ok/empty/error), `test_generic_transport` (Treiber-Wahl + Dell/FS→generic), `api/test_validation_api` (Eintrag, Validate persistiert, /adapters-Status, Bulk-Import). **72 Tests grün.**
- **Folge-Phase A3 (vorgemerkt):** assistiertes Onboarding — neuer Switch → Geräte-Hilfe (`show ?`) → Kandidaten-Befehle → live probieren + validieren → Profil-Vorschlag (Brücke zu Phase-5 KI-Generierung). Validierungs-Kern dafür schon parametrierbar gehalten.

### Session 10 — Discovery/Persistenz (Phase C) + GUI-Anforderung
- `services/discovery.py` `run_discovery(session, device, adapter)`: liest read-only via Adapter, schreibt Inventar → `Device` (model/os_version/serial/last_seen), upsert `Interface` per `(device_id, name)`, ersetzt `LldpNeighbor`/`MacAddressEntry` pro Lauf (volatil), create-if-missing Interface für lldp/mac-Referenzen; `DiscoveryRun` mit Status success/partial/failed + Fehlerliste.
- Endpoints: **`POST /devices/{id}/discover`** (read-only live → persistiert; injizierbarer Live-Adapter via `get_live_adapter`), `GET /devices/{id}/interfaces` / `/lldp-neighbors` / `/mac-table`.
- Tests: `services/test_discovery` (persistiert, idempotent/ersetzt, partial bei Fehler), `api/test_discovery_api`. **77 Tests grün.**
- **Bekannt:** Interface-Namens-Mismatch zwischen Befehlen (z.B. OS10 `Eth 1/1/1` vs `ethernet1/1/1`) → Discovery legt Zusatz-Interfaces an; Normalisierung später (siehe `docs/roadmap.md`).
- **Neue Anforderung (Alex):** grafisches, zoombares **Topologie-GUI** (Standorte→Switches→Firewalls, Layer ein/ausblendbar) → als **Phase G** aufgenommen (Topologie-API + Cytoscape.js-Frontend).

### Session 11 — API-Adapter-Klasse + UniFi (Phase B)
- **Unterbau:** `Credential` um API-Felder (`base_url`, `api_token` verschlüsselt, `extra` JSONB) + `CredentialProtocol.API`; neues `Site`-Modell + `Device.site_id`; Migration `2523e7a92c2a` (Enum-Wert via `autocommit_block`).
- **Zweite Adapter-Klasse:** `adapters/api_client.py` (`ApiClient`-Protocol + `HttpxApiClient`, async CM); `adapters/unifi.py` `UnifiAdapter` (Controller-JSON `stat/device`, Match über mgmt_ip → system/interfaces/lldp/mac), `provenance: unvalidiert`. Registry trägt jetzt **Profil-** *und* **API-Adapter**: `register_api_adapter`, `adapter_kind`, `get_api_adapter_class`, `provenance_for`, `available_adapters` merged. `connect()` branched CLI/API (Transport vs HTTP-Client) — Validate/Discover-Endpoints funktionieren dadurch für beide Klassen transparent.
- Dep `httpx` (jetzt Haupt-Dependency). `POST /credentials` nimmt auch API-Felder; `GET /adapters` zeigt unifi.
- Tests: `test_unifi` (Mapping gegen Fake-Client, not-found, Registry); Conformance filtert auf Profil-Adapter. **82 Tests grün.**
- Offene Folgepunkte (siehe `docs/roadmap.md`): UniFi-Bulk-Discovery, Site-Verdrahtung (mit GUI), UniFi-Auth-Variante.

### Session 12 — Assistiertes Onboarding (Phase A3)
- `services/onboarding.py`: `suggest_profile(transport)` fragt `show ?` ab, parst die Hilfe (`parse_show_help`), wählt je Capability per Schlüsselwörter den besten Kandidaten-Befehl (`pick_candidates`), führt sie read-only aus und liefert einen `ProfileDraft` (Befehl + Roh-Output je Capability). Das ist die „Befehle finden"-Hälfte; Parser-Ableitung daraus = Phase 5.
- `ScrapliTransport` Read-only-Guard erweitert: Hilfe-Befehle (`show ?`, `?`, `help`, `list`, alles endend auf `?`) erlaubt.
- `connection.onboarding_params` (erzwingt `generic`-Plattform, funktioniert für unbekannte Geräte). `POST /devices/{id}/suggest-profile` (injizierbarer Onboarding-Transport für Tests).
- Tests: `services/test_onboarding` (parse/pick/suggest/missing/guard) + `api/test_onboarding_api`. **87 Tests grün.**

### Session 13 — weitere Vendor (Phase D)
- **`aruba_cx`** CLI-Profil (ArubaOS-CX): TextFSM + Fixtures, system-info **multi-source** (`show version` + `show system`), interfaces/lldp/mac. Doku-abgeleitet, unvalidiert.
- **`meraki`** API-Adapter (Cisco Meraki Dashboard, cloud): org-scoped, Match über `lanIp`; system/interfaces/lldp; **kein** READ_MAC_TABLE (keine API). `connect()` setzt Auth-Header aus `credential.extra` (`auth_header`).
- API-Adapter-Konstruktion vereinheitlicht: `(client, *, match_ip, options=credential.extra)` (UniFi: `site`, Meraki: `org_id`).
- Tests: `test_meraki`, aruba via Conformance + Lookup-Fix (YAML `yes/no` → quoten). **97 Tests grün.** 8 Adapter gesamt.

### Session 14/15 — Fortigate (Phase E) + Topologie-API & Frontend-Gerüst (Phase G)
- **`fortigate`** API-Adapter (FortiOS REST, read-only): `system_info` (DeviceType.FIREWALL) + interfaces; LLDP/MAC `CapabilityNotSupported`. 9 Adapter gesamt.
- **Topologie-API (G, Backend):** `POST /sites` + `GET /sites`; `Device.site_id` im Create/Import; **`GET /topology`** → Knoten (Sites + Devices, `type` als Layer) + Kanten (`member` Gerät→Standort, `lldp` Gerät↔Gerät via `remote_system_name==hostname`). Tests: `test_topology_api`, `test_fortigate`. **103 Tests grün.**
- **Frontend-Gerüst (`frontend/`):** React + Vite + TS + **Cytoscape.js** — zoom/pan-barer Topologie-Graph, Layer-Toggles (Geräte-Typen + member/lldp), Adapter-Status-Panel, Vite-Proxy ans Backend. ⚠️ **Unverifiziert** (kein Browser/npm in der Build-Umgebung) — Alex: `cd frontend && npm install && npm run dev`.
- **Hinweis:** laufender Backend-Server (vor S15 gestartet) kennt `/topology`/`/sites` noch nicht → neu starten.

### Session 16 — GUI-App-Ausbau (G2) + Geräte-/Credential-CRUD + LLDP-Vorschläge
- **Backend:** `DELETE /devices/{id}` + `DELETE /credentials/{id}` (Soft-Delete); `site_id` in `DeviceRead`; **`GET /discovery/suggestions`** (LLDP-Nachbarn, die noch nicht im Inventar sind → Add-Vorschläge). 106 Tests grün.
- **Frontend zur App ausgebaut:** Navigations-**Menü** (Topologie / Geräte / Credentials / [Benutzer—Phase H]); **Dark Mode als Default + Toggle** (CSS-Variablen, in localStorage). Views: **Geräte** (Liste + Hinzufügen-Formular + Entfernen + LLDP-Vorschläge „ins Formular"), **Credentials** (SSH/API anlegen + entfernen), **Topologie** (Graph + Layer + Adapter-Status). `npm run build` (tsc + vite) sauber.
- Server laufen: Backend `0.0.0.0:8000`, Vite-GUI `0.0.0.0:5173` (HMR).

### Session 17 — Login + Userverwaltung + RBAC (Phase H)
- **Modelle:** `app_user` (username unique-active, bcrypt-`password_hash`, Rolle `admin/operator/viewer`, enabled) + `auth_session` (opaker Token als SHA-256-Hash, 12h TTL). Migration `16614eab791f`.
- **Auth:** `POST /auth/setup` (erster Admin, nur solange keine User existieren), `/auth/login` (Token als httpOnly-Cookie `nb_session` **und** Bearer für API/Swagger; Header gewinnt vor Cookie), `/auth/logout`, `/auth/me`, `/auth/setup-status`.
- **RBAC:** globale Dependency `authorize` (app-weite Policy): GET = viewer+, Mutationen/„suchen" (validate/discover/suggest, CRUD) = operator+, `/users` = admin; `/auth/*` nur eingeloggt; public: health/docs/login/setup. `/users` CRUD (admin).
- **GUI:** Login-/Erst-Einrichtungs-Screen, Benutzer-View (anlegen mit Rolle, löschen, Selbstschutz), Nav zeigt User+Rolle, Abmelden-Button; 👤-Menüpunkt nur für Admins. Vite-Proxy um `/auth`, `/users`, **`/device-credentials`, `/discovery`** ergänzt (die letzten zwei fehlten — Suggestions/Credential-Badges luden im Dev still nicht).
- Tests: `test_auth_api` (Setup-Flow, Rollen-Enforcement viewer/operator/admin, Logout-Revoke) + bestehende Tests via `authorize`-Override unverändert; neue `auth_client`-Fixture. **109 Tests grün.**

### Session 18 — Autodiscovery-Crawl (rekursiv über LLDP)
- **Enabler:** LLDP-**Management-Adresse** erfasst — `LldpNeighborData.mgmt_address`, Spalte `lldp_neighbor.remote_mgmt_address` (Migration `720e220bdf56`); cisco_ios (ntc-Feld) + dell_os10 (Template+Fixture) mappen sie; Discovery persistiert sie.
- **`services/crawl.py`** `crawl(...)`: BFS ab Seed-Geräten, tiefenbegrenzt, read-only. Pro Gerät discover → LLDP-Nachbarn mit Management-IP, die noch nicht im Inventar sind, automatisch als Device anlegen (Adapter via `guess_adapter()` aus system_description, sonst `default_adapter_id`), mit der Discovery-Credential verknüpfen und weiter crawlen. `CrawlReport` (discovered/added/errors). Injizierbarer Adapter-Provider → testbar ohne Hardware.
- **`POST /discovery/crawl`** (operator+): seed_device_ids + credential_id + max_depth + default_adapter_id. **GUI:** „Autodiscovery-Crawl"-Karte in der Geräte-View (Seed + Credential + Tiefe → Report).
- Tests: `test_crawl` (guess_adapter, BFS legt an + crawlt rekursiv, Tiefenlimit). **112 Tests grün.**

### Session 19 — Geplante Discovery (ARQ-Worker)
- `services/discovery.run_scheduled_discovery(session, provider)`: discovert alle aktiven Geräte mit verknüpfter SSH-Credential, sammelt ok/Fehler. Read-only, injizierbarer Provider → testbar.
- `workers/discovery_worker.py`: ARQ-`WorkerSettings` mit Cron-Job `scheduled_discovery` (alle `scheduled_discovery_minutes` Min, 0 = aus), `redis_settings` aus `redis_url`, eigener Live-Adapter über `connect()`, committet pro Lauf. Start: `uv run arq netbuddy.workers.discovery_worker.WorkerSettings`.
- `core/config.py`: `redis_url` (Default `redis://localhost:6379`) + `scheduled_discovery_minutes` (Default 30). Dep `arq`.
- Tests: `test_scheduled_discovery` (nur Geräte mit SSH-Credential werden discovert, System-Info persistiert). **113 Tests grün.**

### Session 20 — Interface-Namen-Normalisierung
- `services/ifname.normalize_interface_name`: vendor-tolerante Kanonisierung (Präfix-Map + Leerzeichen raus), sodass LLDP/MAC denselben Port treffen wie die Interface-Liste (OS10 „Eth 1/1/1" == „ethernet1/1/1", Cisco „GigabitEthernet1/0/1" == „Gi1/0/1"). Discovery cached + matched jetzt über den normalisierten Schlüssel → keine doppelten „virtuellen" Interfaces mehr.
- Tests: `test_ifname`. **117 Tests grün.** (Behebt die in `docs/roadmap.md` notierte Schwäche.)

### Session 21 — Config-Backup + Diff + Audit-Log (Fundament für F)
- **READ_CONFIG**-Capability + `SwitchAdapter.get_config()`; `DeclarativeAdapter` liefert die laufende Konfig über `backup_command` im Profil (cisco/dell/fs/aruba gesetzt), API-Adapter werfen `CapabilityNotSupportedError`.
- `services/backup.py`: `backup_device` (read-only Konfig holen, per SHA-256 dedupliziert speichern), `diff_latest` (Unified-Diff der zwei jüngsten Sicherungen). Modell `ConfigBackup` (+ Migration `9866fd865f56`).
- Endpoints: `POST /devices/{id}/backup`, `GET /devices/{id}/backups`, `GET /devices/{id}/backups/{id}`, `GET /devices/{id}/config-diff`.
- **Audit-Log:** Modell `AuditLog` + `services/audit.audit()`-Helfer; geloggt bei device.create/delete/backup. `GET /audit` (nur **admin**, RBAC-Policy um `/audit` erweitert).
- Tests: `test_backup_api` (Dedupe, Diff, 400 ohne Credential). **119 Tests grün.**

### Session 22 — Endgerät-Suche / Lokalisierung (welches Gerät an welchem Port)
- `services/locate.locate(q)`: sucht per **MAC / Name / IP** (Teilstring, case-insensitiv) über MAC-Address-Table + LLDP-Nachbarn → liefert **Switch + Port**, wo das Gerät hängt (MACADDR via Cast). `GET /search?q=` (viewer+).
- **GUI:** Suchfeld in der Topologie. Treffer werden **nur bei Suche** als ephemere Endgerät-Knoten (Rauten, amber) am jeweiligen Switch eingeblendet (Kante = Port), inkl. Zoom/Fit; „ausblenden ✕" entfernt sie wieder. Endgeräte sind sonst **nicht** im Graph (Topologie = Sites/Switches/FW + LLDP). Layer-Sichtbarkeit lässt ephemere Knoten unberührt.
- Tests: `test_search_api` (MAC/Name/IP, leere Query → 422). **123 Tests grün.**

### Session 23 — Namensauflösung von Endgeräten (MAC→IP→Name)
- Ziel (Alex): Endgeräte nicht nur per MAC, sondern **per Name** finden und wissen, an welchem Switch-Port sie hängen — und das nur bei Suche, sonst nicht im Graph.
- Neue Capability `read_arp` + DTO `ArpData`; auf dem `SwitchAdapter`-Protocol, im `DeclarativeAdapter` (`get_arp` via `_list_rows`) und als `CapabilityNotSupportedError` auf den API-Adaptern (unifi/meraki/fortigate).
- Profile: `read_arp` für **cisco_ios** (ntc `show ip arp`) und **dell_os10** (eigenes TextFSM `dell_os10_show_ip_arp.textfsm`) + Fixtures; Conformance-Gate deckt beide ab.
- Modelle `ArpEntry` (IP↔MAC je Gerät, pro Lauf ersetzt) + `Host` (korreliert MAC↔IP↔Name, Upsert per kanonischer MAC). Migration `3db5f7c39230`.
- `services/discovery.py`: persistiert ARP read-only, MAC kanonisch (`normalize_mac`, 12 Hex lowercase). `services/hosts.py`: `normalize_mac`, `reverse_dns` (PTR im Thread, injizierbar), `correlate_hosts` (ARP→IP→DNS, idempotent).
- `services/locate.py`: zusätzlicher Treffer-Typ **`host`** — Suche nach Name/IP/MAC → über die kanonische MAC auf MAC-Table-Port; liefert IP + Name. `POST /discovery/resolve-hosts` (operator+) löst die gesammelten ARP-Daten zu Hosts auf (DNS-Resolver injizierbar via `HostResolverDep`).
- **GUI:** Button „Namen auflösen" in der Topologie-Suche (zeigt `aufgelöst/gesamt`); Treffer zeigen Name + IP, ephemere Knoten labeln mit dem aufgelösten Namen.
- Tests: `test_hosts` (normalize_mac, correlate_hosts, locate-by-name/-ip, ARP-Replace), `test_resolve_hosts_api` (Resolver-Override → Suche per Name). **136 Tests grün.**

### Session 24 — GUI: Geräte-Detail + Live-Aktionen + Switch-Faceplate + Icons
- Hintergrund (Alex): vor dem ersten echten Core-Switch-Test sollen die read-only Live-Funktionen **im GUI** klickbar sein (bisher nur API), plus optische Switch-/Port-Darstellung.
- Backend: neuer `GET /devices/{id}/arp` (ArpEntryRead) — die übrigen Read-/Aktions-Routen existierten schon. Test in `test_discovery_api` erweitert (ARP, MAC kanonisch). 136 Tests grün.
- Frontend `api.ts`: `discoverDevice`/`validateDevice`/`backupDevice` + Lesesichten `fetchInterfaces/MacTable/LldpNeighbors/Arp` + Typen.
- **`DeviceDetail.tsx`** (in der Geräte-Liste aufklappbar): Buttons **⟳ Discover / ✓ Validieren / 💾 Backup** (alle read-only, erster echter Geräte-Zugriff via GUI) + Tabs Ports/MAC/LLDP/ARP/Validierung. **Switch-Faceplate**: physische Ports als Kästchen, grün=up / blass=down / amber=admin-down, blauer Punkt+Oberkante=LLDP-Nachbar, Tooltip (Name/Desc/Speed/Nachbar/MAC-Count), Legende; Validierungs-Tab zeigt Status (ok/empty/error) + Feld-Abdeckung.
- **Icons:** `icons.tsx` (Inline-SVG je Gerätetyp, Liste + Detail-Kopf) und `nodeIcons.ts` (weiße Data-URI-SVGs als Cytoscape-Knoten-Hintergrund) → echte Icons im Topologie-Graph, Switches als Chassis-Rechteck.
- `tsc` + `vite build` sauber. Backend neu gestartet (Port 8000), Vite (5173).

### Session 25 — ERSTER ECHTER GERÄTE-ZUGRIFF: dell_os10 live-validiert + Standort-Verwaltung
- **Meilenstein:** Core-Switch (BLS-SW-Core2 / Dell S5248F-ON / OS10 10.5.2.6) read-only live ausgelesen. Zwei Blocker gefixt, die jeden Live-Zugriff verhindert hätten:
  1. `params_from_credential` gab `device.mgmt_ip` (ein `IPv4Address` aus der `INET`-Spalte) an `ConnectionParams.host: str` → pydantic-`ValidationError` vor jedem I/O. Fix: `str(device.mgmt_ip)`.
  2. Der `AsyncGenericDriver` (Dell/FS) kennt Dells Prompt/Pager nicht → lange Ausgaben hingen am `--More--` (`ScrapliTimeout`). Fix: `terminal length 0` beim Öffnen (nur generic-Plattformen, reine Session-Einstellung, read-only-safe).
- **Ergebnis:** `dell_os10` jetzt **live-validiert** (vorher unvalidated): system_info, interfaces (56), lldp (31), mac (338), arp (97) — alle Felder geparst. Provenance aktualisiert. Regressionstests für beide Fixes. Commit `2c160db`.
- **Standort-Verwaltung (Alex' Wunsch):** es gab `GET/POST /sites`, aber kein GUI und kein Delete. Neu: `DELETE /sites/{id}` (Soft-Delete, 409 wenn noch Geräte dranhängen), **`SitesView`** (anlegen/auflisten/löschen + Geräte-Zähler) + Nav-Eintrag „📍 Standorte". Tests `test_sites_api`. 140 Tests grün.
### Session 26 — 1-Klick-Anlage, Profil-Raten, ARP-IP, Inline-Edit + fs_centec live-validiert
- **Geräte bearbeiten:** `PATCH /devices/{id}` (Teil-Update, `site_id: null` leert; `refresh` gegen Lazy-IO bei `updated_at`). GUI: Standort + Adapter als **Inline-Dropdowns** in der Liste, Name/IP per ✎-Edit — kein Löschen+Neuanlegen mehr.
- **1-Klick-Anlage aus LLDP-Vorschlag:** „+ Hinzufügen" statt des wirkungslosen „ins Formular" (das nur das weggescrollte Formular oben füllte). Profil wird **geraten** (`guess_adapter` aus system_description → `guessed_adapter` im Vorschlag), Mgmt-IP kommt aus **ARP** (LLDP-`chassis_id` = MAC → `ArpEntry`), Prompt nur als Fallback.
- **fs_centec live-validiert** gegen echte FS S5800-48MBQ (bls-sw-53 / FSOS 7.0.4.5, 10.120.10.53): system_info, interfaces (54), mac (206). LLDP leer, weil das Gerät real **0 Nachbarn** meldet („has 0 neighbor(s)") — deshalb taucht es nicht in der Autodiscovery auf (LLDP auf dem Uplink/Gegenstelle aus); per IP manuell anlegen. Provenance aktualisiert.
- Tests: `test_patch_device_updates_fields`, `guessed_adapter` im Suggestions-Test. 141 Tests grün.
- **Noch offen:** Crawl-Report zeigt nur Fehler-Anzahl, nicht die Meldungen.

### Session 27 — ERSTER SCHREIBPFAD (eng begrenzt): LLDP aktivieren + LLDP-Liste angereichert
- **Hintergrund:** FS-Switches haben LLDP per Default aus → Autodiscovery findet sie nicht. Alex hat **Schreibzugriff für genau diesen Fall** freigegeben. Entscheidungen: **global + alle Ports**, **Backup→schreiben→verifizieren** + Audit.
- **Profil-gesteuerter Write:** `LldpControlSpec` im Profil (`status_command`, `enabled_marker`-Regex, `enable_global`, `enable_interface`, `interface_enter/exit`). Für `fs_centec` gesetzt (`lldp enable` global + je `eth-0-x`). Andere Profile: kein `lldp_control` → 400 „nicht unterstützt".
- **Getrennter Schreibpfad:** `ScrapliTransport.send_config()` (umrahmt mit `configure terminal`…`end`) — **nicht** read-only-guarded, nur über den autorisierten LLDP-Endpoint. `services/lldp_control.py`: `read_lldp_enabled` + `enable_lldp` (Backup zuerst, dann global+physische Ports, dann Status erneut lesen). `is_physical` filtert vlan/po/loopback/mgmt raus.
- **Endpoints:** `POST /devices/{id}/lldp/status` (read-only live) + `POST /devices/{id}/lldp/enable` (write, operator+, Audit `device.lldp_enable`). Neue Dep `LiveConnectionDep` (Adapter **und** Transport).
- **LLDP-Liste angereichert:** `GET /devices/{id}/lldp-neighbors` liefert jetzt zusätzlich `resolved_ip` (Host/ARP/LLDP-Mgmt über chassis_id-MAC) + `resolved_name` (DNS via Host). GUI-Tab zeigt Hostname + IP-Spalten.
- **GUI:** LLDP-Statusleiste im Geräte-Detail — „LLDP-Status prüfen" → wenn AUS: Banner „LLDP ist AUS" + Button „LLDP aktivieren (Schreibzugriff)" mit Bestätigung.
- Tests: `test_lldp_control` (Service: aus→aktivieren→an, Backup, nur physische Ports), `test_lldp_api` (Status+Enable gemockt, Cred-Pflicht). **146 Tests grün.** Noch NICHT live ausgeführt — der echte Write auf bls-sw-53 wartet auf Alex' Trigger.

### Session 28 — MAC-OUI → Hersteller-Vermutung (IEEE-Registry gebündelt)
- Wunsch (Alex): aus den MACs in der LLDP-Liste auf den Hersteller schließen (FS.com etc.), generell auch für andere Switche/Firewalls.
- **Daten:** IEEE/Wireshark-`manuf` geladen → kompakte `adapters/data/oui.csv` (39 279 /24-OUIs, ~1,2 MB, `prefix,vendor`). `services/oui.vendor_for_mac(mac)` (lru-gecacht; nutzt `normalize_mac`, gibt None bei Nicht-MAC wie LLDP-Name-Chassis).
- **Live bestätigt:** FS S5800 hat OUI `64:9d:99` = „Fs Com Inc". Fleet-OUIs aufgelöst: `b0:4f:13`/`8c:47:be`=Dell (BLS-SW-*/SW1), `1c:6a:1b`=Ubiquiti (BLS-SW-68), `d4:76:a0`=Fortinet (BLS-FW1/2), `90:09:d0`=Synology, `b4:96:91`=Intel, `b8:e9:24`=Mellanox, `e4:3d:1a`=Broadcom, `00:0e:1e`=QLogic (Server-NICs).
- **Verdrahtet:** `guessed_vendor` in `GET /devices/{id}/lldp-neighbors` (Spalte „Hersteller (MAC)") und in den LLDP-Vorschlägen (greift auch bei „Not Advertised", wo das Profil-Raten nichts hat). Tests `test_oui`. 153 Tests grün.
- **Deployment-Notiz:** `adapters/data/oui.csv` muss (wie `profiles/`+`cli_templates/`) ins gebaute Package.

### Session 30 — Gap-Analyse + Discovery flächendeckend (S30) + Discovery-Härtung (S31)
- **Workflow-Gap-Analyse** (10 Agenten) → `docs/gap-analysis.md` = **authoritative Roadmap S30–S38** Richtung Ziel (site-übergreifende VLANs + vollständige Erkennung). Entscheidung Alex: **erst Discovery komplett, dann ans Ändern.** Packaging-Blocker B7 nachgeprüft → Fehlalarm (uv_build packt src-Daten automatisch; im Doc korrigiert).
- **S30 — read_arp + LLDP-Mgmt-IP in allen 6 CLI-Profilen:** fs_centec-LLDP-Template **gegen echtes Gerät neu geschrieben** (das doku-abgeleitete parste 0 Zeilen!) — parst jetzt 8 echte Nachbarn inkl. Core (SW2) mit Management-Adresse; `read_arp` (Header live bestätigt). dell_os6/fs_ruijie: arp+mgmt doku-abgeleitet. aruba_cx: LLDP auf `neighbor-info detail` (einziges Format mit Mgmt-IP), arp, case-insensitive Lookups. Neuer Konverter `ip_or_none` (verwirft 0.0.0.0 von PCs). Live-Validierung bls-sw-53: healthy, lldp 8 / mac 411 / interfaces 54. Erkenntnis: 192.168.245.11 (Alex' „falsche IP") = LLDP-Mgmt-Adresse des Core (OOB).
- **S31 — Discovery-Härtung:** (a) Worker korreliert Hosts nach jedem Lauf (`scheduled_resolve_hosts`, Default an) → Namensauflösung automatisch; (b) Crawl: `guess_device_type` (fortigate→firewall, „U7/access point"→ap) + OUI-Fallback in `guess_adapter` (Fortinet→fortigate, Ubiquiti→unifi; FS/Dell bewusst nicht — per MAC mehrdeutig); (c) **MAC-Tabellen-Vorschläge** `services/mac_suggest.py` + `GET /discovery/mac-suggestions` + GUI-Karte „Verdacht aus MAC-Tabellen (OUI)" mit 1-Klick-Anlage (IP aus ARP/DNS, Prompt-Fallback) — Infra-Vendor-Filter bewusst OHNE Dell/Intel/Broadcom (Server/Laptops; Dell-Switches kommen per LLDP); (d) Crawl-Report zeigt Fehlerdetails (aufklappbare Tabelle).
- **Live-Ergebnis sofort:** MAC-Vorschläge finden **7 weitere FS-Switches** (LLDP-los, an Core-Ports), die **Fortigate** (10.120.10.1, adapter-Vorschlag), Brocade/TP-Link/Zyxel + UniFi-Flotte. **161 Tests grün.**

### Session 31 — Vereinheitlichte Vorschläge + Fortigate ARP/LLDP + 3 neue Firewall-Adapter
- **Eine Vorschlagsliste** (Alex: „LLDP und ARP/MAC kombinieren — einfacher zum Handhaben"): `services/suggest.py` merged LLDP-Nachbarn + MAC-Tabellen-Verdachte (OUI) über die kanonische Chassis-/Quell-MAC zu EINEM Eintrag (`sources: ["lldp","mac"]`), angereichert mit IP (LLDP-Mgmt > ARP > Host) und DNS-Name. `GET /discovery/suggestions` liefert das neue Schema; `/discovery/mac-suggestions` entfernt; GUI = eine Karte „Vorgeschlagene Geräte" mit Quelle-Badges + 1-Klick-Anlage. `services/mac_suggest.py` darin aufgegangen.
- **SW-66/51-Mgmt-IP-Frage beantwortet:** OS6-Switches advertisen kein LLDP-Mgmt-TLV, ihre MACs fehlen im Core-ARP (Gateway = Fortigate), DNS kennt die Namen nicht → IP ist in keiner Quelle vorhanden, Prompt korrekt. Struktureller Fix = Fortigate-ARP (vorgezogen, s.u.).
- **Fortigate erweitert (aus S36 vorgezogen):** `get_arp` (`monitor/network/arp` — Gateway = beste ARP-Quelle des Standorts!) + `get_lldp_neighbors` (`monitor/network/lldp/neighbors`, FortiOS ≥ 7.0). Unvalidiert bis API-Token von Alex (read-only-Profil); Credential: base_url=https://<fw>, api_token, extra.auth_header bleibt X-API-KEY (FortiOS akzeptiert Bearer/Token-Header — beim ersten Zugriff verifizieren).
- **3 neue Firewall-Adapter** (Alex: „alle anderen device profiles bauen"): **paloalto** (PAN-OS XML-API via `X-PAN-KEY`-Header; system_info/interfaces/arp; XML-Parsing mit stdlib-ElementTree), **cato** (GraphQL `accountSnapshot`; system_info je Site; braucht extra.account_id+site_name+auth_header=x-api-key), **watchguard** (ehrliches Skeleton OHNE Capabilities — Fireware verlangt Session-Login (POST), den der tokenbasierte HttpxApiClient nicht kann; GUI graut via Capability-Detection alles aus; Login-Flow folgt, wenn die Italien-Box drankommt). `ApiClient`-Protokolle erweitert: `TextApiClient` (get_text/XML), `GraphqlApiClient` (post_json) — strukturell von `HttpxApiClient` erfüllt, bestehende Fakes unberührt.
- **12 Adapter registriert** (6 CLI-Profile + 6 API). **175 Tests grün.**

### Session 32 — Standorte mit IP-Segmenten, VPN-Topologie, Sites als Container, Discovery-Hauptkategorie
- **Alex' Umbau-Wünsche umgesetzt:** (1) Standorte = **Container/Wolke** in der Topologie (Cytoscape compound, gestrichelt, Geräte liegen darin — keine „member"-Kanten mehr); (2) **Standorte verwalten IP-Segmente** (mehrere pro Site, `SiteSubnet`-Modell, CRUD `POST/DELETE /sites/{id}/subnets`, GUI in SitesView) — Geräte werden beim Anlegen + im Crawl **automatisch per Segment** dem Standort zugeordnet (`services/sites_net.site_for_ip`, längster Präfix); (3) **VPN-Tunnel** von der Firewall gelesen (`READ_VPN_TUNNELS`, FortiOS `monitor/vpn/ipsec`, `VpnTunnel`-Modell, Discovery-**Upsert** statt Ersetzen); Site↔Site-Kanten via Selektor-Überlappung mit den Site-Segmenten (`subnet_overlaps_site`); (4) **„berücksichtigen"-Schalter pro Tunnel** (`relevant`-Flag, überlebt Discovery; Partner-/Lieferanten-Tunnel raus aus der Topologie; GUI: VPN-Tab im Geräte-Detail mit Checkbox); (5) **Discovery = eigene Hauptkategorie** im Menü (Vorschläge + Crawl + Namen auflösen raus aus „Geräte").
- **Namens→IP-Regel pro Standort** (S31e, jetzt mit GUI in SitesView): `mgmt_ip_template` „10.120.10.{n}" → Vorschläge ohne echte IP-Quelle bekommen eine als ≈ markierte Schätzung aus der Endnummer des Namens.
- **Live verifiziert:** Segmente angelegt (Sulgen 10.120/16, Grosuplje 10.121/16, USA 10.122/16, Cusano 10.123/16); FW1-Discovery liest **10 echte IPsec-Tunnel**; Topologie zeigt **Sulgen↔USA (BLS-US), Sulgen↔Cusano, Sulgen↔Grosuplje (BLS-SLO)** — Partner-Tunnel (ProcessPartner/Orbis/TibaTec/All4One/TS01) erzeugen korrekt keine Site-Kanten. Fortigate-Provenance → live-validated. FortiOS-Notiz: Selektoren kommen als `10.122.0.0/255.255.0.0` (Netmask-Form — `ipaddress` parst das) bzw. als Range `a-b` (wird übersprungen).
- **Bugfix dabei:** Seed-/CLI-Skripte ohne `deleted_at`-Filter erwischten ein soft-gelöschtes FW-Duplikat (BLS-FW-CU) — Tunnel umgehängt; Lehre: `.first()` auf Device-Queries immer mit `deleted_at.is_(None)`.
- Migrationen `d8cfa495b306` (site_subnet+vpn_tunnel) + `878bb2414311` (relevant). **188 Tests grün.**

### Session 33+34 — Telnet, API-Validate, Interface-Baum, Topologie-Stabilität (Alex' Funde im Akkord)
- **Telnet (read-only):** Protokoll folgt dem **Port** (22=SSH, 23=Telnet automatisch; abweichender Port → Protokoll-Auswahl im Formular; `extra.transport` als Override). Writes bleiben SSH-only (send_config lehnt Telnet ab). OS6-Fleet ist Telnet-only (Port 23 offen, 22 refused).
- **Kind-Badges:** Credentials + Geräte-Verknüpfungen zeigen den echten Typ (ssh/telnet/api) — API-Credential erschien vorher als „(ssh)". `link_credential` leitet Protokoll aus der Credential ab; validate/discover wählen die zur Adapter-Art passende Credential (`_device_credential`).
- **Validate für API-Adapter** (Forti-400 gefixt): Branch über `adapter_kind`, Checks mit „API: <capability>"-Label.
- **FortiGate Interface-BAUM:** `Interface.parent_name`+`vlan_id` (Migration `8c7971315c66`), fortigate merged `cmdb/system/interface` (type/interface/vlanid) in die Monitor-Liste; GUI rendert Baum (VLAN unter physischem Port) statt Faceplate, wenn Eltern existieren.
- **Topologie:** stabiles Layout (Positions-Persistenz in localStorage + deterministisches Seeding — F5 würfelt nicht mehr; gezogene Positionen bleiben), **VPN-Kanten gehen von der Firewall aus** zum Remote-Standort, Auto-Fit nach Layout (dynamischer Zoom je Gerätemenge) + Doppelklick=Einpassen. **Icons endgültig gefixt**: SVGs mit expliziten Maßen + Innen-Padding, `background-fit: contain` (kein Beschnitt mehr); leere Standorte = Pin; Nav-Emoji „Geräte" ausgerichtet.
- VPN-Toggle: GUI optimistisch + Fehleranzeige (Backend war korrekt, Fehler wurden verschluckt). **192 Tests grün.**

### Pragmatische Entscheidungen (Detail siehe Session-3-Status)
- StrEnum + `values_callable=enum_values` → lowercase Enum-Werte in PG, passend zu den server_defaults
- Explizite `DROP TYPE`-Schleife im `downgrade()` (Alembic vergisst Enums)
- `render_item`-Callback in `env.py` → künftige Migrationen importieren `EncryptedString` automatisch
- `pydantic.mypy`-Plugin → `Settings()` typcheckt trotz env-geladenem `fernet_key`
- Composite PK `(device_id, credential_id, protocol)` auf `DeviceCredential` (kein Surrogat-ID)
- DB-Tests benutzen echte Postgres-Instanz, separate `netbuddy_test`-DB wird automatisch angelegt

## Kritische offene Punkte

**✅ Git-Commits erledigt.** 4 thematisch geschnittene Commits (Scaffolding / FastAPI-Skelett / Docker-Stack / DB-Schema), auf `origin` (`github.com/swissgiant/Netbuddy`, HTTPS via `gh`) gepusht. `main` trackt `origin/main`. Commit-Mail: GitHub-noreply (`6225583+swissgiant@users.noreply.github.com`, lokal im Repo gesetzt). Keine offenen Blocker.

## Reales Fleet (Sammelmodus, Anfang Juni 2026)

Statt aus Doku zu raten, hat Alex das echte Fleet per `show version` / UniFi-Controller gezeigt. Details + Captures-Fakten siehe Memory `project_vendor_fleet.md`. Zusammenfassung der nötigen Integrationen:

| Vendor | Modell(e) | Zugriff | Integration |
|---|---|---|---|
| Dell | S5248F-ON | OS10 CLI | `dell_os10` (TextFSM-Profil) |
| Dell | N2248PX-ON (mehrfach) | OS6 CLI | `dell_os6` (TextFSM-Profil) |
| FS.com | S5800/48MBQ | FSOS **Centec** (`eth-0-x`) | `fs_centec` (TextFSM-Profil) |
| FS.com | N8560-48BC | FSOS **Ruijie** (`Gi 0/x`) | `fs_ruijie` (TextFSM-Profil) |
| Ubiquiti | USW/ECS + APs, 3 Sites | UniFi-Controller | **`unifi` API-Adapter** (kein Profil), multi-site |
| **gewünscht:** Cisco | Catalyst/IOS | CLI | `cisco_ios` (Profil **existiert** seit S5/7) |
| **gewünscht:** HP Aruba | ArubaOS-CX / ProCurve | CLI (Central = API) | Profil(e), Modelle tbd |
| **gewünscht:** Cisco Meraki | — | cloud | **API-Adapter** (Dashboard-API) |

**Zwei Integrations-Klassen:** CLI/TextFSM-Profil (Dell, FS, Cisco, Aruba-CX) **vs** JSON-API-Adapter (UniFi, Meraki, ggf. Aruba Central) — das Framework muss beide tragen.

**Firewalls (Standort-Kopplung, eigener Geräte-Bereich):** fast überall **Fortigate/FortiOS** (REST-API), in Italien eine **WatchGuard**, gewünscht **Palo Alto** (PAN-OS-API) und **Cato** (Cloud-SASE/GraphQL). **Produktziel:** VLANs **standortübergreifend** ausrollen inkl. VPN-Orchestrierung über die Firewalls (spätere Phase). Details siehe Memory `project_vendor_fleet.md`.

## Naheliegende nächste Schritte

1. **Echte Live-Validierung** — Alex trägt die Switches ein (`POST /devices` + Credentials bzw. `POST /devices/import`) und fährt `POST /devices/{id}/validate` gegen die realen Geräte → bestätigt/korrigiert die noch `unvalidated` interfaces/lldp/mac. (Code + Tests stehen, Session 9.)
2. **Phase A3 — assistiertes Onboarding** (Befehls-Discovery via Geräte-Hilfe → Kandidaten → validieren → Profil-Vorschlag).
3. **`unifi` API-Adapter** — zweite Adapter-Klasse (Controller-JSON), multi-site; Credential-Modell um API-Felder + Site/Controller-Entity (U6/U7).
4. **Discovery-Service-Skelett** — mappt Adapter-DTOs auf die ORM-Aggregate, schreibt `DiscoveryRun`; ARQ-Worker.
5. **Weitere Vendor:** Cisco Catalyst (Profil da), HP Aruba (CLI-Profil[e]), Cisco Meraki (API-Adapter).
6. **Firewalls** (Fortigate API zuerst) + Nordstern: site-übergreifende VLANs/VPN.
6. **KI-gestützte Profil-Generierung** (Phase 5) — baut direkt auf dem Profil-Schema + Conformance-Gate auf

## Quick-Reference

```bash
# Dev-Stack
./scripts/dev-up.sh                                    # Postgres + Redis + Adminer
./scripts/dev-down.sh                                  # Stop (Volume bleibt; -v zum Wipen)

# Backend
cd backend
uv run uvicorn netbuddy.api.main:app --reload          # Server
uv run alembic upgrade head                            # Migration anwenden
uv run alembic revision --autogenerate -m "msg"        # Neue Migration
uv run ruff check . && uv run mypy src/ && uv run pytest
```

Endpoints im laufenden Stack:
- Backend: http://127.0.0.1:8000 (`/health`)
- Adminer: http://localhost:8080 (System: PostgreSQL, Server: `postgres`, User: `netbuddy`)
- Postgres: `postgresql+asyncpg://netbuddy:changeme_for_dev_only@localhost:5432/netbuddy`
