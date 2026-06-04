#!/usr/bin/env bash
#
# run_local.sh — Run FretWise in SINGLE-USER mode against the local library.
#
# Unlike run.sh (which loads .env and enables multi-user Google OIDC, so the UI
# shows each logged-in user's OWN Google Drive), this launcher forces
# single-user mode with NO login and serves the on-disk `partitions/` library
# directly. Use it to test/preview locally without a Google Drive round-trip.
#
# Examples:
#   scripts/run_local.sh                       # web UI on http://localhost:8080
#   PORT=8800 scripts/run_local.sh             # pick a port
#   PARTITIONS=/path/to/scores scripts/run_local.sh   # point at another folder
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

command -v pixi >/dev/null 2>&1 || export PATH="$HOME/.pixi/bin:$PATH"
command -v pixi >/dev/null 2>&1 || {
  echo "error: pixi not found — run scripts/install.sh first" >&2; exit 1; }

# Force single-user: do NOT source .env, and clear any auth/OIDC vars that may
# already live in the shell so create_app() stays in single-user mode.
unset FRETWISE_AUTH_ENABLED \
      FRETWISE_GOOGLE_CLIENT_ID FRETWISE_GOOGLE_CLIENT_SECRET \
      FRETWISE_OIDC_CLIENT_ID FRETWISE_OIDC_CLIENT_SECRET FRETWISE_OIDC_ISSUER \
      FRETWISE_OIDC_NAME FRETWISE_SECRET_KEY FRETWISE_BASE_URL 2>/dev/null || true

HOST="${HOST:-localhost}"
PORT="${PORT:-8080}"
PARTITIONS="${PARTITIONS:-$ROOT/partitions}"

if [ ! -d "$PARTITIONS" ]; then
  echo "error: partitions dir not found: $PARTITIONS" >&2; exit 1; fi

echo "==> FretWise (SINGLE-USER, no login)"
echo "    library : $PARTITIONS"
echo "    url     : http://${HOST}:${PORT}   (Ctrl+C to stop)"
exec env COPYFILE_DISABLE=1 FRETWISE_PARTITIONS_DIR="$PARTITIONS" \
  pixi run fretwise web --host "$HOST" --port "$PORT" --dir "$PARTITIONS"
