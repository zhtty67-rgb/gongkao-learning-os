@echo off
setlocal EnableDelayedExpansion
title Gongkao Learning OS

set "PROJECT=%~dp0"
set "PROJECT=%PROJECT:~0,-1%"
set "BACKEND_SCRIPT=%PROJECT%\scripts\start-backend.ps1"
set "FRONTEND_SCRIPT=%PROJECT%\scripts\start-frontend.ps1"

if not exist "%PROJECT%\.venv\Scripts\python.exe" goto need_install
if not exist "%PROJECT%\frontend\node_modules" goto need_install
goto ready

:need_install
echo [!] First run: please double-click "1-Install.bat" first.
pause
exit /b 1

:ready
rem ---------- backend :8000 ----------
powershell.exe -NoLogo -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [1/2] Starting backend FastAPI :8000 ...
    start /min "Gongkao Backend" powershell.exe -NoLogo -NoExit -ExecutionPolicy Bypass -File "%BACKEND_SCRIPT%"
    timeout /t 3 >nul
) else (
    echo [1/2] Backend already running.
)

rem ---------- frontend :3000 ----------
powershell.exe -NoLogo -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [2/2] Starting frontend Next.js :3000 ...
    start /min "Gongkao Frontend" powershell.exe -NoLogo -NoExit -ExecutionPolicy Bypass -File "%FRONTEND_SCRIPT%"
    timeout /t 4 >nul
) else (
    echo [2/2] Frontend already running.
)

start "" http://127.0.0.1:3000
echo.
echo Gongkao Learning OS: http://127.0.0.1:3000  (settings page: /settings)
timeout /t 8 >nul
