# NetBuddy — Aktueller Stand

**Stand:** Anfang Juni 2026, Phase 1 — Schema/Migration fertig, alles committed & gepusht.

Projektkontext und Konventionen stehen in `CLAUDE.md`. Diese Datei dokumentiert nur den **aktuellen Fortschritt** und was als Nächstes ansteht.

## Was läuft gerade

| Komponente | Status |
|---|---|
| Docker-Dev-Stack (postgres + redis + adminer) | Seit ~2 Wochen ununterbrochen `healthy`; Endpoints lt. README |
| Alembic-Head | `2523e7a92c2a` (`sites, device.site_id, credential api fields`) |
| DB-Schema | Alle 7 Phase-1-Tabellen + `alembic_version` migriert |
| Backend-Server | Nicht dauerhaft gestartet; `uv run uvicorn netbuddy.api.main:app --reload` läuft fehlerfrei |
| `ruff` / `mypy --strict` / `pytest` | Alle drei grün (97 Tests) |
| CLI-Profile | cisco_ios, dell_os10, dell_os6, fs_ruijie, fs_centec, aruba_cx (sysinfo dell/fs live-validiert, Rest unvalidiert) |
| API-Adapter | unifi, meraki (JSON-Controller-API, unvalidiert) |
| Vendor-Abstraction-Layer | Deklarative YAML-Profile + `DeclarativeAdapter`; Cisco IOS als erstes Profil (read-only, gegen Mock-Transport) |
| Echter Transport | `ScrapliTransport` (async, read-only-Guard) + `ConnectionParams` aus `Credential`; noch kein Live-Zugriff |
| Neuer Vendor | = Profil-YAML + Fixtures + bestandener Conformance-Test, **kein Code** |

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
