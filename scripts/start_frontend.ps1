# powershell -ExecutionPolicy Bypass -File scripts\start_frontend.ps1

$ErrorActionPreference = 'Stop'
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) 'dashboard\frontend'

if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host "Dependencies not installed. Run 'npm install' in dashboard\frontend first (see dashboard\README.md)." -ForegroundColor Yellow
    exit 1
}

Push-Location $frontend
try {
    npm run dev
}
finally {
    Pop-Location
}
