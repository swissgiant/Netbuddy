#!/usr/bin/env bash
# NetBuddy — Zertifikat von der AD-CS (BLS-T1CA) holen und in den nginx einbauen.
#
# Hintergrund (Runbook bls-srv-vapp2): die CA bietet nur RPC-Enrollment → Ausstellung via
# `certipy` auf Linux. Dieses Skript automatisiert Schritte 2–6:
#   2) certipy req  → <host>.pfx (Cert + Key)
#   3) PFX → PEM    (Leaf-Cert + Key)
#   4) CA-Kette aus AD via LDAPS-Simple-Bind (Intermediate BLS-T1CA + Root)
#   5) Fullchain (Leaf + Intermediate) zusammensetzen, gegen Root verifizieren
#   6) in docker/certs einbauen, Frontend-Container neu starten, Arbeitskopien shreddern
#
# Voraussetzung (einmalig, NICHT in den Chat/Repo):
#   sudo install -d -m 700 /opt/urs/secrets
#   printf '%s' 'AD-PASSWORT-von-msak' | sudo tee /opt/urs/secrets/adpw >/dev/null
#   sudo chmod 600 /opt/urs/secrets/adpw
#
# Aufruf (auf der VM, im Subnetz des DC):  ./issue_cert.sh [FQDN]
set -euo pipefail

FQDN="${1:-bls-srv-netbuddy.bls.local}"

# --- Eckdaten (per Env überschreibbar) — aus dem bls-srv-vapp2-Runbook -----------------------
DOMAIN="${DOMAIN:-bls.local}"
CA="${CA:-BLS-T1CA}"
CA_HOST="${CA_HOST:-BLS-SRV-T1CA.bls.local}"
TEMPLATE="${TEMPLATE:-BLS-WebServer-RSA4096Linux}"   # verlangt RSA-4096 (sonst 0x80094811)
DC_IP="${DC_IP:-10.120.20.10}"
ENROLL_USER="${ENROLL_USER:-msak@bls.local}"
ADPW_FILE="${ADPW_FILE:-/opt/urs/secrets/adpw}"
KEY_SIZE="${KEY_SIZE:-4096}"
VENV="${VENV:-/opt/urs/venv}"                         # certipy + ldap3 isoliert
CERTS_DIR="${CERTS_DIR:-$HOME/netbuddy/docker/certs}"
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/netbuddy/docker}"
PFX_PASS="${PFX_PASS:-}"                               # certipy-PFX ist standardmäßig ohne Passwort

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mFEHLER: %s\033[0m\n' "$*" >&2; exit 1; }

[ -r "$ADPW_FILE" ] || sudo test -r "$ADPW_FILE" || die "AD-Passwortdatei fehlt/nicht lesbar: $ADPW_FILE (siehe Kopf des Skripts)"
ADPW="$(cat "$ADPW_FILE" 2>/dev/null || sudo cat "$ADPW_FILE")"
[ -n "$ADPW" ] || die "AD-Passwort ist leer"
BASE_DN="$(echo "$DOMAIN" | sed 's/^/DC=/; s/\./,DC=/g')"   # bls.local -> DC=bls,DC=local

# --- certipy + ldap3 bereitstellen (isoliertes venv) -----------------------------------------
if [ ! -x "$VENV/bin/certipy" ]; then
  log "Installiere certipy-ad + ldap3 nach $VENV"
  sudo install -d -m 755 "$(dirname "$VENV")"
  sudo python3 -m venv "$VENV"
  sudo "$VENV/bin/pip" install -q --upgrade pip certipy-ad ldap3
fi
CERTIPY="$VENV/bin/certipy"
PY="$VENV/bin/python"

WORK="$(mktemp -d)"
cleanup() {
  # Schritt 6: alle Schlüssel-/Credential-Kopien sicher vernichten.
  find "$WORK" -type f -exec shred -u {} + 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT
cd "$WORK"

# --- 2) Zertifikat anfordern (host-network nicht nötig: VM ist im DC-Subnetz) -----------------
log "certipy req für $FQDN (CA=$CA, Template=$TEMPLATE, RSA-$KEY_SIZE)"
"$CERTIPY" req -u "$ENROLL_USER" -p "$ADPW" \
  -dc-ip "$DC_IP" -ns "$DC_IP" \
  -target "$CA_HOST" -ca "$CA" -template "$TEMPLATE" \
  -key-size "$KEY_SIZE" -subject "CN=$FQDN" -dns "$FQDN" \
  -out host
[ -f host.pfx ] || die "certipy lieferte keine host.pfx (Template/Rechte/DC prüfen)"

# --- 3) PFX → PEM (Leaf + Key); openssl 3 ggf. -legacy --------------------------------------
log "PFX → PEM (Leaf-Cert + privater Schlüssel)"
_p12() { openssl pkcs12 -in host.pfx -passin pass:"$PFX_PASS" "$@" 2>/dev/null \
      || openssl pkcs12 -in host.pfx -passin pass:"$PFX_PASS" -legacy "$@"; }
_p12 -nokeys -clcerts -out leaf.crt
_p12 -nocerts -nodes  -out app.key
chmod 600 app.key
[ -s leaf.crt ] && [ -s app.key ] || die "PFX-Aufteilung fehlgeschlagen"

# --- 4) CA-Kette aus AD via LDAPS-Simple-Bind (HTTP-AIA war 404) -----------------------------
log "CA-Kette aus AD ziehen (LDAPS $DC_IP:636, Simple-Bind)"
ADPW="$ADPW" "$PY" - "$DC_IP" "$ENROLL_USER" "$BASE_DN" <<'PYEOF'
import os, ssl, sys
from ldap3 import Server, Connection, Tls, SUBTREE
dc, user, base = sys.argv[1], sys.argv[2], sys.argv[3]
tls = Tls(validate=ssl.CERT_NONE)  # interner DC, Self-/CA-Cert ok
srv = Server(dc, port=636, use_ssl=True, tls=tls)
conn = Connection(srv, user=user, password=os.environ["ADPW"],
                  authentication="SIMPLE", auto_bind=True)
# Ausstellende CAs (Intermediate) unter AIA, Roots unter Certification Authorities.
targets = {
    "intermediate": f"CN=AIA,CN=Public Key Services,CN=Services,CN=Configuration,{base}",
    "root":         f"CN=Certification Authorities,CN=Public Key Services,CN=Services,CN=Configuration,{base}",
}
import base64
def write_pem(der, path):
    b = base64.encodebytes(der).decode()
    open(path, "w").write("-----BEGIN CERTIFICATE-----\n" + b + "-----END CERTIFICATE-----\n")
for name, dn in targets.items():
    conn.search(dn, "(objectClass=certificationAuthority)",
                search_scope=SUBTREE, attributes=["cACertificate"])
    certs = []
    for e in conn.entries:
        vals = e.cACertificate.values if "cACertificate" in e else []
        certs += [v for v in vals if v]
    for i, der in enumerate(certs):
        write_pem(der, f"{name}{'' if i == 0 else i}.crt")
    print(f"{name}: {len(certs)} Zertifikat(e)")
PYEOF
[ -s intermediate.crt ] || die "Kein Intermediate-Cert aus AD erhalten (LDAP-Base/Rechte prüfen)"
[ -s root.crt ] || die "Kein Root-Cert aus AD erhalten"

# --- 5) Fullchain (Leaf + Intermediate) + Verifikation --------------------------------------
log "Fullchain zusammensetzen + verifizieren"
cat leaf.crt intermediate.crt > fullchain.crt
openssl verify -CAfile root.crt -untrusted intermediate.crt leaf.crt \
  || die "openssl verify fehlgeschlagen — Kette stimmt nicht"
openssl x509 -in leaf.crt -noout -subject -ext subjectAltName

# --- 6) Einbauen + Frontend neu starten ------------------------------------------------------
log "Einbauen nach $CERTS_DIR und nginx neu starten"
install -d -m 755 "$CERTS_DIR"
install -m 644 fullchain.crt "$CERTS_DIR/netbuddy.crt"
install -m 600 app.key       "$CERTS_DIR/netbuddy.key"
install -m 644 root.crt      "$CERTS_DIR/ca-root.crt"   # zur Info / Client-Verteilung
( cd "$COMPOSE_DIR" && docker compose -f docker-compose.prod.yml --env-file .env.prod restart frontend )

log "FERTIG — https://$FQDN/ sollte jetzt mit gültigem Zertifikat laufen."
echo "Verifikation von außen:  curl -v https://$FQDN/health"
