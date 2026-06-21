@echo off
echo ============================================
echo   AutoCut Agent - Apex Clip Tool
echo ============================================
echo.
echo [1/2] Starting backend API on port 8000...
start "AutoCut-API" cmd /c "cd /d %~dp0 && D:\study_tool\anaconda\envs\agent\python.exe main.py serve --port 8000"
timeout /t 3 /nobreak >nul
echo [2/2] Starting frontend on port 3000...
start "AutoCut-Frontend" cmd /c "cd /d %~dp0frontend && npx vite --host"
echo [3/3] Waiting for servers to be ready...
timeout /t 5 /nobreak >nul
start http://localhost:3000
echo.
echo ============================================
echo   Frontend: http://localhost:3000
echo   API docs:  http://localhost:8000/docs
echo ============================================
echo.
pause
