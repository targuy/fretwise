#!/usr/bin/env bash
#
# run.sh — Run FretWise on macOS / Linux (Ubuntu, Jetson Orin, Synology, containers).
#
# No arguments  -> launches the web UI (http://localhost:8080).
# With arguments -> passes them to the `fretwise` CLI.
#
# Examples:
#   scripts/run.sh                          # web UI on localhost:8080
#   HOST=0.0.0.0 PORT=9090 scripts/run.sh   # web UI reachable on the network
#   scripts/run.sh solve song.gp5 --mode performance
#   scripts/run.sh parse song.gp5
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

command -v pixi >/dev/null 2>&1 || export PATH="$HOME/.pixi/bin:$PATH"
command -v pixi >/dev/null 2>&1 || {
  echo "error: pixi not found — run scripts/install.sh first" >&2; exit 1; }

# Auto-load multi-user / OIDC config from .env if present (see .env.example).
if [ -f "$ROOT/.env" ]; then
  echo "==> Loading .env (multi-user config)"
  set -a; . "$ROOT/.env"; set +a
fi

if [ "$#" -eq 0 ]; then
  HOST="${HOST:-localhost}"; PORT="${PORT:-8080}"
  echo "==> FretWise web UI -> http://${HOST}:${PORT}   (Ctrl+C to stop)"
  exec env COPYFILE_DISABLE=1 pixi run fretwise web --host "$HOST" --port "$PORT"
else
  exec env COPYFILE_DISABLE=1 pixi run fretwise "$@"
fi
