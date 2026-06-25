#!/usr/bin/env bash
# issue_cert.sh — TLS-Zertifikat von einer Windows AD-CS (Enterprise-CA) per Linux holen.
#
# Generische, wiederverwendbare Variante (nicht netbuddy-spezifisch).
# Erprobt gegen die BLS-PKI (24./25.6.2026, bls-srv-netbuddy):
#   - CA bietet nur RPC-Enrollment → Ausstellung via `certipy` statt CSR/Web-Enrollment.
#   - NTLM ist in der Umgebung deaktiviert (MD4) → certipy MUSS über Kerberos laufen:
#     wir holen erst ein TGT (getTGT.py) und rufen `certipy req -k` mit Ticket.
#   - CA-Kette kommt aus AD via LDAPS-Simple-Bind (HTTP-AIA war 404). Die Kette wird per
#     Issuer-Walking gebaut (Multi-Tier-PKI: leaf → Sub-CA(s) → Root), nicht hart verdrahtet.
#
# Aufruf:   issue_cert.sh <FQDN> [OUTDIR]
# Beispiel: issue_cert.sh bls-srv-netbuddy.bls.local ~/certs
#
# Ausgabe in OUTDIR (Default: ./<fqdn>/):
#   <fqdn>.crt        Fullchain (Leaf + alle Sub-CAs, ohne Root) — nginx/Apache `ssl_certificate`
#   <fqdn>.key        privater Schlüssel                          — `ssl_certificate_key`
#   <fqdn>-root.crt   Root-CA (zur Info / Client-Verteilung)
#
# Voraussetzungen:
#   - Linux-Host MIT Routing zum DC (Kerberos 88 + LDAPS 636) und zur CA (RPC). WSL erreicht
#     das interne Netz i.d.R. nur über VPN — sonst auf einer VM im DC-Subnetz laufen lassen.
#   - AD-Passwort root-only in $ADPW_FILE (NICHT in Chat/Repo/History). Wegen Sonderzeichen
#     ($ etc.) per Prompt ablegen, nie inline:
#       ssh -t <host> 'sudo install -d -m700 /opt/urs/secrets; read -rsp "AD-PW: " P; \
#         printf "%s" "$P" | sudo tee /opt/urs/secrets/adpw >/dev/null; sudo chmod 600 /opt/urs/secrets/adpw; unset P'
#   - python3-venv + openssl vorhanden (certipy[+impacket] & ldap3 werden ins venv gebootstrapt).
set -euo pipefail

FQDN="${1:?Usage: issue_cert.sh <FQDN> [OUTDIR]}"
OUTDIR="${2:-./$FQDN}"

# --- Umgebung (per Env überschreibbar) — Defaults = BLS-Umgebung ----------------------------
DOMAIN="${DOMAIN:-bls.local}"
REALM="${REALM:-$(echo "$DOMAIN" | tr '[:lower:]' '[:upper:]')}"
CA="${CA:-BLS-T1CA}"
CA_HOST="${CA_HOST:-BLS-SRV-T1CA.bls.local}"
TEMPLATE="${TEMPLATE:-BLS-WebServer-RSA4096Linux}"   # verlangt RSA-4096 (sonst 0x80094811)
DC_IP="${DC_IP:-10.120.20.10}"
DC_HOST="${DC_HOST:-BLS-SRV-T0DC10.bls.local}"       # FQDN des DC (für Kerberos)
ENROLL_USER="${ENROLL_USER:-msak}"                   # sAMAccountName (ohne @realm)
ADPW_FILE="${ADPW_FILE:-/opt/urs/secrets/adpw}"
KEY_SIZE="${KEY_SIZE:-4096}"
VENV="${VENV:-$HOME/.local/share/certipy-venv}"      # certipy + ldap3 isoliert
# Optionales Einbauen nach Ausstellung (leer = nur Dateien schreiben):
INSTALL_CRT="${INSTALL_CRT:-}"                        # Zielpfad für Fullchain
INSTALL_KEY="${INSTALL_KEY:-}"                        # Zielpfad für Key
RESTART_CMD="${RESTART_CMD:-}"                        # z.B. "cd ~/netbuddy/docker && docker compose ... restart frontend"

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mFEHLER: %s\033[0m\n' "$*" >&2; exit 1; }

command -v openssl >/dev/null || die "openssl fehlt"
command -v python3 >/dev/null || die "python3 fehlt"
[ -r "$ADPW_FILE" ] || sudo test -r "$ADPW_FILE" || die "AD-Passwortdatei fehlt/nicht lesbar: $ADPW_FILE (siehe Kopf)"
BASE_DN="$(echo "$DOMAIN" | sed 's/^/DC=/; s/\./,DC=/g')"   # bls.local -> DC=bls,DC=local

# --- certipy + ldap3 bereitstellen (isoliertes venv, einmalig) ------------------------------
if [ ! -x "$VENV/bin/certipy" ]; then
  log "Installiere certipy-ad + ldap3 nach $VENV"
  python3 -m venv "$VENV" || die "venv-Erstellung fehlgeschlagen — fehlt python3-venv? (apt install python3-venv)"
  "$VENV/bin/pip" install -q --upgrade pip certipy-ad ldap3
fi
CERTIPY="$VENV/bin/certipy"; PY="$VENV/bin/python"; GETTGT="$VENV/bin/getTGT.py"

# --- krb5.conf (für Kerberos-Auth) ----------------------------------------------------------
KRB5_CONF="$(mktemp)"
cat > "$KRB5_CONF" <<EOF
[libdefaults]
    default_realm = $REALM
    dns_lookup_kdc = false
    dns_lookup_realm = false
    rdns = false
[realms]
    $REALM = { kdc = $DC_IP
        admin_server = $DC_IP }
[domain_realm]
    .$DOMAIN = $REALM
    $DOMAIN = $REALM
EOF
export KRB5_CONFIG="$KRB5_CONF"

WORK="$(mktemp -d)"
cleanup() {
  find "$WORK" -type f -exec shred -u {} + 2>/dev/null || true
  rm -rf "$WORK"; rm -f "$KRB5_CONF"
}
trap cleanup EXIT
cd "$WORK"

# Passwort einmalig laden (für getTGT + LDAPS); bleibt nur in dieser Shell.
ADPW="$(cat "$ADPW_FILE" 2>/dev/null || sudo cat "$ADPW_FILE")"
[ -n "$ADPW" ] || die "AD-Passwort ist leer"
export CCACHE="$WORK/krb.ccache"

# --- 1) Kerberos-TGT holen (NTLM ist deaktiviert) -------------------------------------------
log "Kerberos-TGT für $ENROLL_USER@$REALM holen"
ADPW="$ADPW" KRB5CCNAME="$CCACHE" "$PY" -c "
import os, subprocess, sys
subprocess.run([sys.executable, '$GETTGT',
    '$DOMAIN/$ENROLL_USER:'+os.environ['ADPW'], '-dc-ip', '$DC_IP'],
    cwd='$WORK', check=True)
" || die "getTGT fehlgeschlagen (Passwort? Uhrzeit-Skew zum DC?)"
mv -f "$WORK/$ENROLL_USER.ccache" "$CCACHE" 2>/dev/null || true
[ -s "$CCACHE" ] || die "kein TGT-Cache erzeugt"

# --- 2) Zertifikat anfordern (certipy via Kerberos) -----------------------------------------
log "certipy req für $FQDN (CA=$CA, Template=$TEMPLATE, RSA-$KEY_SIZE, Kerberos)"
KRB5CCNAME="$CCACHE" "$CERTIPY" req -k -no-pass \
  -dc-ip "$DC_IP" -dc-host "$DC_HOST" -ns "$DC_IP" \
  -target "$CA_HOST" -ca "$CA" -template "$TEMPLATE" \
  -key-size "$KEY_SIZE" -subject "CN=$FQDN" -dns "$FQDN" \
  -out cert 2>&1 | tee certipy.log
# certipy ersetzt '/' im -out durch '_'; PFX robust finden.
PFX="$(ls -1t "$WORK"/*.pfx 2>/dev/null | head -1)"
[ -n "$PFX" ] && [ -f "$PFX" ] || die "certipy lieferte keine PFX (Rechte/Template/DC prüfen, s. certipy.log)"

# --- 3) PFX → PEM (Leaf + Key); openssl 3 ggf. -legacy --------------------------------------
log "PFX → PEM (Leaf-Cert + privater Schlüssel)"
_p12() { openssl pkcs12 -in "$PFX" -passin pass: "$@" 2>/dev/null \
      || openssl pkcs12 -in "$PFX" -passin pass: -legacy "$@"; }
_p12 -nokeys -clcerts -out leaf.crt
_p12 -nocerts -nodes  -out app.key
chmod 600 app.key
[ -s leaf.crt ] && [ -s app.key ] || die "PFX-Aufteilung fehlgeschlagen"
# Cert/Key-Konsistenz
[ "$(openssl x509 -in leaf.crt -noout -modulus | openssl md5)" = \
  "$(openssl rsa -in app.key -noout -modulus 2>/dev/null | openssl md5)" ] \
  || die "Key passt nicht zum Cert"

# --- 4) CA-Pool aus AD ziehen (LDAPS) + Kette per Issuer-Walking bauen -----------------------
log "CA-Kette aus AD ziehen (LDAPS $DC_IP:636) + per Issuer ordnen"
cat > build_chain.py <<'PYEOF'
import base64, os, ssl, subprocess, sys
from ldap3 import Connection, Server, SUBTREE, Tls

dc, base, leaf_path, work = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
pw = os.environ["ADPW"]
srv = Server(dc, port=636, use_ssl=True, tls=Tls(validate=ssl.CERT_NONE))
conn = Connection(srv, user=os.environ["BINDUSER"], password=pw,
                  authentication="SIMPLE", auto_bind=True)
containers = [
    f"CN=AIA,CN=Public Key Services,CN=Services,CN=Configuration,{base}",
    f"CN=Certification Authorities,CN=Public Key Services,CN=Services,CN=Configuration,{base}",
]
pool = []  # alle bekannten CA-Zertifikate als DER
for dn in containers:
    conn.search(dn, "(objectClass=certificationAuthority)", search_scope=SUBTREE,
                attributes=["cACertificate"])
    for e in conn.entries:
        if "cACertificate" in e:
            pool += [bytes(v) for v in e.cACertificate.values if v]

def run(args, stdin=None):
    return subprocess.run(args, input=stdin, capture_output=True).stdout

def field(der, which):  # which = -subject | -issuer
    pem = b"-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(der) + b"-----END CERTIFICATE-----\n"
    return run(["openssl", "x509", "-noout", which, "-nameopt", "RFC2253"], pem).decode().split("=", 1)[1].strip()

# Index: subject -> DER
by_subject = {}
for der in pool:
    by_subject.setdefault(field(der, "-subject"), der)

leaf_pem = open(leaf_path, "rb").read()
leaf_issuer = run(["openssl", "x509", "-noout", "-issuer", "-nameopt", "RFC2253"], leaf_pem).decode().split("=", 1)[1].strip()

chain, root = [], None
cur = leaf_issuer
seen = set()
while cur in by_subject and cur not in seen:
    seen.add(cur)
    der = by_subject[cur]
    issuer = field(der, "-issuer")
    if issuer == cur:        # self-signed → Root
        root = der
        break
    chain.append(der)        # Sub-CA → in die Fullchain
    cur = issuer

def write_pem(der, path):
    open(path, "wb").write(b"-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(der) + b"-----END CERTIFICATE-----\n")

for i, der in enumerate(chain):
    write_pem(der, os.path.join(work, f"sub_{i}.crt"))
if root is not None:
    write_pem(root, os.path.join(work, "root.crt"))
print(f"sub-CAs: {len(chain)}, root: {'ja' if root else 'NEIN'}")
PYEOF
ADPW="$ADPW" BINDUSER="$ENROLL_USER@$DOMAIN" "$PY" build_chain.py "$DC_IP" "$BASE_DN" "$WORK/leaf.crt" "$WORK" \
  || die "Kettenaufbau via LDAPS fehlgeschlagen"
ls sub_0.crt >/dev/null 2>&1 || die "keine Sub-CA gefunden (Issuer der Leaf nicht im AD-Pool)"

# --- 5) Fullchain + Verifikation ------------------------------------------------------------
log "Fullchain zusammensetzen + verifizieren"
cat leaf.crt sub_*.crt > fullchain.crt
if [ -s root.crt ]; then
  openssl verify -CAfile root.crt $(for s in sub_*.crt; do echo -n "-untrusted $s "; done) leaf.crt \
    || die "openssl verify fehlgeschlagen — Kette stimmt nicht"
else
  printf '\033[1;33mWARN: keine Root im AD-Pool gefunden — Fullchain ungeprüft.\033[0m\n'
fi
openssl x509 -in leaf.crt -noout -subject -issuer -ext subjectAltName

# --- 6) Dateien schreiben -------------------------------------------------------------------
mkdir -p "$OUTDIR"
install -m 644 fullchain.crt "$OUTDIR/$FQDN.crt"
install -m 600 app.key       "$OUTDIR/$FQDN.key"
[ -s root.crt ] && install -m 644 root.crt "$OUTDIR/$FQDN-root.crt"
log "Geschrieben nach $OUTDIR/: $FQDN.crt (fullchain), $FQDN.key$([ -s root.crt ] && echo ", $FQDN-root.crt")"

# --- 7) Optionales Einbauen + Restart -------------------------------------------------------
if [ -n "$INSTALL_CRT" ] && [ -n "$INSTALL_KEY" ]; then
  log "Einbauen → $INSTALL_CRT / $INSTALL_KEY"
  install -m 644 "$OUTDIR/$FQDN.crt" "$INSTALL_CRT"
  install -m 600 "$OUTDIR/$FQDN.key" "$INSTALL_KEY"
  [ -n "$RESTART_CMD" ] && { log "Restart: $RESTART_CMD"; bash -c "$RESTART_CMD"; }
fi

log "FERTIG — Cert für $FQDN bereit."
