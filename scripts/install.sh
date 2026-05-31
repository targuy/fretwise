#!/usr/bin/env bash
#
# install.sh — Install FretWise on macOS / Linux (Ubuntu, Jetson Orin, Synology, containers).
#
# Ensures pixi is available, hardens the project if it lives on a non-native
# filesystem (exFAT/NTFS/network — see scripts/pixi notes), then installs the
# locked pixi environment for the current platform.
#
# Usage:
#   scripts/install.sh [--dev] [--no-lock]
#     --dev       Also install the 'dev' environment (pytest, ruff, mypy).
#     --no-lock   Allow pixi to update the lock file if needed (default: --locked).
#
set -euo pipefail

DEV=0
LOCK_FLAG="--locked"
for a in "$@"; do
  case "$a" in
    --dev)     DEV=1 ;;
    --no-lock) LOCK_FLAG="" ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown option '$a'" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

OS="$(uname -s)"; ARCH="$(uname -m)"
echo "==> FretWise install — OS=$OS ARCH=$ARCH"
echo "    project: $ROOT"

# ---- 1. ensure pixi -------------------------------------------------------
if ! command -v pixi >/dev/null 2>&1; then
  if [ -x "$HOME/.pixi/bin/pixi" ]; then
    export PATH="$HOME/.pixi/bin:$PATH"
  else
    echo "==> pixi not found — installing from https://pixi.sh"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL https://pixi.sh/install.sh | bash
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://pixi.sh/install.sh | bash
    else
      echo "error: need curl or wget to install pixi" >&2; exit 1
    fi
    export PATH="$HOME/.pixi/bin:$PATH"
  fi
fi
command -v pixi >/dev/null 2>&1 || {
  echo "error: pixi still not on PATH — open a new shell or add ~/.pixi/bin to PATH" >&2; exit 1; }
echo "    pixi $(pixi --version)"

# ---- 2. non-native filesystem hardening (macOS exFAT/NTFS/network) --------
if [ "$OS" = "Darwin" ]; then
  MP="$(df -P "$ROOT" | awk 'NR==2{print $NF}')"
  FS="$(mount | grep -E " on ${MP} " | sed -E 's/.*\(([^,)]+).*/\1/' | head -n1)"
  case "$FS" in
    exfat|msdos|ntfs|smbfs|nfs|cifs|fat|vfat|fuse*)
      echo "==> Non-native filesystem ($FS) — hardening pixi & git"
      find "$ROOT" \( -name '._*' -o -name '.DS_Store' \) -type f -delete 2>/dev/null || true
      [ -d "$ROOT/.git" ] && find "$ROOT/.git" -name '._*' -type f -delete 2>/dev/null || true
      pixi config set --local detached-environments true >/dev/null 2>&1 || true
      rm -rf "$ROOT/.pixi/envs" 2>/dev/null || true
      ;;
  esac
fi

# ---- 3. install environment(s) --------------------------------------------
echo "==> pixi install (default) $LOCK_FLAG"
COPYFILE_DISABLE=1 pixi install $LOCK_FLAG -e default
if [ "$DEV" -eq 1 ]; then
  echo "==> pixi install (dev) $LOCK_FLAG"
  COPYFILE_DISABLE=1 pixi install $LOCK_FLAG -e dev
fi

echo "==> Done. Launch with:  scripts/run.sh        (web UI on http://localhost:8080)"
echo "                  or:   scripts/run.sh solve song.gp5   (CLI)"
