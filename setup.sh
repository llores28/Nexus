#!/usr/bin/env bash
# Nexus one-command setup / upgrade.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/llores28/Nexus/main/setup.sh | bash
#   # or, from a local clone:
#   ./setup.sh                  # fresh init OR safe upgrade (auto-detected)
#   ./setup.sh --upgrade-only   # just refresh the Nexus package; skip nexus init
#   ./setup.sh --refresh        # on upgrade, also regenerate BOOTSTRAP.md
#
# Behavior:
#   - Brand-new project (no .nexus/state.json): creates .venv, installs Nexus,
#     runs `nexus init` (interactive 7-question wizard).
#   - Already-bootstrapped project (.nexus/state.json present): creates/reuses
#     .venv, upgrades the Nexus package, runs `nexus init --upgrade` to re-validate
#     git hooks and run the health check. Does NOT re-prompt the wizard.
#     Does NOT overwrite BOOTSTRAP.md unless --refresh is also passed.
#   - --upgrade-only: just install/upgrade the package and exit. Useful for
#     refreshing the tool on a project that doesn't use `nexus init` scaffolding
#     (e.g. you only want the CLI for `nexus journal`).

set -euo pipefail

# --- Guard: detect Windows WSL shim without a real distro ---
# When a user runs `curl ... | bash` from cmd.exe or PowerShell on Windows,
# `bash` resolves to C:\Windows\System32\bash.exe (the WSL relay).
# If no WSL Linux distro is installed, the relay exits with:
#   WSL ERROR: execvpe(/bin/bash) failed: No such file or directory
# We detect this early and print actionable guidance.
if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi 'microsoft' /proc/version 2>/dev/null; then
  : # running inside a real WSL distro — fine, continue
elif uname -s 2>/dev/null | grep -qi 'mingw\|msys\|cygwin'; then
  : # running inside Git Bash / MSYS2 — fine, continue
else
  # Check if we look like a bare WSL relay invocation (no /bin/sh features)
  if [ ! -d /home ] && [ ! -f /etc/os-release ] 2>/dev/null; then
    printf "\n\033[1;31mXX  ERROR: No WSL Linux distro detected.\033[0m\n"
    printf "    You appear to be running 'bash' from cmd.exe or PowerShell on Windows.\n"
    printf "    On Windows, 'bash' resolves to the WSL relay (C:\\Windows\\System32\\bash.exe),\n"
    printf "    which requires an installed WSL distro to work.\n\n"
    printf "    \033[1;32mFix — choose one:\033[0m\n"
    printf "    1) PowerShell (recommended):\n"
    printf "       irm https://raw.githubusercontent.com/llores28/Nexus/main/setup.ps1 | iex\n\n"
    printf "    2) Git Bash (open 'Git Bash' from Start menu, then run):\n"
    printf "       curl -sSL https://raw.githubusercontent.com/llores28/Nexus/main/setup.sh | bash\n\n"
    printf "    3) Install WSL: wsl --install  (then reboot and re-run)\n\n"
    exit 1
  fi
fi

NEXUS_REPO="https://github.com/llores28/Nexus.git"
PROJECT_DIR="$(pwd)"

UPGRADE_ONLY=0
REFRESH=0
for arg in "$@"; do
  case "$arg" in
    --upgrade-only) UPGRADE_ONLY=1 ;;
    --refresh)      REFRESH=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 2
      ;;
  esac
done

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

# --- 1b. Check git (required for pip install git+...) ---
if ! command -v git >/dev/null 2>&1; then
  err "git not found. Install git from https://git-scm.com/ and re-run."
  exit 1
fi
echo "   git: $(git --version)"

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

# --- 4. Detect prior Nexus install (informational) ---
PRIOR_VERSION=""
if python -m pip show nexus-bootstrap >/dev/null 2>&1; then
  PRIOR_VERSION="$(python -m pip show nexus-bootstrap 2>/dev/null | awk '/^Version:/ {print $2}')"
  info "Existing Nexus install detected: nexus-bootstrap ${PRIOR_VERSION}"
else
  info "No existing Nexus install detected (first install in this venv)"
fi

# --- 5. Install / upgrade Nexus ---
info "Upgrading pip"
python -m pip install --quiet --upgrade pip

if [ "$MODE" = "clone" ]; then
  if [ -n "$PRIOR_VERSION" ]; then
    info "Reinstalling Nexus (editable) from local clone"
  else
    info "Installing Nexus (editable) from local clone"
  fi
  python -m pip install --quiet -e .
else
  if [ -n "$PRIOR_VERSION" ]; then
    info "Upgrading Nexus from $NEXUS_REPO"
  else
    info "Installing Nexus from $NEXUS_REPO"
  fi
  python -m pip install --quiet --upgrade "git+${NEXUS_REPO}"
fi

NEW_VERSION="$(python -m pip show nexus-bootstrap 2>/dev/null | awk '/^Version:/ {print $2}')"
if [ -n "$PRIOR_VERSION" ] && [ "$PRIOR_VERSION" != "$NEW_VERSION" ]; then
  echo "   nexus-bootstrap: $PRIOR_VERSION -> $NEW_VERSION"
else
  echo "   nexus-bootstrap: $NEW_VERSION"
fi

# --- 6. --upgrade-only: stop here ---
if [ "$UPGRADE_ONLY" -eq 1 ]; then
  info "Package upgrade complete (--upgrade-only)."
  echo "   Skipping 'nexus init' as requested."
  if [ -f "$VENV/Scripts/activate" ]; then
    echo "   Activate the venv:  . .venv/Scripts/activate"
  else
    echo "   Activate the venv:  . .venv/bin/activate"
  fi
  exit 0
fi

# --- 7. Run nexus init (auto-detect upgrade vs fresh) ---
INIT_FLAGS=()
if [ -f "$PROJECT_DIR/.nexus/state.json" ]; then
  INIT_FLAGS+=(--upgrade)
  if [ "$REFRESH" -eq 1 ]; then
    INIT_FLAGS+=(--refresh)
  fi
  info "Already-bootstrapped project detected (.nexus/state.json present) -- running upgrade"
elif [ "$REFRESH" -eq 1 ]; then
  warn "--refresh has no effect on a fresh init (BOOTSTRAP.md doesn't exist yet). Ignoring."
fi

nexus init --project-dir "$PROJECT_DIR" "${INIT_FLAGS[@]}"

# --- 8. Done ---
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
