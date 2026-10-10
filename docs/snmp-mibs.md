# SNMP für NetBuddy-Inventar + PRTG

## Read-Community
Standard-Read-Community **`PRTG`** (SNMP v2c), organisationsweit auf allen Storages/Servern.
In NetBuddy als Credential **„PRTG SNMP"** hinterlegt (editierbar unter Credentials). PRTG nutzt
dieselbe Community. NetBuddy probiert beim Anreichern die PRTG-Community zuerst, dann die
Switch-Community aus Passwordstate („B-HQ Switch / SNMP Community").

## OIDs, die NetBuddy abfragt (numerisch, keine MIB-Datei nötig)
| Zweck | OID |
|---|---|
| System-Beschreibung (Modell-Hinweis) | 1.3.6.1.2.1.1.1.0 (sysDescr) |
| System-Name | 1.3.6.1.2.1.1.5.0 (sysName) |
| Kapazität nutzbar/belegt (NAS) | 1.3.6.1.2.1.25.2.3.1 (hrStorageTable: .4 Units, .5 Size, .6 Used, Typ .2 = FixedDisk 25.2.1.4) |
| RAM (Server) | 1.3.6.1.2.1.25.2.2.0 (hrMemorySize, KB) |
| Seriennummer generisch | 1.3.6.1.2.1.47.1.1.1.1.11 (ENTITY-MIB entPhysicalSerialNum) |
| NetApp Modell / Serial | 1.3.6.1.4.1.789.1.1.5.0 / .789.1.1.9.0 |
| Synology Modell / Serial / Version | 1.3.6.1.4.1.6574.1.5.1.0 / .2.0 / .3.0 |
| QNAP Modell / Serial | 1.3.6.1.4.1.24681.1.2.12.0 / .24681.1.4.4.0 |

## MIB-Dateien für PRTG (zum Import in den PRTG MIB-Importer)
PRTG braucht die Text-MIBs der Hersteller. Bezugsquellen:
- **HOST-RESOURCES-MIB**, **ENTITY-MIB**, **SNMPv2-MIB**: Standard (IETF), in PRTG meist enthalten.
- **NetApp**: `NETWORK-APPLIANCE-MIB` / `NETAPP-MIB` — NetApp Support-Portal (mysupport.netapp.com).
- **Synology**: `SYNOLOGY-*-MIB` — https://global.download.synology.com/download/Document/Software/DeveloperGuide/ (Synology_MIB_File).
- **QNAP**: `NAS.mib` — QNAP-Website / im QTS enthalten.
- **IBM Storwize/FlashSystem**, **Dell EMC**, **IBM i (AS/400)**: jeweils vom Hersteller-Support.

> Hinweis: NetBuddy läuft auf der Linux-VM `bls-srv-netbuddy` und hat keinen Zugriff auf das
> Windows-Laufwerk `E:`. Diese Referenz liegt im Repo unter `docs/snmp-mibs.md` (also auch auf der
> VM unter `/home/msak/netbuddy/docs/`). Die eigentlichen MIB-Dateien bitte aus den obigen Quellen
> nach `E:\Netbuddy\MIBs\` legen; eine Linkliste/Ablage kann NetBuddy nicht selbst auf E: schreiben.

## SNMP auf den Geräten aktivieren
Antwortet ein Gerät nicht, ist SNMP dort aus oder gefiltert. Aktivierung je Vendor:
- **Synology/QNAP**: DSM/QTS → Systemsteuerung → Terminal&SNMP → SNMP-Dienst + v2c-Community `PRTG`.
- **NetApp ONTAP**: `security login` + `snmp community add -community-name PRTG -type ro`.
- **IBM Storwize**: `chsnmpserver` / GUI.
- Firewall/ACL: Lesezugriff von NetBuddy (10.120.20.101) und PRTG auf UDP 161 erlauben.
