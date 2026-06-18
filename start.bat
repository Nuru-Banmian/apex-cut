@echo off
cd /d "%~dp0"

:: Use PowerShell if available (native UTF-8, no garbled text)
where powershell.exe >nul 2>&1
if %errorlevel% equ 0 (
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0start.ps1"
) else (
    :: Ultimate fallback
    chcp 65001 >nul
    D:\study_tool\anaconda\envs\agent\python.exe main.py serve --port 8000
    pause
)
