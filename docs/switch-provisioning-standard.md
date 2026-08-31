# Switch-Provisioning-Standard (verbindlich)

Festgelegt von Alex, 31.08.2026 (nach S70–S72: fehlende Trunks auf SLO-20/21/22/25,
OS10-Cores ohne VLAN 120/130, Core-Port ohne Trunk beim SLO-27-Anschluss).

**Regel: Jeder Access-Switch muss diese Konfiguration haben. Jeder neue Uplink wird
erst als fertig betrachtet, wenn alle Punkte erfüllt und verifiziert sind.**

## 1. Uplink-/Interconnect-Ports (Switch↔Switch, Switch↔Firewall)

- **Trunk-Mode**, native VLAN 1 untagged (Prod-Verhalten bleibt unverändert)
- **Alle Test-VLANs getaggt: 101–116, 120 (Aufsetznetz), 130 (Gästenetz)**
- Bei Plattformen mit Allowed-Listen (OS10, Centec, TP-Link) muss die Liste explizit
  `101-116,120,130` enthalten — neue unternehmensweite VLANs werden dort NACHGEPFLEGT
- AP- und Client-Ports bleiben Access (kein Trunk nötig)

## 2. Inbetriebnahme neuer Glasfaser-Uplinks — FEC/Link und Trunk gehören ZUSAMMEN

1. Link prüfen (Transceiver-Typ, RX/TX-Power beidseitig)
2. Bei 25G und Link down: FEC-Modi durchprobieren **inkl. Port-Bounce nach jedem
   Wechsel** (UniFi ECS ↔ N8560: `fec mode base-r`; FS S5800 ↔ N8560: `fec mode rs`
   + shutdown/no shutdown)
3. **Im selben Arbeitsgang:** Core-Port UND Switch-Uplink auf Trunk stellen (Punkt 1)
4. Save auf beiden Seiten, Verify (`show vlan id 103` muss den Port listen; Achtung:
   OS10 komprimiert Portlisten zu Ranges)
5. Funktionsbeweis: Test-Client oder Port in ein Testnetz → DHCP-Lease von der FW

## 3. Grundkonfiguration jedes Switches

- `lldp enable` global, **keine** Interface-Level-Disables auf Uplinks
- Fleet-Service-User statt Factory-Credentials (Factory-Login wird ersetzt)
- Statische Mgmt-IP nach Konvention (Nummer = letztes IP-Oktett) + Default-Route zur FW
  - **Reihenfolge: erst statische IP setzen, DANN `no ip address dhcp`** — sonst Lockout
- Nach JEDER Änderung: running → startup speichern (Vendor-Save-Sequenz), Reboot-fest

## 4. Plattform-Referenz

| Plattform | Trunk-Kommandos | Save |
|---|---|---|
| Dell OS6 | `switchport mode trunk` (trägt automatisch alle VLANs) | `copy running-config startup-config` + `y` |
| Dell OS10 | `switchport mode trunk` + `switchport trunk allowed vlan 101-116,120,130` (additiv) | `write memory` |
| FS Centec (S5800) | `switchport mode trunk` + `switchport trunk allowed vlan add 101-116,120,130` | `write` |
| FS/Ruijie (N8560) | `switchport mode trunk` (VLAN lists ALL) | `write` |
| TP-Link JetStream | `switchport general allowed vlan 101-116,120,130 tagged` | `copy running-config startup-config` |
| UniFi | Ports Default „Allow All" — VLANs laufen durch; Anbindung core-seitig als Trunk | via Controller |

## 5. Verifikation (NetBuddy)

- Gerät in NetBuddy inventarisiert (Adapter, Credential, Discovery gelaufen)
- LLDP-Kante zum Core in der Topologie sichtbar
- Port→VLAN-Zuweisung über NetBuddy liefert `verifiziert + gespeichert`
