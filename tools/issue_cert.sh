#!/usr/bin/env bash
# issue_cert.sh — TLS-Zertifikat von einer Windows AD-CS (Enterprise-CA) per Linux holen.
#
# Generische, wiederverwendbare Variante (nicht netbuddy-spezifisch).
# Methode (erprobt auf bls-srv-vapp2, Runbook /opt/urs/CERT_RUNBOOK.md dort):
# die CA bietet nur RPC-Enrollment → Ausstellung via `certipy` statt CSR/Web-Enrollment.
# Holt das Cert, baut die CA-Kette aus AD (LDAPS), schreibt PEM-Dateien. Optionales Einbauen
# in einen Cert-Pfad + Service-Restart per Env.
#
# Aufruf:   issue_cert.sh <FQDN> [OUTDIR]
# Beispiel: issue_cert.sh bls-srv-netbuddy.bls.local ~/certs
#
# Ausgabe in OUTDIR (Default: ./<fqdn>/):
#   <fqdn>.crt        Fullchain (Leaf + Intermediate) — für nginx/Apache `ssl_certificate`
#   <fqdn>.key        privater Schlüssel              — `ssl_certificate_key`
#   <fqdn>-root.crt   CA-Root (zur Info / Client-Verteilung)
#
# Voraussetzungen:
#   - Linux-Host MIT Routing zum DC (LDAPS 636) und zur CA (RPC). WSL erreicht das interne
#     Netz i.d.R. nur über VPN/Routing — sonst auf einer VM im DC-Subnetz laufen lassen.
#   - AD-Passwort root-only in $ADPW_FILE ablegen (NICHT in Chat/Repo/History):
#       sudo install -d -m700 /opt/urs/secrets
#       printf '%s' 'AD-PW' | sudo tee /opt/urs/secrets/adpw >/dev/null && sudo chmod 600 /opt/urs/secrets/adpw
#   - python3 + openssl vorhanden (certipy & ldap3 werden in ein venv gebootstrapt).
set -euo pipefail

FQDN="${1:?Usage: issue_cert.sh <FQDN> [OUTDIR]}"
OUTDIR="${2:-./$FQDN}"

# --- Umgebung (per Env überschreibbar) — Defaults = BLS-Umgebung ----------------------------
DOMAIN="${DOMAIN:-bls.local}"
CA="${CA:-BLS-T1CA}"
CA_HOST="${CA_HOST:-BLS-SRV-T1CA.bls.local}"
TEMPLATE="${TEMPLATE:-BLS-WebServer-RSA4096Linux}"   # verlangt RSA-4096 (sonst 0x80094811)
DC_IP="${DC_IP:-10.120.20.10}"
ENROLL_USER="${ENROLL_USER:-msak@bls.local}"
ADPW_FILE="${ADPW_FILE:-/opt/urs/secrets/adpw}"
KEY_SIZE="${KEY_SIZE:-4096}"
VENV="${VENV:-$HOME/.local/share/certipy-venv}"      # certipy + ldap3 isoliert
PFX_PASS="${PFX_PASS:-}"                              # certipy-PFX standardmäßig ohne Passwort
# Optionales Einbauen nach Ausstellung (leer = nur Dateien schreiben):
INSTALL_CRT="${INSTALL_CRT:-}"                        # Zielpfad für Fullchain
INSTALL_KEY="${INSTALL_KEY:-}"                        # Zielpfad für Key
RESTART_CMD="${RESTART_CMD:-}"                        # z.B. "cd ~/netbuddy/docker && docker compose ... restart frontend"

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mFEHLER: %s\033[0m\n' "$*" >&2; exit 1; }

command -v openssl >/dev/null || die "openssl fehlt"
command -v python3 >/dev/null || die "python3 fehlt"
[ -r "$ADPW_FILE" ] || sudo test -r "$ADPW_FILE" || die "AD-Passwortdatei fehlt/nicht lesbar: $ADPW_FILE (siehe Kopf)"
ADPW="$(cat "$ADPW_FILE" 2>/dev/null || sudo cat "$ADPW_FILE")"
[ -n "$ADPW" ] || die "AD-Passwort ist leer"
BASE_DN="$(echo "$DOMAIN" | sed 's/^/DC=/; s/\./,DC=/g')"   # bls.local -> DC=bls,DC=local

# --- certipy + ldap3 bereitstellen (isoliertes venv, einmalig) ------------------------------
if [ ! -x "$VENV/bin/certipy" ]; then
  log "Installiere certipy-ad + ldap3 nach $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip certipy-ad ldap3
fi
CERTIPY="$VENV/bin/certipy"
PY="$VENV/bin/python"

WORK="$(mktemp -d)"
cleanup() { find "$WORK" -type f -exec shred -u {} + 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
cd "$WORK"

# --- 1) Zertifikat anfordern (certipy RPC-Enrollment) ---------------------------------------
log "certipy req für $FQDN (CA=$CA, Template=$TEMPLATE, RSA-$KEY_SIZE)"
"$CERTIPY" req -u "$ENROLL_USER" -p "$ADPW" \
  -dc-ip "$DC_IP" -ns "$DC_IP" \
  -target "$CA_HOST" -ca "$CA" -template "$TEMPLATE" \
  -key-size "$KEY_SIZE" -subject "CN=$FQDN" -dns "$FQDN" \
  -out host
[ -f host.pfx ] || die "certipy lieferte keine host.pfx (Template/Rechte/DC prüfen)"

# --- 2) PFX → PEM (Leaf + Key); openssl 3 ggf. -legacy --------------------------------------
log "PFX → PEM (Leaf-Cert + privater Schlüssel)"
_p12() { openssl pkcs12 -in host.pfx -passin pass:"$PFX_PASS" "$@" 2>/dev/null \
      || openssl pkcs12 -in host.pfx -passin pass:"$PFX_PASS" -legacy "$@"; }
_p12 -nokeys -clcerts -out leaf.crt
_p12 -nocerts -nodes  -out app.key
chmod 600 app.key
[ -s leaf.crt ] && [ -s app.key ] || die "PFX-Aufteilung fehlgeschlagen"

# --- 3) CA-Kette aus AD via LDAPS-Simple-Bind -----------------------------------------------
log "CA-Kette aus AD ziehen (LDAPS $DC_IP:636, Simple-Bind)"
ADPW="$ADPW" "$PY" - "$DC_IP" "$ENROLL_USER" "$BASE_DN" <<'PYEOF'
import os, ssl, sys, base64
from ldap3 import Server, Connection, Tls, SUBTREE
dc, user, base = sys.argv[1], sys.argv[2], sys.argv[3]
srv = Server(dc, port=636, use_ssl=True, tls=Tls(validate=ssl.CERT_NONE))
conn = Connection(srv, user=user, password=os.environ["ADPW"],
                  authentication="SIMPLE", auto_bind=True)
targets = {
    "intermediate": f"CN=AIA,CN=Public Key Services,CN=Services,CN=Configuration,{base}",
    "root":         f"CN=Certification Authorities,CN=Public Key Services,CN=Services,CN=Configuration,{base}",
}
def write_pem(der, path):
    b = base64.encodebytes(der).decode()
    open(path, "w").write("-----BEGIN CERTIFICATE-----\n" + b + "-----END CERTIFICATE-----\n")
for name, dn in targets.items():
    conn.search(dn, "(objectClass=certificationAuthority)", search_scope=SUBTREE,
                attributes=["cACertificate"])
    certs = [v for e in conn.entries if "cACertificate" in e for v in e.cACertificate.values if v]
    for i, der in enumerate(certs):
        write_pem(der, f"{name}{'' if i == 0 else i}.crt")
    print(f"{name}: {len(certs)} Zertifikat(e)")
PYEOF
[ -s intermediate.crt ] || die "Kein Intermediate-Cert aus AD (LDAP-Base/Rechte prüfen)"
[ -s root.crt ] || die "Kein Root-Cert aus AD"

# --- 4) Fullchain + Verifikation ------------------------------------------------------------
log "Fullchain zusammensetzen + verifizieren"
cat leaf.crt intermediate.crt > fullchain.crt
openssl verify -CAfile root.crt -untrusted intermediate.crt leaf.crt \
  || die "openssl verify fehlgeschlagen — Kette stimmt nicht"
openssl x509 -in leaf.crt -noout -subject -ext subjectAltName

# --- 5) Dateien schreiben -------------------------------------------------------------------
mkdir -p "$OUTDIR"
install -m 644 fullchain.crt "$OUTDIR/$FQDN.crt"
install -m 600 app.key       "$OUTDIR/$FQDN.key"
install -m 644 root.crt      "$OUTDIR/$FQDN-root.crt"
log "Geschrieben nach $OUTDIR/: $FQDN.crt (fullchain), $FQDN.key, $FQDN-root.crt"

# --- 6) Optionales Einbauen + Restart -------------------------------------------------------
if [ -n "$INSTALL_CRT" ] && [ -n "$INSTALL_KEY" ]; then
  log "Einbauen → $INSTALL_CRT / $INSTALL_KEY"
  install -m 644 "$OUTDIR/$FQDN.crt" "$INSTALL_CRT"
  install -m 600 "$OUTDIR/$FQDN.key" "$INSTALL_KEY"
  [ -n "$RESTART_CMD" ] && { log "Restart: $RESTART_CMD"; bash -c "$RESTART_CMD"; }
fi

log "FERTIG — Cert für $FQDN bereit."
