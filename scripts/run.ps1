<#
.SYNOPSIS
  Run FretWise on Windows.
.DESCRIPTION
  No arguments  -> launches the web UI (http://localhost:8080).
  With arguments -> passes them to the `fretwise` CLI.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run.ps1
  powershell -ExecutionPolicy Bypass -File scripts\run.ps1 solve song.gp5 --mode performance
  $env:HOST='0.0.0.0'; $env:PORT='9090'; powershell -File scripts\run.ps1
#>
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$pixiBin = Join-Path $env:USERPROFILE ".pixi\bin"
if (Test-Path (Join-Path $pixiBin "pixi.exe")) { $env:Path = "$pixiBin;$env:Path" }
if (-not (Get-Command pixi -ErrorAction SilentlyContinue)) {
  Write-Error "pixi not found - run scripts\install.ps1 first"; exit 1
}

# Auto-load multi-user / OIDC config from .env if present (see .env.example).
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
  Write-Host "==> Loading .env (multi-user config)"
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
      $k, $v = $line.Split('=', 2)
      [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
    }
  }
}

if ($args.Count -eq 0) {
  $bindHost = if ($env:HOST) { $env:HOST } else { 'localhost' }
  $port     = if ($env:PORT) { $env:PORT } else { '8080' }
  Write-Host "==> FretWise web UI -> http://${bindHost}:${port}   (Ctrl+C to stop)"
  pixi run fretwise web --host $bindHost --port $port
} else {
  pixi run fretwise @args
}
