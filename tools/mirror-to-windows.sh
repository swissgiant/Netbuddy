#!/usr/bin/env bash
# Spiegelt die Windows-/PowerShell-Artefakte des Repos nach E:\DEV\netbuddy (WSL: /mnt/e/DEV/netbuddy),
# damit Alex sie direkt unter Windows (PowerShell, Microsoft.Graph etc.) ausführen kann.
# Erhält die Repo-Verzeichnisstruktur. Aufruf aus dem Repo-Root:  ./tools/mirror-to-windows.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${DEST:-/mnt/e/DEV/netbuddy}"

[ -d "$(dirname "$DEST")" ] || { echo "Ziel-Laufwerk nicht gemountet: $(dirname "$DEST")" >&2; exit 1; }
mkdir -p "$DEST"

cd "$REPO"
# Alle PowerShell-Skripte, Struktur erhalten; .venv/node_modules/.git ausgeschlossen.
rsync -am \
  --exclude '.venv' --exclude 'node_modules' --exclude '.git' \
  --include '*/' --include '*.ps1' --exclude '*' \
  ./ "$DEST/"

# Begleit-Doku für die Windows-Schritte.
mkdir -p "$DEST/docs"
cp -f docs/sso.md "$DEST/docs/sso.md" 2>/dev/null || true

echo "Gespiegelt nach $DEST:"
find "$DEST" -type f -printf '  %P\n' | sort
