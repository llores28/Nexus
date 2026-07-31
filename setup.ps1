# Nexus setup / upgrade (PowerShell).
#
# RECOMMENDED usage (avoids AMSI/Defender blocks):
#
#   Option A — clone the repo and install into an explicit project:
#     git clone --branch v0.3.0 --depth 1 https://github.com/llores28/Nexus.git; cd Nexus
#     .\setup.ps1 -ProjectDir C:\path\to\project -Template team -Unattended
#
#   Option B — download to disk, inspect, then run:
#     irm https://raw.githubusercontent.com/llores28/Nexus/v0.3.0/setup.ps1 -OutFile setup-nexus.ps1
#     Unblock-File setup-nexus.ps1
#     .\setup-nexus.ps1 -ProjectDir C:\path\to\project -Template team -Unattended
#
#   NOTE: 'irm ... | iex' is blocked by Windows Defender AMSI on most systems
#   (ScriptContainedMaliciousContent) because it is the canonical malware cradle.
#   Use Option A or B above — AMSI does NOT flag local file execution.
#
#   If blocked by execution policy, run once:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#
#   Flags (only work when run from disk, not via irm|iex):
#   .\setup.ps1 -ProjectDir C:\path\to\project
#   .\setup.ps1 -ProjectDir C:\path\to\project -Source C:\path\to\nexus.whl
#   .\setup.ps1 -ProjectDir C:\path\to\project -Template team -Unattended
#   .\setup.ps1 -UpgradeOnly     # just refresh the Nexus package; skip nexus init
#   .\setup.ps1 -Refresh         # on upgrade, also regenerate BOOTSTRAP.md
#
# Behavior:
#   - Brand-new project: creates .venv, installs Nexus, and runs `nexus init`.
#   - Already-bootstrapped project (profile, manifest, or legacy state): creates/reuses
#     .venv, upgrades the Nexus package, runs `nexus init --upgrade` to re-validate
#     git hooks and run the health check. Does NOT re-prompt the wizard.
#     Does NOT overwrite BOOTSTRAP.md unless -Refresh is also passed.
#   - -UpgradeOnly: just install/upgrade the package and exit. Useful for
#     refreshing the tool on a project that doesn't use `nexus init` scaffolding.

param(
    [string]$ProjectDir = "",
    [ValidateSet("fast", "team", "enterprise")]
    [string]$Template = "",
    [string]$Consumers = "all",
    [string]$Source = "",
    [switch]$DryRun,
    [Alias("Yes")]
    [switch]$AcceptDefaults,
    [switch]$Unattended,
    [switch]$UpgradeOnly,
    [switch]$Refresh
)

$ErrorActionPreference = "Stop"

if ($Unattended) { $AcceptDefaults = $true }

function Info($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "`n!!  $msg" -ForegroundColor Yellow }
function Err ($msg) { Write-Host "`nXX  $msg" -ForegroundColor Red }

# --- Guard: AMSI / irm|iex cradle detection ---
# When this script is piped via `irm ... | iex`, $PSCommandPath is $null and
# $MyInvocation.InvocationName is empty or "&". Windows Defender's AMSI hooks
# the PowerShell parser on this delivery pattern and raises:
#   ScriptContainedMaliciousContent,Microsoft.PowerShell.Commands.InvokeExpressionCommand
# That error fires BEFORE this guard runs, so the block is AMSI-side.
# However, if AMSI is not active (e.g. corporate allowlist, older Defender sigs),
# this guard catches the pipe and redirects the user to the safe path.
if (-not $PSCommandPath) {
    Write-Host ""
    Write-Host "!! AMSI WARNING: You are running this script via 'irm ... | iex'." -ForegroundColor Yellow
    Write-Host "   Windows Defender blocks this delivery pattern as a security measure." -ForegroundColor Yellow
    Write-Host "   If you received a 'ScriptContainedMaliciousContent' error, that is why." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Use the safe path instead (download -> inspect -> run):" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "     irm https://raw.githubusercontent.com/llores28/Nexus/v0.3.0/setup.ps1 -OutFile setup-nexus.ps1" -ForegroundColor White
    Write-Host "     Unblock-File setup-nexus.ps1" -ForegroundColor White
    Write-Host "     .\setup-nexus.ps1 -ProjectDir C:\path\to\project -Template team -Unattended" -ForegroundColor White
    Write-Host ""
    Write-Host "   Or clone the repo and run locally (most reliable):" -ForegroundColor Cyan
    Write-Host "     git clone --branch v0.3.0 --depth 1 https://github.com/llores28/Nexus.git; cd Nexus" -ForegroundColor White
    Write-Host "     .\setup.ps1 -ProjectDir C:\path\to\project -Template team -Unattended" -ForegroundColor White
    Write-Host ""
    exit 1
}

$NexusSpec = if ($Source) { $Source } else { "git+https://github.com/llores28/Nexus.git@v0.3.0" }
$ScriptDir = Split-Path -Parent $PSCommandPath
if (-not $ProjectDir) {
    $candidate = (Get-Location).Path
    $candidatePyproject = Join-Path $candidate "pyproject.toml"
    if ((Test-Path $candidatePyproject) -and ((Get-Content $candidatePyproject -Raw) -match 'name = "nexus-bootstrap"')) {
        Err "Running from the Nexus clone requires -ProjectDir <your-project>."
        exit 2
    }
    $ProjectDir = $candidate
}
if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
    Err "Project directory does not exist: $ProjectDir"
    exit 2
}
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path

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

# --- 1b. Check git when the selected package source requires it ---
if ($NexusSpec.StartsWith("git+") -and -not (Get-Command git -ErrorAction SilentlyContinue)) {
    Err "git not found. Install from https://git-scm.com/ and re-run."
    exit 1
}
if (Get-Command git -ErrorAction SilentlyContinue) { Write-Host "   git: $(git --version)" }

# --- 2. Detect install source: local Nexus clone vs pinned release ---
$mode = if ($Source) { "custom" } else { "target" }
$pyprojectPath = Join-Path $ScriptDir "pyproject.toml"
if (-not $Source -and (Test-Path $pyprojectPath)) {
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

function Invoke-VenvPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $savedPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $null
        & $script:venvPy @Arguments
        $script:VenvExitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $savedPythonPath
    }
}

# --- 4. Detect prior Nexus install (informational) ---
$priorVersion = ""
$pipShow = Invoke-VenvPython -m pip show nexus-bootstrap 2>$null
if ($VenvExitCode -eq 0 -and $pipShow) {
    $line = $pipShow | Select-String -Pattern '^Version:'
    if ($line) {
        $priorVersion = ($line.Line -split '\s+', 2)[1].Trim()
    }
    Info "Existing Nexus install detected: nexus-bootstrap $priorVersion"
} else {
    Info "No existing Nexus install detected (first install in this venv)"
}

# --- 5. Install / upgrade Nexus ---
Info "Using project-local pip"
Invoke-VenvPython -m pip --version

if ($mode -eq "clone") {
    if ($priorVersion) {
        Info "Reinstalling Nexus from local clone"
    } else {
        Info "Installing Nexus from local clone"
    }
    Invoke-VenvPython -m pip install --quiet --upgrade --force-reinstall $ScriptDir
} else {
    if ($priorVersion) {
        Info "Upgrading Nexus from $NexusSpec"
    } else {
        Info "Installing Nexus from $NexusSpec"
    }
    Invoke-VenvPython -m pip install --quiet --upgrade --force-reinstall $NexusSpec
}
if ($VenvExitCode -ne 0) { Err "pip install failed"; exit 1 }

$pipShow2 = Invoke-VenvPython -m pip show nexus-bootstrap 2>$null
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
$initFlags = @("--consumers", $Consumers)
$profileJson = Join-Path $ProjectDir ".nexus\profile.json"
$manifestJson = Join-Path $ProjectDir ".nexus\install-manifest.json"
$stateJson = Join-Path $ProjectDir ".nexus\state.json"
$legacyWindsurf = Join-Path $ProjectDir ".windsurf"
$agentsMd = Join-Path $ProjectDir "AGENTS.md"
$hasManagedAgents = (Test-Path $agentsMd) -and ((Get-Content -LiteralPath $agentsMd -Raw) -match '<!-- nexus:agents-md:begin -->')
if ((Test-Path $profileJson) -or (Test-Path $manifestJson) -or (Test-Path $stateJson) -or
    (Test-Path $legacyWindsurf) -or $hasManagedAgents) {
    $initFlags += "--upgrade"
    if ($Refresh) {
        $initFlags += "--refresh"
    }
    Info "Existing Nexus project detected (profile, manifest, managed AGENTS, or legacy artifacts) -- running upgrade"
} elseif ($Refresh) {
    Warn "-Refresh has no effect on a fresh init (BOOTSTRAP.md doesn't exist yet). Ignoring."
}

if ($Template) { $initFlags += @("--template", $Template) }
if ($DryRun) { $initFlags += "--dry-run" }
if ($AcceptDefaults) { $initFlags += "--yes" }

$venvNexus = Join-Path $venv "Scripts\nexus.exe"
if (-not (Test-Path $venvNexus)) { $venvNexus = Join-Path $venv "bin\nexus" }
$savedPythonPath = $env:PYTHONPATH
$nexusExit = 1
try {
    $env:PYTHONPATH = $null
    Push-Location -LiteralPath $ProjectDir
    try {
        & $venvNexus init --project-dir $ProjectDir @initFlags
        $nexusExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:PYTHONPATH = $savedPythonPath
}
if ($nexusExit -ne 0) { Err "nexus init exited with $nexusExit"; exit $nexusExit }

# --- 8. Done ---
Info "Setup complete."
Write-Host "   Activate the venv in future sessions:"
Write-Host "     PowerShell:  & .venv\Scripts\Activate.ps1"
Write-Host "     cmd.exe:     .venv\Scripts\activate.bat"
Write-Host "     Git Bash:    . .venv/Scripts/activate"
Write-Host ""
