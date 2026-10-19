# Run from PowerShell: powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host '[ACTION] Edit .env with your actual MySQL password and two unique secrets.' -ForegroundColor Yellow
}
if (-not (Test-Path '.venv')) {
    python -m venv .venv
}
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Pip upgrade failed' }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
Write-Host 'Python dependencies installed. Next steps:' -ForegroundColor Green
Write-Host '1. Set MYSQL_PASSWORD and secrets in .env'
Write-Host '2. Run MySQL client: mysql -u root -p -e "source sql/00_database.sql"'
Write-Host '3. Run MySQL client: mysql -u root -p -e "source sql/01_schema.sql"'
Write-Host '4. Run MySQL client: mysql -u root -p -e "source sql/02_programmability.sql"'
Write-Host '5. Check schema: cd backend; ..\.venv\Scripts\python.exe manage.py verify_schema'
Write-Host '6. Seed demo: ..\.venv\Scripts\python.exe manage.py seed_demo'
