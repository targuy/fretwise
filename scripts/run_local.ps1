<#
.SYNOPSIS
  Run FretWise in SINGLE-USER mode against the local library (Windows).
.DESCRIPTION
  Unlike run.ps1 (which loads .env and enables multi-user Google OIDC, so the UI
  shows each logged-in user's OWN Google Drive), this launcher forces
  single-user mode with NO login and serves the on-disk `partitions/` library
  directly. Use it to test/preview locally without a Google Drive round-trip.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1
  $env:PORT='8800'; powershell -File scripts\run_local.ps1
  $env:PARTITIONS='C:\scores'; powershell -File scripts\run_local.ps1
#>
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Shared helpers (benign-pixi-line filter, etc.).
. (Join-Path $PSScriptRoot 'pixi-helpers.ps1')

$pixiBin = Join-Path $env:USERPROFILE ".pixi\bin"
if (Test-Path (Join-Path $pixiBin "pixi.exe")) { $env:Path = "$pixiBin;$env:Path" }
if (-not (Get-Command pixi -ErrorAction SilentlyContinue)) {
  Write-Error "pixi not found - run scripts\install.ps1 first"; exit 1
}

# Force single-user: do NOT load .env, and clear any auth/OIDC vars already in
# the environment so create_app() stays in single-user mode.
foreach ($v in @(
    'FRETWISE_AUTH_ENABLED',
    'FRETWISE_GOOGLE_CLIENT_ID', 'FRETWISE_GOOGLE_CLIENT_SECRET',
    'FRETWISE_OIDC_CLIENT_ID', 'FRETWISE_OIDC_CLIENT_SECRET', 'FRETWISE_OIDC_ISSUER',
    'FRETWISE_OIDC_NAME', 'FRETWISE_SECRET_KEY', 'FRETWISE_BASE_URL')) {
  [System.Environment]::SetEnvironmentVariable($v, $null)
}

$bindHost   = if ($env:HOST) { $env:HOST } else { 'localhost' }
$port       = if ($env:PORT) { $env:PORT } else { '8080' }
$partitions = if ($env:PARTITIONS) { $env:PARTITIONS } else { Join-Path $Root 'partitions' }

if (-not (Test-Path $partitions)) {
  Write-Error "partitions dir not found: $partitions"; exit 1
}

$env:FRETWISE_PARTITIONS_DIR = $partitions
Write-Host "==> FretWise (SINGLE-USER, no login)"
Write-Host "    library : $partitions"
Write-Host "    url     : http://${bindHost}:${port}   (Ctrl+C to stop)"

# Launch via pixi, filtering out pixi's harmless "`.pixi\envs` already exists"
# (os error 183) line so it does not look like a real failure. Every other line
# (including live uvicorn logs) passes straight through. Ctrl+C still stops the
# server; we echo pixi's own exit code afterwards.
$ErrorActionPreference = 'Continue'
pixi run fretwise web --host $bindHost --port $port --dir $partitions 2>&1 |
  ForEach-Object {
    $text = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
    if (Test-IsBenignPixiEnvLine $text) {
      Write-Host "    (pixi: ignored a harmless '.pixi\envs already exists' notice - environment OK)" -ForegroundColor DarkGray
    } else {
      Write-Host $text
    }
  }
exit $LASTEXITCODE
