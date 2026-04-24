#!/usr/bin/env bash
# Nexus one-command setup / upgrade.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/llores28/Nexus/main/setup.sh | bash
#   # or, from a local clone:
#   ./setup.sh
#
# Creates a project-local .venv, installs (or upgrades) Nexus into it, then
# runs `nexus init` to scaffold the current project with a guided wizard.

set -euo pipefail

NEXUS_REPO="https://github.com/llores28/Nexus.git"
PROJECT_DIR="$(pwd)"

info() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
warn() { printf "\n\033[1;33m!!  %s\033[0m\n" "$*"; }
err()  { printf "\n\033[1;31mXX  %s\033[0m\n" "$*" >&2; }

# --- 1. Check Python ---
info "Checking Python 3.10+"
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
    case "$ver" in
      3.1[0-9]|3.[2-9][0-9]|[4-9].*) PY="$candidate"; break ;;
    esac
  fi
done

if [ -z "$PY" ]; then
  err "Python 3.10+ not found. Install from https://www.python.org/downloads/ and re-run."
  exit 1
fi
echo "   using: $PY ($($PY --version))"

# --- 2. Detect mode: local-clone vs target-project ---
MODE="target"
if [ -f "$PROJECT_DIR/pyproject.toml" ] && grep -q 'name = "nexus-bootstrap"' "$PROJECT_DIR/pyproject.toml" 2>/dev/null; then
  MODE="clone"
fi
info "Mode: $MODE"

# --- 3. Create / reuse .venv ---
VENV="$PROJECT_DIR/.venv"
if [ -d "$VENV" ]; then
  info "Reusing existing .venv"
else
  info "Creating .venv"
  "$PY" -m venv "$VENV"
fi

# Activate
if [ -f "$VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "$VENV/bin/activate"
elif [ -f "$VENV/Scripts/activate" ]; then
  # Git Bash on Windows
  # shellcheck disable=SC1091
  . "$VENV/Scripts/activate"
else
  err "Could not find venv activate script in $VENV"
  exit 1
fi

# --- 4. Install / upgrade Nexus ---
info "Upgrading pip"
python -m pip install --quiet --upgrade pip

if [ "$MODE" = "clone" ]; then
  info "Installing Nexus (editable) from local clone"
  python -m pip install --quiet -e .
else
  info "Installing / upgrading Nexus from $NEXUS_REPO"
  python -m pip install --quiet --upgrade "git+${NEXUS_REPO}"
fi

# --- 5. Run nexus init (auto-detect upgrade) ---
UPGRADE_FLAG=""
if [ -f "$PROJECT_DIR/.nexus/state.json" ]; then
  UPGRADE_FLAG="--upgrade"
  info "Existing .nexus/ detected — running upgrade"
fi

# shellcheck disable=SC2086
nexus init --project-dir "$PROJECT_DIR" $UPGRADE_FLAG

# --- 6. Done ---
info "Setup complete."
echo "   Activate the venv in future sessions:"
if [ -f "$VENV/Scripts/activate" ]; then
  echo "     Git Bash:    . .venv/Scripts/activate"
  echo "     PowerShell:  & .venv\\Scripts\\Activate.ps1"
  echo "     cmd.exe:     .venv\\Scripts\\activate.bat"
else
  echo "     . .venv/bin/activate"
fi
echo ""
