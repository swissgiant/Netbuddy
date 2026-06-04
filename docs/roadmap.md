# Roadmap, Entscheidungen & offene Fragen

Lebendes Dokument für den **autonomen Bau** (Alex kann im aktuellen Zustand nicht live testen).
Session-Fortschritt: `STATUS.md`. Fleet-Fakten: `docs/fleet-and-adapters.md`.

## Phasen-Status

| Phase | Inhalt | Status |
|---|---|---|
| Adapter-Framework | deklarative Profile + DeclarativeAdapter, Registry, Conformance | ✅ (S5/7) |
| CLI-Profile | cisco_ios, dell_os10, dell_os6, fs_centec, fs_ruijie (sysinfo live-validiert) | ✅ (S8) |
| A2 — Live-Read-only + Validierungs-Tool | connect(), generic transport, validate-Endpoints, ValidationCheck | ✅ (S9) |
| C — Discovery/Persistenz | DTOs → ORM-Aggregate, DiscoveryRun, Aggregat-Endpoints | ✅ (S10) |
| B — API-Adapter-Klasse + UniFi | zweite Integrationsart, Credential-API-Felder, Site/Controller | ✅ (S11) |
| A3 — Assistiertes Onboarding | Geräte-Hilfe → Kandidaten-Befehle → Profil-Entwurf | ✅ (S12) |
| D — Aruba CX (CLI) + Meraki (API) | weitere Vendor | ✅ (S13) |
| E — Fortigate (Firewall, API, read-only) | Firewall-Geräteklasse | ✅ (S14) |
| G — GUI / Topologie-Graph | Topologie-API ✅ + React/Cytoscape-Frontend (build/typecheck ✅, Browser-Render offen) | 🟢 (S15) |
| G2 — GUI-App-Ausbau | Menü, Geräte-Liste + Add/Remove, Credentials-Verwaltung, LLDP-Vorschläge, Dark Mode (default) + Toggle | 🟢 (S16) build ✅, Browser-Feincheck offen |
| **H — User/Login + RBAC** | Login, Userverwaltung, Rollen/Berechtigungen (wer darf suchen/lesen/ändern) | 🔨 als Nächstes |
| F — Schreibzugriff/VLAN/VPN (Nordstern) | NICHT autonom — braucht Alex' Go + Backup/Rollback | ⛔ gesperrt |

### Backlog aus Alex' Wünschen (live gesammelt)
- **G2 (jetzt):** Navigations-**Menü**; **Listenansicht** Switches/FW (zusätzlich zum Graph);
  Geräte **hinzufügen/entfernen** im GUI; **Credentials** sauber verwalten (SSH + API); **naheliegende
  Switches automatisch erkennen + vorschlagen** (aus LLDP-Nachbarn, die noch nicht im Inventar sind);
  **Dark Mode als Default, umschaltbar**.
- **H (danach):** Login + Userverwaltung + RBAC (Rollen: wer darf suchen/lesen/ändern). CLAUDE.md
  hatte RBAC zurückgestellt — wird jetzt nachgezogen. Enforcement auf allen Endpoints + Login im GUI.

### Phase G — GUI / Topologie (Zusatzanforderung Alex)

Grafische, **zoombare** Übersicht der Struktur (Standorte, Switches, Firewalls) als **Graph**, nicht
nur Listen; verschiedene Infos als Layer **ein-/ausblendbar**. Plan:
- **Backend zuerst:** `GET /topology` liefert Knoten (Sites, Devices/Switches, Firewalls) + Kanten
  (Uplinks aus LLDP-Nachbarn, Site-Zugehörigkeit). Unabhängig vom Frontend-Framework, autonom baubar.
  Wird voller, sobald **Sites** (Phase B) und **Firewalls** (Phase E) existieren.
- **Frontend (entschieden):** **React + Vite + TypeScript + Cytoscape.js** (Graph, Zoom/Pan,
  Layer-Toggle).
- Reihenfolge (entschieden): Topologie-API begleitend bauen; **volles GUI nach B (Sites) + E
  (Firewalls)**.

## Autonom getroffene Annahmen (bei Bedarf korrigieren)

- **API-Adapter (UniFi/Meraki/Forti) werden gegen einen injizierbaren HTTP-Client gebaut und gegen
  Fake-Antworten getestet** — kein echter API-Call im Bau. Endpunkte/Felder nach öffentlicher Doku,
  als `provenance: unvalidated` bis echter Zugriff.
- **Read-only durchgängig.** Keine Schreibzugriffe auf Geräte in irgendeiner autonomen Phase.
- Discovery überschreibt volatile Daten (LLDP-Nachbarn, MAC-Table) pro Lauf komplett; Interfaces
  werden ge-upsertet (per `(device_id, name)`).

## Offene Fragen an Alex

- **Frontend im Browser anschauen:** `cd frontend && npm run dev` (Backend muss laufen). Build +
  TypeScript-Check laufen bereits sauber; nur der visuelle Render/Bedienung steht noch aus.
- API-Auth-Details für UniFi/Meraki/Forti (Header/Token-Format) gegen echte Systeme bestätigen.

## Bekannte Schwächen / Normalisierung nötig

- **Interface-Namens-Mismatch:** manche Vendor nennen denselben Port je Befehl unterschiedlich
  (OS10: `Eth 1/1/1` in `show interface status`, aber `ethernet1/1/1` in lldp/mac). Discovery legt
  dann zusätzliche „virtuelle" Interfaces an (create-if-missing). → Später Namens-Normalisierung pro
  Vendor, damit lldp/mac sauber auf das echte Interface referenzieren.

## Phase B — offene Folgepunkte (notiert)

- **UniFi bisher per-Device (Match über mgmt_ip)**; Controller-**Bulk-Discovery** (alle Geräte eines
  Controllers auf einmal enumerieren) fehlt noch → eigener Schritt.
- **Site-Modell existiert**, ist aber noch nicht in Geräte-Eintrag/Topologie verdrahtet (kommt mit G).
- UniFi-Auth: `X-API-KEY`-Header angenommen (neue UniFi-API). Cookie-Login-Variante ggf. nötig — live klären.

## Testlücke (notiert)

- Endpoint-Tests überschreiben `get_session` mit einer pro-Test zurückgerollten Session → die
  echte Commit-Logik wird nicht getestet (hat den fehlenden Commit in `get_session` nicht gefangen,
  Fix in `d3cd2f4`). Später: ein Integrationstest gegen den echten Session-Pfad.

## Muss später live validiert werden (gegen echte Hardware)

- interfaces/lldp/mac aller CLI-Profile (dell_os10/os6, fs_centec/ruijie) — `provenance: unvalidated`.
- scrapli `AsyncGenericDriver` gegen reale Dell/FS-Geräte (read-only `show`).
- Sobald `POST /devices/{id}/validate` gegen echte Switches läuft: Profile bei Bedarf nachziehen.
