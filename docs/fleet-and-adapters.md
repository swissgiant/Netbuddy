# Fleet & Adapter-Architektur

Diese Datei hält fest, **welche Geräte real im Einsatz sind** und **wie NetBuddy sie anbinden muss**.
Erhoben im „Sammelmodus" (Anfang Juni 2026) aus echten `show version`-Captures bzw. UniFi-Controller —
nicht aus Hersteller-Doku geraten. Fortschritt/Bau-Stand steht in `STATUS.md`.

## 1. Switch-Fleet (real erfasst)

| Host (Bsp.) | Vendor | Modell | OS / Version | Zugriff | Integration |
|---|---|---|---|---|---|
| SW2 | Dell | S5248F-ON | OS10 10.5.2.6 | CLI/SSH | `dell_os10` (TextFSM-Profil) |
| BLS-SW-51 u.a. (mehrfach) | Dell | N2248PX-ON | OS6 6.6.3.15 | CLI/SSH | `dell_os6` (TextFSM-Profil) |
| BLS-SW-56 | FS.com | S5800 / HW 48MBQ | FSOS 7.0.4.21 | CLI/SSH | `fs_centec` (`eth-0-x`) |
| FS# | FS.com | N8560-48BC | FSOS 11.0(5)B9P66S2 | CLI/SSH | `fs_ruijie` (`Gi 0/x`) |
| Cusano / Slovenia / Sulgen | Ubiquiti UniFi | USW/ECS-Switches + viele APs | UniFi Network | **Controller-API (JSON)**, multi-site (3 Controller) | `unifi` (API-Adapter) |

Gewünscht, noch nicht im Lab gezeigt: **Cisco** Catalyst/IOS (CLI — `cisco_ios`-Profil existiert bereits),
**HP Aruba** (ArubaOS-CX/ProCurve CLI; Aruba Central = API), **Cisco Meraki** (cloud Dashboard-API).

### Vendor-Fakten (aus echten Captures)

- **Dell OS10** (`SW2#`): `show version` → `OS Version:`, `System Type:` (=model), Banner
  `Dell EMC Networking OS10 Enterprise`. Serial **nicht** in `show version` → `show license status`
  (`Service Tag :   <serial>`, `Product Name :`). Hostname nur im Prompt. → System-Info braucht **2 Befehle**.
- **Dell OS6 / N-Series** (`BLS-SW-51#`): `show version` enthält alles in **einem** Befehl
  (`System Model ID`, `Serial Number`, Unit-Tabelle `active`=os_version bzw. `Image File`). Dotted-Label-Format.
  Hostname nur im Prompt.
- **FS.com = ZWEI verschiedene CLIs** (nicht eine!):
  - **Centec** (S5800, `eth-0-x`): `show version` = `Fiberstore Software, S5800, Version …`;
    Interfaces `a-full`/`a-1000`; MAC-Table mit Titel/Legende; `show lldp neighbor` (non-brief).
  - **Ruijie** (N8560-48BC, `Gi 0/x`, prompt `FS#`): `show version` key:value
    (`System description`, `System software version`, `System serial number`); `show mac-address-table`
    (hyphenated); `show lldp neighbors detail` (lokaler Port im Block-Header).
- **Ubiquiti UniFi**: 3 Sites/Controller. Switches v.a. in Cusano (USW, ECS 48 PoE, ECS Aggregation,
  Core1). APs/Kameras (U6 LR, U7 Pro, G6 Bullet, G4 PTZ, U(N)VR, AI-LPR) = WLAN/Protect, nicht Switch-Scope.

## 2. Firewalls (Standort-Kopplung)

Die Standorte sind per Firewalls verbunden. Ziel: auch diese ins Tool, u.a. um **VPNs einzurichten,
damit VLANs standortübergreifend ausgerollt** werden können (CLAUDE.md: „Switches und Firewalls",
„unternehmensweite VLANs").

| Firewall | Vorkommen | Zugriff | Klasse |
|---|---|---|---|
| Fortigate / FortiOS | fast überall (Standard) | REST-API (Token) + CLI; FortiManager zentral | API-Adapter (primär) |
| WatchGuard / Fireware | Italien (eine) | CLI + WatchGuard-Cloud-API | API/CLI |
| Palo Alto / PAN-OS | gewünscht | XML/REST-API, Panorama | API-Adapter |
| Cato Networks | gewünscht | reine Cloud-SASE, GraphQL-API (kein on-prem CLI) | API-Adapter (cloud) |

## 3. Zwei Integrations-Klassen (zentrale Konsequenz)

1. **CLI / TextFSM-Profil** — Dell, FS.com, Cisco IOS, Aruba-CX/ProCurve.
   `CommandTransport` → CLI-Text → TextFSM → DTO, deklaratives YAML-Profil, `DeclarativeAdapter`.
2. **JSON-API-Adapter** — UniFi, Meraki, Fortigate, Palo Alto, Cato, Aruba Central.
   Kein SSH/Profil; HTTP/GraphQL-Client → JSON → DTO. Erfüllt dasselbe Adapter-Protocol, aber als
   **Code-Adapter**. Oft **cloud / multi-site / multi-controller** (eine Credential erschließt viele Geräte).

Das Adapter-Framework (bisher rein CLI/Transport-zentriert) muss **beide** Klassen tragen.

## 4. Onboarding & Validierungs-Strategie

Es sind **über 30 Switches**. Beispiel-Output für jede Box manuell zu pasten skaliert nicht. Stattdessen:

1. **Basic CLI-Adapter bauen** (Transport + die 4 Profile dell_os10/dell_os6/fs_centec/fs_ruijie), sodass NetBuddy read-only an die Geräte connecten kann.
2. **Switches eintragen** (Device + Credential in die DB; Mechanismus dafür ist nötig → siehe Unterbau).
3. **Read-only direkt von den Geräten auslesen** — das **validiert** die Profile gegen echte Hardware *und* füllt das Inventar. Alex hat read-only Live-Zugriff hierfür freigegeben.

Folge fürs Tooling: der echte `ScrapliTransport` muss für Dell/FS funktionieren (scrapli-Plattform-Mapping,
ggf. scrapli-community/GenericDriver) und es braucht einen **Eintrage-/Import-Weg für viele Geräte**.

## 5. Produktziel (Nordstern, spätere Phase)

VLANs **standortübergreifend** ausrollen — inkl. VPN-Orchestrierung über die Firewalls
(L2/L3-Extension über IPsec/SD-WAN). Schreibzugriff + Multi-Device-Transaktion über Geräteklassen
hinweg → erst nach Read-only + Backup/Rollback (CLAUDE.md Phasen 3+). Hier nur als Richtung notiert.
