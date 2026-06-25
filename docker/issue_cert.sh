#!/usr/bin/env bash
# NetBuddy — TLS-Zertifikat von der AD-CS holen und in den nginx-Frontend-Container einbauen.
#
# Dünner Wrapper um das generische ../tools/issue_cert.sh: setzt die netbuddy-Zielpfade
# (docker/certs/netbuddy.{crt,key}) + Frontend-Restart. Methode/Details + Voraussetzungen
# (AD-Passwort root-only in /opt/urs/secrets/adpw, Kerberos, LDAPS-Kette) siehe tools/issue_cert.sh.
#
# Aufruf (auf der Prod-VM, im Subnetz des DC):  ./issue_cert.sh [FQDN]
set -euo pipefail

FQDN="${1:-bls-srv-netbuddy.bls.local}"
HERE="$(cd "$(dirname "$0")" && pwd)"
GENERIC="$HERE/../tools/issue_cert.sh"
[ -x "$GENERIC" ] || GENERIC="$HERE/issue_cert-generic.sh"   # Fallback, falls nur docker/ deployt
[ -x "$GENERIC" ] || { echo "FEHLER: tools/issue_cert.sh nicht gefunden" >&2; exit 1; }

CERTS="$HERE/certs"

INSTALL_CRT="$CERTS/netbuddy.crt" \
INSTALL_KEY="$CERTS/netbuddy.key" \
RESTART_CMD="cd '$HERE' && docker compose -f docker-compose.prod.yml --env-file .env.prod restart frontend" \
  "$GENERIC" "$FQDN" "$CERTS/_issued"

# Root-CA fürs Client-Rollout zusätzlich ablegen (best effort).
cp -f "$CERTS/_issued/$FQDN-root.crt" "$CERTS/ca-root.crt" 2>/dev/null || true

echo
echo "FERTIG — https://$FQDN/ läuft mit CA-Zertifikat. Verifikation:"
echo "  curl --cacert $CERTS/ca-root.crt https://$FQDN/health"
