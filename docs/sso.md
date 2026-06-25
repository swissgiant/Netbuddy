# NetBuddy — SSO mit Microsoft Entra ID (Azure AD)

Anmeldung über Entra ID per OIDC-Authorization-Code-Flow. **Die Rolle ergibt sich aus der
AAD-Sicherheitsgruppen-Mitgliedschaft** — keine manuelle Userpflege für SSO-Nutzer. Lokale
Benutzer (Username/Passwort) bleiben als **Break-Glass-Zugang** erhalten.

Mapping (Hierarchie, Admin zuerst — admin ⊇ operator ⊇ viewer):

| AAD-Gruppe | NetBuddy-Rolle |
|---|---|
| `NetBuddy-Admin`    | admin (alles inkl. Userverwaltung + SSO-Config) |
| `NetBuddy-Operator` | operator (lesen + discover/validate + Inventar) |
| `NetBuddy-Viewer`   | viewer (read-only) |

Wer in keiner der drei Gruppen ist, bekommt **keinen Zugriff**.

## 1. Entra-Seite einrichten (einmalig)

Per PowerShell-Script (idempotent, legt App-Registrierung + 3 Gruppen + Claims + Secret an und
gibt alle Werte aus):

```powershell
# benötigt: Install-Module Microsoft.Graph -Scope CurrentUser
cd backend/scripts
./Setup-Entra-NetBuddy.ps1 -RedirectHost bls-srv-netbuddy.bls.local -GrantAdminConsent
```

Das Script erledigt:
- App-Registrierung (Single-Tenant, Web), Redirect-URI `https://<host>/auth/callback`
- `groupMembershipClaims = "SecurityGroup"` (Gruppen kommen in den ID-Token)
- Graph `User.Read` (delegiert) + Admin-Consent — für den Overage-Fallback
- drei Sicherheitsgruppen (Viewer/Operator/Admin) + ein Client-Secret

Am Ende gibt es **Tenant-ID, Client-ID, Client-Secret und die drei Gruppen-Object-IDs** aus.
Danach Mitglieder den Gruppen zuweisen.

> **Stolpersteine:** Redirect-URI braucht **HTTPS + FQDN** (keine nackte IP). Gruppen-Claim muss
> aktiviert sein. Bei „Vielgruppen"-Usern (>~200 Gruppen) liefert Entra keinen groups-Claim →
> NetBuddy lädt die Gruppen dann per Graph (`/me/transitiveMemberOf`) nach (deshalb User.Read).

## 2. NetBuddy konfigurieren (Admin-UI)

Als Admin einloggen → **🔐 SSO** → Werte aus dem Script eintragen, **SSO aktiviert** anhaken,
speichern. Das Client-Secret wird **Fernet-verschlüsselt** in der DB abgelegt und nie wieder
angezeigt (beim erneuten Speichern leer lassen = behalten).

Danach erscheint auf der Login-Seite zusätzlich **„🪟 Mit Microsoft anmelden"**.

## 3. Voraussetzungen am Netz

- Das Backend (VM) muss **`login.microsoftonline.com`** und (für den Overage-Fallback)
  **`graph.microsoft.com`** erreichen.
- HTTPS muss stehen (Redirect-URI). Auf der Prod-VM erledigt durch das nginx-Frontend +
  internes CA-Zertifikat (siehe `tools/issue_cert.sh` / `docs/deployment.md`).

## Technik (kurz)

- `services/oidc.py`: authlib-Client (lazy aus DB-Config), Gruppen→Rolle, Graph-Overage-Fallback,
  User-Upsert (per `oidc_subject` = Entra `oid`-Claim).
- Routen in `api/routes/auth.py`: `GET /auth/oidc-status` (public), `GET /auth/login/entra`,
  `GET /auth/callback`, `GET|PUT /auth/oidc-config` (admin-only).
- `SessionMiddleware` (in `api/main.py`) hält nur kurzlebig State/Nonce des Redirect-Flows;
  der eigentliche Login läuft weiter über das bestehende `nb_session`-Cookie.
- Config-Tabelle `oidc_config` (Single-Row); `app_user` um `oidc_subject` + `email` erweitert,
  `password_hash` ist für SSO-only-User `NULL`.
