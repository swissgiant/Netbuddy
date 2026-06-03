# NetBuddy — Aktueller Stand

**Stand:** Anfang Juni 2026, Phase 1 — Schema/Migration fertig, alles committed & gepusht.

Projektkontext und Konventionen stehen in `CLAUDE.md`. Diese Datei dokumentiert nur den **aktuellen Fortschritt** und was als Nächstes ansteht.

## Was läuft gerade

| Komponente | Status |
|---|---|
| Docker-Dev-Stack (postgres + redis + adminer) | Seit ~2 Wochen ununterbrochen `healthy`; Endpoints lt. README |
| Alembic-Head | `c31556efa8b2` (`phase1 initial schema`) |
| DB-Schema | Alle 7 Phase-1-Tabellen + `alembic_version` migriert |
| Backend-Server | Nicht dauerhaft gestartet; `uv run uvicorn netbuddy.api.main:app --reload` läuft fehlerfrei |
| `ruff` / `mypy --strict` / `pytest` | Alle drei grün (38 Tests) |
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

### Pragmatische Entscheidungen (Detail siehe Session-3-Status)
- StrEnum + `values_callable=enum_values` → lowercase Enum-Werte in PG, passend zu den server_defaults
- Explizite `DROP TYPE`-Schleife im `downgrade()` (Alembic vergisst Enums)
- `render_item`-Callback in `env.py` → künftige Migrationen importieren `EncryptedString` automatisch
- `pydantic.mypy`-Plugin → `Settings()` typcheckt trotz env-geladenem `fernet_key`
- Composite PK `(device_id, credential_id, protocol)` auf `DeviceCredential` (kein Surrogat-ID)
- DB-Tests benutzen echte Postgres-Instanz, separate `netbuddy_test`-DB wird automatisch angelegt

## Kritische offene Punkte

**✅ Git-Commits erledigt.** 4 thematisch geschnittene Commits (Scaffolding / FastAPI-Skelett / Docker-Stack / DB-Schema), auf `origin` (`github.com/swissgiant/Netbuddy`, HTTPS via `gh`) gepusht. `main` trackt `origin/main`. Commit-Mail: GitHub-noreply (`6225583+swissgiant@users.noreply.github.com`, lokal im Repo gesetzt). Keine offenen Blocker.

## Naheliegende nächste Schritte

1. **Weitere Vendor-Profile** — Dell OS10/OS6 und FS.com/FSOS: CLI-Befehls-Sets recherchieren (Quellen), Profil + Beispiel-Output-Fixtures erstellen, ggf. custom TextFSM-Template in `cli_templates/` (FS.com hat keine ntc-Abdeckung). Gate = `test_conformance`. Für FS.com/Dell ohne echte Captures bleiben Profile „unvalidiert bis Live-Capture".
2. **Live-Smoke-Test** des `ScrapliTransport` gegen einen echten Lab-Switch — read-only Service-User + IP via `secrets.yaml` (gitignored). ⚠️ Erster echter Geräte-Zugriff, braucht Alex' explizites OK + Creds.
3. **Discovery-Service-Skelett** — mappt Adapter-DTOs auf die ORM-Aggregate, schreibt `DiscoveryRun`
4. **ARQ-Worker** für Background-Jobs (Discovery async)
5. **`GET /adapters` + Endpoints für übrige Aggregate** (Interfaces, LLDP-Neighbors, Discovery-Runs)
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
