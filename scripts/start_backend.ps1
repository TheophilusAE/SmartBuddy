# powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1

$ErrorActionPreference = 'Stop'
$dashboard = Join-Path (Split-Path -Parent $PSScriptRoot) 'dashboard'
$python = Join-Path $dashboard '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host "No virtual environment at dashboard\.venv. Create it first (see dashboard\README.md)." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path (Join-Path $dashboard '.env'))) {
    Write-Host "dashboard\.env is missing. Copy dashboard\.env.example to dashboard\.env and fill it in." -ForegroundColor Yellow
    exit 1
}

Push-Location $dashboard
try {
    & $python -m backend.main
}
finally {
    Pop-Location
}
