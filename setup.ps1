# Nexus one-command setup / upgrade (PowerShell).
#
# Usage:
#   irm https://raw.githubusercontent.com/llores28/Nexus/main/setup.ps1 | iex
#   # or, from a local clone:
#   .\setup.ps1
#
# Creates a project-local .venv, installs (or upgrades) Nexus into it, then
# runs `nexus init` to scaffold the current project with a guided wizard.

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

# --- 4. Install / upgrade Nexus ---
Info "Upgrading pip"
& python -m pip install --quiet --upgrade pip

if ($mode -eq "clone") {
    Info "Installing Nexus (editable) from local clone"
    & python -m pip install --quiet -e .
} else {
    Info "Installing / upgrading Nexus from $NexusRepo"
    & python -m pip install --quiet --upgrade "git+$NexusRepo"
}
if ($LASTEXITCODE -ne 0) { Err "pip install failed"; exit 1 }

# --- 5. Run nexus init (auto-detect upgrade) ---
$upgradeFlag = @()
if (Test-Path (Join-Path $ProjectDir ".nexus\state.json")) {
    $upgradeFlag = @("--upgrade")
    Info "Existing .nexus/ detected — running upgrade"
}

& nexus init --project-dir $ProjectDir @upgradeFlag
if ($LASTEXITCODE -ne 0) { Err "nexus init exited with $LASTEXITCODE"; exit $LASTEXITCODE }

# --- 6. Done ---
Info "Setup complete."
Write-Host "   Activate the venv in future sessions:"
Write-Host "     PowerShell:  & .venv\Scripts\Activate.ps1"
Write-Host "     cmd.exe:     .venv\Scripts\activate.bat"
Write-Host "     Git Bash:    . .venv/Scripts/activate"
Write-Host ""
