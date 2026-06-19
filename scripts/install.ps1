<#
.SYNOPSIS
  Install FretWise on Windows.
.DESCRIPTION
  Ensures pixi is available, then installs the locked pixi environment.
.PARAMETER Dev
  Also install the 'dev' environment (pytest, ruff, mypy).
.PARAMETER NoLock
  Allow pixi to update the lock file if needed (default: --locked).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev
#>
param(
  [switch]$Dev,
  [switch]$NoLock
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "==> FretWise install (Windows)"
Write-Host "    project: $Root"

# ---- 1. ensure pixi -------------------------------------------------------
$pixiBin = Join-Path $env:USERPROFILE ".pixi\bin"
if (-not (Get-Command pixi -ErrorAction SilentlyContinue)) {
  if (Test-Path (Join-Path $pixiBin "pixi.exe")) {
    $env:Path = "$pixiBin;$env:Path"
  } else {
    Write-Host "==> pixi not found - installing from https://pixi.sh"
    Invoke-RestMethod -UseBasicParsing https://pixi.sh/install.ps1 | Invoke-Expression
    $env:Path = "$pixiBin;$env:Path"
  }
}
if (-not (Get-Command pixi -ErrorAction SilentlyContinue)) {
  Write-Error "pixi still not on PATH - open a new shell or add $pixiBin to PATH"; exit 1
}
Write-Host "    pixi $(pixi --version)"

# ---- 2. install environment(s) -------------------------------------------
$lock = if ($NoLock) { @() } else { @('--locked') }
Write-Host "==> pixi install (default)"
pixi install @lock -e default
if ($Dev) {
  Write-Host "==> pixi install (dev)"
  pixi install @lock -e dev
}

Write-Host "==> Done. Launch with:  scripts\run.ps1        (web UI on http://localhost:8080)"
Write-Host "                  or:   scripts\run.ps1 solve song.gp5   (CLI)"
