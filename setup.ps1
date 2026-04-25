# Nexus one-command setup / upgrade (PowerShell).
#
# Usage:
#   irm https://raw.githubusercontent.com/llores28/Nexus/main/setup.ps1 | iex
#   NOTE: 'irm ... | iex' does NOT support -UpgradeOnly / -Refresh flags.
#   For flags, save the script first: irm ... -OutFile setup.ps1; .\setup.ps1 -UpgradeOnly
#
#   If blocked by execution policy, run once:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#
#   # or, from a local clone:
#   .\setup.ps1                  # fresh init OR safe upgrade (auto-detected)
#   .\setup.ps1 -UpgradeOnly     # just refresh the Nexus package; skip nexus init
#   .\setup.ps1 -Refresh         # on upgrade, also regenerate BOOTSTRAP.md
#
# Behavior:
#   - Brand-new project (no .nexus/state.json): creates .venv, installs Nexus,
#     runs `nexus init` (interactive 7-question wizard).
#   - Already-bootstrapped project (.nexus/state.json present): creates/reuses
#     .venv, upgrades the Nexus package, runs `nexus init --upgrade` to re-validate
#     git hooks and run the health check. Does NOT re-prompt the wizard.
#     Does NOT overwrite BOOTSTRAP.md unless -Refresh is also passed.
#   - -UpgradeOnly: just install/upgrade the package and exit. Useful for
#     refreshing the tool on a project that doesn't use `nexus init` scaffolding.

param(
    [switch]$UpgradeOnly,
    [switch]$Refresh
)

$ErrorActionPreference = "Stop"

$NexusRepo  = "https://github.com/llores28/Nexus.git"
$ProjectDir = (Get-Location).Path

function Info($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "`n!!  $msg" -ForegroundColor Yellow }
function Err ($msg) { Write-Host "`nXX  $msg" -ForegroundColor Red }

# --- 1. Check Python ---
Info "Checking Python 3.10+"
$py = $null
foreach ($candidate in @("python", "python3", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            $parts = $ver -split '\.'
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
                $py = $candidate
                break
            }
        } catch {}
    }
}

if (-not $py) {
    Err "Python 3.10+ not found. Install from https://www.python.org/downloads/ and re-run."
    exit 1
}
$pyVersion = & $py --version
Write-Host "   using: $py ($pyVersion)"

# --- 1b. Check git (required for pip install git+...) ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Err "git not found. Install from https://git-scm.com/ and re-run."
    exit 1
}
Write-Host "   git: $(git --version)"

# --- 2. Detect mode: local-clone vs target-project ---
$mode = "target"
$pyprojectPath = Join-Path $ProjectDir "pyproject.toml"
if (Test-Path $pyprojectPath) {
    $content = Get-Content $pyprojectPath -Raw
    if ($content -match 'name = "nexus-bootstrap"') {
        $mode = "clone"
    }
}
Info "Mode: $mode"

# --- 3. Create / reuse .venv ---
$venv = Join-Path $ProjectDir ".venv"
if (Test-Path $venv) {
    Info "Reusing existing .venv"
} else {
    Info "Creating .venv"
    & $py -m venv $venv
    if ($LASTEXITCODE -ne 0) { Err "venv creation failed"; exit 1 }
}

# Activate
$activate = Join-Path $venv "Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    $activate = Join-Path $venv "bin\Activate.ps1"
}
if (-not (Test-Path $activate)) {
    Err "Could not find venv activate script in $venv"
    exit 1
}
& $activate

# Pin to the venv's own python.exe so all subsequent calls use the correct interpreter
$venvPy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    $venvPy = Join-Path $venv "bin\python"
}

# --- 4. Detect prior Nexus install (informational) ---
$priorVersion = ""
$pipShow = & $venvPy -m pip show nexus-bootstrap 2>$null
if ($LASTEXITCODE -eq 0 -and $pipShow) {
    $line = $pipShow | Select-String -Pattern '^Version:'
    if ($line) {
        $priorVersion = ($line.Line -split '\s+', 2)[1].Trim()
    }
    Info "Existing Nexus install detected: nexus-bootstrap $priorVersion"
} else {
    Info "No existing Nexus install detected (first install in this venv)"
}

# --- 5. Install / upgrade Nexus ---
Info "Upgrading pip"
& $venvPy -m pip install --quiet --upgrade pip

if ($mode -eq "clone") {
    if ($priorVersion) {
        Info "Reinstalling Nexus (editable) from local clone"
    } else {
        Info "Installing Nexus (editable) from local clone"
    }
    & $venvPy -m pip install --quiet -e .
} else {
    if ($priorVersion) {
        Info "Upgrading Nexus from $NexusRepo"
    } else {
        Info "Installing Nexus from $NexusRepo"
    }
    & $venvPy -m pip install --quiet --upgrade "git+$NexusRepo"
}
if ($LASTEXITCODE -ne 0) { Err "pip install failed"; exit 1 }

$pipShow2 = & $venvPy -m pip show nexus-bootstrap 2>$null
$newVersion = ""
if ($pipShow2) {
    $line = $pipShow2 | Select-String -Pattern '^Version:'
    if ($line) {
        $newVersion = ($line.Line -split '\s+', 2)[1].Trim()
    }
}
if ($priorVersion -and $priorVersion -ne $newVersion) {
    Write-Host "   nexus-bootstrap: $priorVersion -> $newVersion"
} else {
    Write-Host "   nexus-bootstrap: $newVersion"
}

# --- 6. -UpgradeOnly: stop here ---
if ($UpgradeOnly) {
    Info "Package upgrade complete (-UpgradeOnly)."
    Write-Host "   Skipping 'nexus init' as requested."
    Write-Host "   Activate the venv:  & .venv\Scripts\Activate.ps1"
    exit 0
}

# --- 7. Run nexus init (auto-detect upgrade vs fresh) ---
$initFlags = @()
$stateJson = Join-Path $ProjectDir ".nexus\state.json"
if (Test-Path $stateJson) {
    $initFlags += "--upgrade"
    if ($Refresh) {
        $initFlags += "--refresh"
    }
    Info "Already-bootstrapped project detected (.nexus/state.json present) -- running upgrade"
} elseif ($Refresh) {
    Warn "-Refresh has no effect on a fresh init (BOOTSTRAP.md doesn't exist yet). Ignoring."
}

& nexus init --project-dir $ProjectDir @initFlags
if ($LASTEXITCODE -ne 0) { Err "nexus init exited with $LASTEXITCODE"; exit $LASTEXITCODE }

# --- 8. Done ---
Info "Setup complete."
Write-Host "   Activate the venv in future sessions:"
Write-Host "     PowerShell:  & .venv\Scripts\Activate.ps1"
Write-Host "     cmd.exe:     .venv\Scripts\activate.bat"
Write-Host "     Git Bash:    . .venv/Scripts/activate"
Write-Host ""
