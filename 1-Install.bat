@echo off
setlocal EnableDelayedExpansion
title Gongkao Learning OS - Install
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Please install Python 3.11+ first.
    echo     https://www.python.org/downloads/
    pause
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [!] Node.js/npm not found. Please install Node.js 20+ first.
    echo     https://nodejs.org/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating Python venv ...
    python -m venv .venv
)
echo [2/3] Installing backend dependencies (requirements.lock.txt) ...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.lock.txt -q
if errorlevel 1 (
    echo [!] Backend dependency install failed.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [3/3] Installing frontend dependencies (npm install) ...
    cd frontend
    call npm install
    if errorlevel 1 ( cd .. & pause & exit /b 1 )
    echo      Building frontend (npm run build) ...
    call npm run build
    cd ..
) else (
    echo [3/3] Frontend already installed.
)

echo.
echo Done! Double-click "2-Start.bat" to launch.
echo Configure your AI API key on the settings page: http://127.0.0.1:3000/settings
pause
