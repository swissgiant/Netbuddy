# NetBuddy

Web-based network administration tool for switches and firewalls.
Multi-vendor support via plugin architecture.

Status: early development (Phase 1)

See `CLAUDE.md` for project context.

## Development Setup

### Prerequisites

- Docker + Docker Compose v2
- [uv](https://docs.astral.sh/uv/) for Python tooling
- Python 3.12 (managed by uv via `backend/.python-version`)

### 1. Configure local secrets

```bash
cp .env.docker.example .env.docker        # repo root: Postgres credentials for the local dev stack
cp backend/.env.example backend/.env      # backend config (DATABASE_URL, log level, ...)
```

Both files are gitignored. Default dev passwords are fine on a local machine — never use them anywhere reachable from the network.

### 2. Start the local infrastructure (Postgres + Redis + Adminer)

```bash
./scripts/dev-up.sh
```

Equivalent of `cd docker && docker compose up -d`. Wait for healthchecks (`cd docker && docker compose ps`) — both `postgres` and `redis` should report `healthy`.

Endpoints:

| Service  | URL / DSN                                                                       |
|----------|---------------------------------------------------------------------------------|
| Postgres | `postgresql+asyncpg://netbuddy:changeme_for_dev_only@localhost:5432/netbuddy`   |
| Redis    | `redis://localhost:6379/0`                                                      |
| Adminer  | http://localhost:8080 (System: PostgreSQL, Server: `postgres`, User: `netbuddy`)|

The Postgres volume `pgdata` persists across `docker compose down`. Use `./scripts/dev-down.sh -v` to wipe it.

### 3. Run the backend

```bash
cd backend
uv sync                                        # first time only
uv run uvicorn netbuddy.api.main:app --reload
```

Smoke-test: `curl http://127.0.0.1:8000/health` → `{"status":"ok","app":"NetBuddy"}`.

### 4. Stop the stack

```bash
./scripts/dev-down.sh
```

## Common commands

```bash
# Lint + format
cd backend && uv run ruff check . && uv run ruff format .

# Type-check
cd backend && uv run mypy src/

# Tests
cd backend && uv run pytest
```
