# NetBuddy — Deployment auf der On-Prem-VM

Produktions-Stack via Docker Compose: **postgres + redis + backend (API) + worker (ARQ) +
frontend (nginx, TLS + Reverse-Proxy)**. Alles in `docker/docker-compose.prod.yml`.

## VM-Anforderungen
- **4 vCPU / 8 GB RAM / 100 GB SSD**, Ubuntu 26.04 LTS (oder Debian 12) — passt.
- **Docker + Compose-Plugin** installiert.
- **Netz:** die VM muss in alle Standort-Mgmt-Netze routen (10.120/121/122/123.0.0/16),
  sonst sind die Geräte nicht erreichbar.
- **FortiGate (und künftige API-Firewalls):** Trusted-Host des API-Tokens muss die **VM-IP**
  zulassen, sonst 403.

## Docker installieren (Ubuntu)
```bash
sudo apt update && sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"   # neu einloggen
```
> Falls für Ubuntu 26.04 noch kein Docker-Repo-Codename existiert: vorerst den 24.04-Codename
> (`noble`) eintragen oder Dockers convenience-Skript nutzen.

## Deployen
```bash
git clone https://github.com/swissgiant/Netbuddy.git && cd Netbuddy/docker
cp .env.prod.example .env.prod && nano .env.prod      # Passwörter + FERNET_KEY setzen
./gen-selfsigned-cert.sh <vm-ip-oder-hostname>        # TLS-Zertifikat (oder echtes hinterlegen)
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```
Migrationen laufen automatisch im Backend-Container (`RUN_MIGRATIONS=1`). Danach:
**https://\<vm\>/** öffnen → beim ersten Aufruf den Admin anlegen (Setup-Screen).

## Betrieb
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps          # Status
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f backend
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build  # Update nach git pull
```
**Backup** (Inventar + verschlüsselte Credentials):
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec postgres \
  pg_dump -U netbuddy netbuddy | gzip > netbuddy-$(date +%F).sql.gz
```
> Den **FERNET_KEY separat sichern** — ohne ihn sind die DB-Passwörter nach einem Restore unlesbar.

## Sicherheit (Stand)
- TLS am nginx (HTTP→HTTPS-Redirect), Session-Cookie `secure`+httpOnly (`USE_SECURE_COOKIES=true`).
- Credentials Fernet-verschlüsselt in der DB; RBAC (viewer/operator/admin).
- Self-signed-Cert → Browser-Warnung; für warnungsfrei ein internes CA-/echtes Zertifikat in
  `docker/certs/netbuddy.{crt,key}` ablegen.
- Postgres/Redis sind **nicht** nach außen gemappt (nur im Compose-Netz); nur 80/443 offen.
