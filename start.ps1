# AutoCut Agent - Start Script (PowerShell, native UTF-8)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = "D:\study_tool\anaconda\envs\agent\python.exe"
$Port = 8000

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  AutoCut Agent - AI Video Editing System" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] Python not found: $Python" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Check environment
Write-Host "[1/2] Checking environment..." -ForegroundColor Gray
& $Python -c "from autocut.config import settings; print('Environment OK, provider:', settings.llm_provider)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to import autocut" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Start
Write-Host "[2/2] Starting server..." -ForegroundColor Gray
Write-Host ""
Write-Host "  Frontend : http://localhost:$Port" -ForegroundColor Green
Write-Host "  API Docs : http://localhost:$Port/docs" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# Open browser
Start-Process "http://localhost:$Port"

# Run server
& $Python main.py serve --port $Port

Read-Host "Press Enter to exit"
