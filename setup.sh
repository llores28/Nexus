#!/usr/bin/env bash
# Nexus one-command setup / upgrade.
#
# Usage:
#   ./nexus/setup.sh --template team --yes   # from the containing project
#   ./setup.sh --template team --yes         # from inside <project>/nexus
#   ./setup.sh --project-dir /path/to/project
#   ./setup.sh --project-dir /path/to/project --source /path/to/nexus.whl
#   ./setup.sh --project-dir /path/to/project --template team --unattended
#   ./setup.sh --upgrade-only   # just refresh the Nexus package; skip nexus init
#   ./setup.sh --refresh        # on upgrade, also regenerate BOOTSTRAP.md
#
# Behavior:
#   - When this script is run from <project>/nexus without --project-dir, the
#     containing project directory is selected automatically.
#   - Brand-new project: creates .venv, installs Nexus, and runs `nexus init`.
#   - Already-bootstrapped project (profile, manifest, or legacy state): creates/reuses
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
    printf "    1) PowerShell (recommended): download setup.ps1, inspect it, then run it with -ProjectDir.\n\n"
    printf "    2) Git Bash (open 'Git Bash' from Start menu, then run):\n"
    printf "       curl -fsSLo setup-nexus.sh https://raw.githubusercontent.com/llores28/Nexus/v0.3.0/setup.sh\n"
    printf "       bash setup-nexus.sh --project-dir .\n\n"
    printf "    3) Install WSL: wsl --install  (then reboot and re-run)\n\n"
    exit 1
  fi
fi

NEXUS_SPEC="git+https://github.com/llores28/Nexus.git@v0.3.0"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR=""

UPGRADE_ONLY=0
REFRESH=0
DRY_RUN=0
YES=0
TEMPLATE=""
CONSUMERS="all"
SOURCE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift ;;
    --template) TEMPLATE="$2"; shift ;;
    --consumers) CONSUMERS="$2"; shift ;;
    --source) SOURCE="$2"; NEXUS_SPEC="$2"; shift ;;
    --dry-run) DRY_RUN=1 ;;
    --yes|--accept-defaults|--unattended) YES=1 ;;
    --upgrade-only) UPGRADE_ONLY=1 ;;
    --refresh)      REFRESH=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
  shift
done

info() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
warn() { printf "\n\033[1;33m!!  %s\033[0m\n" "$*"; }
err()  { printf "\n\033[1;31mXX  %s\033[0m\n" "$*" >&2; }

if [ -z "$PROJECT_DIR" ]; then
  PROJECT_DIR="$(pwd)"
  INSTALLER_NAME="$(basename "$SCRIPT_DIR")"
  if [ "$PROJECT_DIR" = "$SCRIPT_DIR" ] && [ "$(printf '%s' "$INSTALLER_NAME" | tr '[:upper:]' '[:lower:]')" = "nexus" ] && [ -f "$PROJECT_DIR/pyproject.toml" ] && grep -q 'name = "nexus-bootstrap"' "$PROJECT_DIR/pyproject.toml"; then
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
    info "Targeting containing project: $PROJECT_DIR"
  elif [ -f "$PROJECT_DIR/pyproject.toml" ] && grep -q 'name = "nexus-bootstrap"' "$PROJECT_DIR/pyproject.toml"; then
    err "A standalone Nexus source checkout requires --project-dir <your-project>."
    exit 2
  fi
fi
if [ ! -d "$PROJECT_DIR" ]; then
  err "Project directory does not exist: $PROJECT_DIR"
  exit 2
fi
PROJECT_DIR="$(CDPATH= cd -- "$PROJECT_DIR" && pwd)"

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

# --- 1b. Check git when the selected package source requires it ---
if [ "${NEXUS_SPEC#git+}" != "$NEXUS_SPEC" ] && ! command -v git >/dev/null 2>&1; then
  err "git not found. Install git from https://git-scm.com/ and re-run."
  exit 1
fi
if command -v git >/dev/null 2>&1; then echo "   git: $(git --version)"; fi

# --- 2. Detect mode: local-clone vs target-project ---
MODE="target"
if [ -n "$SOURCE" ]; then
  MODE="custom"
  NEXUS_SPEC="$SOURCE"
elif [ -f "$SCRIPT_DIR/pyproject.toml" ] && grep -q 'name = "nexus-bootstrap"' "$SCRIPT_DIR/pyproject.toml" 2>/dev/null; then
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
if PYTHONPATH= python -m pip show nexus-bootstrap >/dev/null 2>&1; then
  PRIOR_VERSION="$(PYTHONPATH= python -m pip show nexus-bootstrap 2>/dev/null | awk '/^Version:/ {print $2}')"
  info "Existing Nexus install detected: nexus-bootstrap ${PRIOR_VERSION}"
else
  info "No existing Nexus install detected (first install in this venv)"
fi

# --- 5. Install / upgrade Nexus ---
info "Using project-local pip"
PYTHONPATH= python -m pip --version

if [ "$MODE" = "clone" ]; then
  if [ -n "$PRIOR_VERSION" ]; then
    info "Reinstalling Nexus from local clone"
  else
    info "Installing Nexus from local clone"
  fi
  PYTHONPATH= python -m pip install --quiet --upgrade --force-reinstall "$SCRIPT_DIR"
else
  if [ -n "$PRIOR_VERSION" ]; then
    info "Upgrading Nexus from $NEXUS_SPEC"
  else
    info "Installing Nexus from $NEXUS_SPEC"
  fi
  PYTHONPATH= python -m pip install --quiet --upgrade --force-reinstall "$NEXUS_SPEC"
fi

NEW_VERSION="$(PYTHONPATH= python -m pip show nexus-bootstrap 2>/dev/null | awk '/^Version:/ {print $2}')"
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
INIT_FLAGS=(--consumers "$CONSUMERS")
HAS_MANAGED_AGENTS=0
if [ -f "$PROJECT_DIR/AGENTS.md" ] && grep -q '<!-- nexus:agents-md:begin -->' "$PROJECT_DIR/AGENTS.md"; then
  HAS_MANAGED_AGENTS=1
fi
if [ -f "$PROJECT_DIR/.nexus/profile.json" ] || [ -f "$PROJECT_DIR/.nexus/install-manifest.json" ] || [ -f "$PROJECT_DIR/.nexus/state.json" ] || [ -d "$PROJECT_DIR/.windsurf" ] || [ "$HAS_MANAGED_AGENTS" -eq 1 ]; then
  INIT_FLAGS+=(--upgrade)
  if [ "$REFRESH" -eq 1 ]; then
    INIT_FLAGS+=(--refresh)
  fi
  info "Existing Nexus project detected (profile, manifest, managed AGENTS, or legacy artifacts) -- running upgrade"
elif [ "$REFRESH" -eq 1 ]; then
  warn "--refresh has no effect on a fresh init (BOOTSTRAP.md doesn't exist yet). Ignoring."
fi

if [ -n "$TEMPLATE" ]; then INIT_FLAGS+=(--template "$TEMPLATE"); fi
if [ "$DRY_RUN" -eq 1 ]; then INIT_FLAGS+=(--dry-run); fi
if [ "$YES" -eq 1 ]; then INIT_FLAGS+=(--yes); fi

if [ -x "$VENV/Scripts/nexus.exe" ]; then
  NEXUS_BIN="$VENV/Scripts/nexus.exe"
else
  NEXUS_BIN="$VENV/bin/nexus"
fi
(
  cd "$PROJECT_DIR"
  PYTHONPATH= "$NEXUS_BIN" init --project-dir "$PROJECT_DIR" "${INIT_FLAGS[@]}"
)

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
