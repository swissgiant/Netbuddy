#!/usr/bin/env bash
# Erzeugt ein selbstsigniertes TLS-Zertifikat für den nginx-Reverse-Proxy.
# Aufruf:  ./gen-selfsigned-cert.sh netbuddy.intern   (oder die VM-IP)
# Für eine interne CA / echtes Zertifikat die Dateien in ./certs einfach ersetzen.
set -euo pipefail

CN="${1:-netbuddy.local}"
DIR="$(dirname "$0")/certs"
mkdir -p "$DIR"

openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout "$DIR/netbuddy.key" -out "$DIR/netbuddy.crt" \
  -subj "/CN=${CN}" \
  -addext "subjectAltName=DNS:${CN},IP:${CN}" 2>/dev/null || \
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout "$DIR/netbuddy.key" -out "$DIR/netbuddy.crt" \
  -subj "/CN=${CN}"  # Fallback ohne SAN, falls CN keine IP ist

echo "Zertifikat erzeugt: $DIR/netbuddy.crt (CN=${CN})"
echo "Browser zeigt eine Warnung (self-signed) — fürs interne Tool ok, oder echtes Cert hinterlegen."
