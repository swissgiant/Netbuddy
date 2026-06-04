# NetBuddy Frontend (Topologie-GUI)

React + Vite + TypeScript + **Cytoscape.js**. Zeigt die Netz-Topologie als zoom-/pan-baren Graph
(Standorte, Switches, Firewalls) mit ein-/ausblendbaren Layern. Daten kommen vom Backend
(`GET /topology`, `GET /adapters`).

> **Status:** `npm install` + `npm run build` (tsc-Typecheck **und** Vite-Bundle) laufen sauber durch.
> Der **visuelle Browser-Render** wurde noch nicht geprüft (keine Browser-Umgebung im Build) — bitte
> einmal `npm run dev` öffnen und draufschauen.

## Starten

```bash
# 1) Backend muss laufen (Port 8000):
cd ../backend && uv run uvicorn netbuddy.api.main:app --reload

# 2) Frontend:
cd frontend
npm install
npm run dev          # http://localhost:5173  (Vite proxyt /topology, /adapters, … ans Backend)
```

## Was es kann
- **Graph** der Topologie (Cytoscape, Mausrad = Zoom, Drag = Pan), Layout `cose`.
- **Layer-Toggles** links: Geräte-Typen (site/switch/firewall/router/ap/other) und Verbindungen
  (Standort-Zugehörigkeit / LLDP-Links) ein-/ausblenden.
- **Adapter-Status**-Panel (validiert/unvalidiert je Capability aus `GET /adapters`).
- **↻ Neu laden** holt Topologie + Adapter neu.

## Daten
Topologie wird aus dem persistierten Inventar gebaut (nach `POST /devices/{id}/discover`): Knoten =
Sites + Devices, Kanten = Geräte→Standort (`member`) und LLDP-Links zwischen bekannten Geräten
(`lldp`, gematcht über `remote_system_name == hostname`).

## Noch offen / Ideen
- Detail-Panel beim Klick auf einen Knoten (Interfaces/LLDP/MAC/Validierungs-Status).
- Live-Aktionen (Validate/Discover) aus dem GUI auslösen.
- Bessere LLDP-Matching-Heuristik (Chassis-ID/MAC statt nur Hostname).
