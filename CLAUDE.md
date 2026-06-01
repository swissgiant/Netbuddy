# NetBuddy — Project Context for Claude Code

## Was ist NetBuddy

Ein webbasiertes Tool für Netzwerk-Administration, fokussiert auf Switches und Firewalls. Solo-Projekt von Alex. Zielumgebung: On-Prem VM, deployed via Docker Compose.

### Kern-Features (Ziel)

1. **Geräte-Discovery** — automatisches Auffinden von Switches im Netz via LLDP/CDP/SNMP
2. **Inventar** — wo hängt welches Endgerät an welchem Switch-Port?
3. **VLAN-Management** — unternehmensweite VLANs anlegen, auf relevanten Switches automatisch ausrollen
4. **RSTP-Topologie** — Spanning-Tree visualisieren und optimieren
5. **Multi-Vendor** — modulare Adapter-Architektur: Cisco, Juniper, HPE/Aruba, Ubiquiti, ...
6. **KI-gestützte Adapter-Generierung** (späte Phase) — neue Vendor-Adapter aus CLI-Doku ableiten

## Architektur-Prinzipien

- **Vendor-Abstraction-Layer**: einheitliches `SwitchAdapter`-Protocol, konkrete Adapter pro Vendor als Plugin
- **Capability-Detection**: Adapter melden, was sie können — Frontend graut nicht-unterstützte Features aus
- **Read-only first**: Schreibzugriffe auf echte Hardware erst, wenn Backup/Rollback steht
- **Transaktional**: Multi-Switch-Konfigs sind atomar — bei Fehler Rollback auf allen betroffenen Geräten
- **Audit-Log**: jede Änderung mit User, Timestamp, Diff
- **Async durchgängig**: viele parallele SSH/SNMP-Verbindungen — async ist Pflicht, nicht Optional

## Tech-Stack

### Backend
- **Python 3.12** (gepinnt via uv, NICHT das System-Python 3.14)
- **uv** als Package-Manager (nicht pip, nicht Poetry)
- **FastAPI** als Web-Framework
- **SQLAlchemy 2.0** (async, mit asyncpg)
- **Alembic** für DB-Migrations
- **pydantic-settings** für Konfiguration aus .env
- **loguru** für Logging
- **ARQ** (geplant) für Background-Jobs

### Switch-Kommunikation (kommt später)
- **Netmiko** und/oder **Scrapli** für SSH/CLI
- **pysnmp** für SNMP
- **NAPALM** wo verfügbar
- **TextFSM** (ntc-templates) zum Parsen von CLI-Output
- **Jinja2** für Command-Templates pro Vendor

### Frontend (kommt später)
- Vue oder React + Vite (Entscheidung noch offen)
- **Cytoscape.js** für Topologie-Visualisierung

### Persistence
- **PostgreSQL 16** für Inventar, Konfig-Historie, Audit-Log
- **Redis** für Caching und Job-Queues

### Tooling
- **ruff** (Lint + Format)
- **mypy --strict**
- **pytest** + pytest-asyncio
- **httpx** für API-Tests

## Projektstruktur

```
~/projects/netbuddy/             ← Repo-Root
├── CLAUDE.md                    ← diese Datei
├── README.md
├── .gitignore
├── docker/                      ← Compose-Files, Dockerfiles
└── backend/
    ├── pyproject.toml
    ├── uv.lock
    ├── .python-version
    ├── .env                     ← gitignored
    ├── .env.example
    ├── src/
    │   └── netbuddy/
    │       ├── api/             ← FastAPI Routes
    │       │   └── routes/
    │       ├── core/            ← Config, Logging, Domain-Types
    │       ├── adapters/        ← Vendor-spezifische Plugins
    │       ├── services/        ← Discovery, VLAN-Orchestrator, STP-Analyzer
    │       ├── db/              ← SQLAlchemy-Modelle, Migrations
    │       └── workers/         ← Background-Jobs
    ├── tests/
    ├── templates/               ← Jinja2 für CLI-Commands pro Vendor
    └── parsers/                 ← TextFSM
```

## Coding-Konventionen

- **Sprache**: Code, Variablen, Kommentare auf **Englisch**. Docstrings und User-facing Messages: Deutsch ist okay
- **Type Hints überall** — mypy strict muss durchlaufen
- **Async-first** — Sync-Code nur wenn explizit nötig (z.B. bei Netmiko, das kein async kann)
- **Pydantic für alle API-Schemas und Domain-Daten**
- **Dataclasses** nur intern, nicht an API-Grenzen
- **Funktionen klein halten** — eine Aufgabe pro Funktion
- **Imports**: stdlib → third-party → eigene, alphabetisch (ruff isort regelt das)
- **Pfade**: nie hardcoden, immer über `pathlib.Path` und Konfig
- **Geheimnisse**: NIE im Code, nie ins Git. .env lokal, später verschlüsselt in DB

## Was bewusst NICHT verwendet wird (am Anfang)

- Kein Kubernetes (Solo-Projekt, On-Prem VM)
- Kein komplexes CI/CD (einfache GitHub Actions reicht)
- Keine Microservices (Modular-Monolith)
- Kein RBAC am ersten Tag (kommt, wenn das Tool über Read-Only hinausgeht)
- Kein Frontend in Phase 1

## Phasen-Plan

- **Phase 1 (jetzt)**: Skelett, Discovery read-only, Inventar in DB, ein Vendor (Cisco IOS)
- **Phase 2**: Topologie-Visualisierung, RSTP-Anzeige, mehr Read-Methoden
- **Phase 3**: Schreibzugriffe (VLANs), Backup/Restore, Audit-Log, Dry-Run-Modus
- **Phase 4**: Zweiter und dritter Vendor (Juniper, Ubiquiti)
- **Phase 5**: KI-gestützte Adapter-Generierung

## Test-Lab

Alex hat echte Switches als Test-Hardware. **Vorsichtsregeln**:
- Erst nur Read-Operationen auf echten Geräten
- Separater Service-User pro Switch, nicht Admin-Account
- Credentials in lokaler `secrets.yaml` (gitignored)
- Schreibzugriff frühestens nach funktionierender Backup-Logik

## Commands

```bash
# Server starten
uv run uvicorn netbuddy.api.main:app --reload

# Lint + Format
uv run ruff check . && uv run ruff format .

# Type-Check
uv run mypy src/

# Tests
uv run pytest

# Migration erstellen
uv run alembic revision --autogenerate -m "beschreibung"

# Migration anwenden
uv run alembic upgrade head
```

## Wichtige Hinweise an Claude Code

- **Niemals** das System-Python 3.14 verwenden, nur uv mit gepinntem 3.12
- **Niemals** `.env` oder `secrets.yaml` committen
- **Niemals** echten Switch-Zugriff im Code, ohne dass Alex es explizit will (wir bauen erst Skelett + Tests)
- Bei Architektur-Unsicherheit: **nachfragen, nicht raten**
- Code-Beispiele in Docstrings willkommen, aber realistisch — keine Marketing-Sätze
- Wenn Tests Sinn ergeben: schreib welche, aber pragmatisch (keine 100%-Coverage-Pflicht)
