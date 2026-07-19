@echo off
setlocal EnableExtensions
rem chcp 65001 (UTF-8) is needed so "type" below renders the UTF-8
rem Japanese message .txt file correctly. This BAT's own body is
rem ASCII-only, so chcp does not affect how cmd.exe parses it.
chcp 65001 >nul
title Local Site Walk - Start

rem Repo root = one folder above this BAT
for %%i in ("%~dp0..") do set "ROOT=%%~fi"

echo ==============================================
echo  Local Site Walk - Start
echo ==============================================

rem --- Check setup has been completed ---
if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    echo [ERROR] backend\.venv not found.
    echo Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)
if not exist "%ROOT%\frontend\node_modules" (
    echo [ERROR] frontend\node_modules not found.
    echo Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)

echo Starting backend (port 8000) ...
start "Local Site Walk - Backend" /d "%ROOT%\backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo Starting frontend (port 5173) ...
start "Local Site Walk - Frontend" /d "%ROOT%\frontend" cmd /k "npm run dev"

echo Waiting for startup ...
timeout /t 8 /nobreak >nul

echo Opening browser: http://localhost:5173/
start "" "http://localhost:5173/"

echo.
type "%~dp0start_windows_message.txt"
echo.
pause
exit /b 0
