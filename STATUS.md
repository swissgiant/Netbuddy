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
| `ruff` / `mypy --strict` / `pytest` | Alle drei grün (10 Tests) |

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

### Pragmatische Entscheidungen (Detail siehe Session-3-Status)
- StrEnum + `values_callable=enum_values` → lowercase Enum-Werte in PG, passend zu den server_defaults
- Explizite `DROP TYPE`-Schleife im `downgrade()` (Alembic vergisst Enums)
- `render_item`-Callback in `env.py` → künftige Migrationen importieren `EncryptedString` automatisch
- `pydantic.mypy`-Plugin → `Settings()` typcheckt trotz env-geladenem `fernet_key`
- Composite PK `(device_id, credential_id, protocol)` auf `DeviceCredential` (kein Surrogat-ID)
- DB-Tests benutzen echte Postgres-Instanz, separate `netbuddy_test`-DB wird automatisch angelegt

## Kritische offene Punkte

**✅ Git-Commits erledigt.** 4 thematisch geschnittene Commits (Scaffolding / FastAPI-Skelett / Docker-Stack / DB-Schema), auf `origin` (`github.com/swissgiant/Netbuddy`, HTTPS via `gh`) gepusht. `main` trackt `origin/main`. Commit-Mail: GitHub-noreply (`6225583+swissgiant@users.noreply.github.com`, lokal im Repo gesetzt). Keine offenen Blocker.

## Naheliegende nächste Schritte (nichts angefangen)

1. **SwitchAdapter-Protocol** + erster Cisco-IOS-Skeleton-Adapter (read-only gegen Mock)
2. **Discovery-Service-Skelett** (LLDP/CDP/SNMP)
3. **ARQ-Worker** für Background-Jobs
4. **Weitere Device-Endpoints** (POST/PATCH/DELETE) — erst wenn über Read-Only hinaus gewünscht
5. **Endpoints für übrige Aggregate** (Interfaces, LLDP-Neighbors, Discovery-Runs)

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
