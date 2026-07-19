@echo off
setlocal EnableExtensions
rem chcp 65001 (UTF-8) is needed so "type" below renders the UTF-8
rem Japanese message .txt files correctly. This BAT's own body is
rem ASCII-only, so chcp does not affect how cmd.exe parses it.
chcp 65001 >nul
title Local Site Walk - Setup

rem Skip the final pause when called with the "nopause" argument (used by bootstrap etc.)
set "NOPAUSE=%~1"

rem Repo root = one folder above this BAT
for %%i in ("%~dp0..") do set "ROOT=%%~fi"

echo ==============================================
echo  Local Site Walk - Setup
echo ==============================================
echo Target: "%ROOT%"
echo.

rem --- Detect Python (prefer "py -3", fall back to "python") ---
set "PY_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [ERROR] Python not found. Install Python 3.11 or later.
    goto :fail
)
echo [OK] Python: %PY_CMD%

rem --- Check Node.js / npm ---
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 20 or later.
    goto :fail
)
call npm --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Check your Node.js installation.
    goto :fail
)
echo [OK] Node.js / npm found.

rem --- Backend virtual environment (do not recreate an existing .venv) ---
set "VENV_PY=%ROOT%\backend\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Creating backend\.venv ...
    %PY_CMD% -m venv "%ROOT%\backend\.venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        goto :fail
    )
)
echo Installing Python dependencies...
"%VENV_PY%" -m pip install -r "%ROOT%\backend\requirements-dev.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed.
    goto :fail
)

rem --- Frontend dependencies (use npm ci for reproducibility when a lockfile exists) ---
cd /d "%ROOT%\frontend"
if exist "package-lock.json" (
    echo Running npm ci ...
    call npm ci
    if errorlevel 1 (
        type "%~dp0setup_npm_deps_failed_message.txt"
        goto :fail
    )
) else (
    echo Running npm install ...
    call npm install
    if errorlevel 1 (
        type "%~dp0setup_npm_deps_failed_message.txt"
        goto :fail
    )
)

rem --- Data directory (outside the repo, default location) ---
if not exist "%USERPROFILE%\LocalSiteWalkData" (
    echo Creating data folder: "%USERPROFILE%\LocalSiteWalkData"
    mkdir "%USERPROFILE%\LocalSiteWalkData"
    if errorlevel 1 (
        echo [ERROR] Could not create the data folder.
        goto :fail
    )
)

rem --- .env (create from .env.example if missing; contains no secrets) ---
if not exist "%ROOT%\.env" (
    if exist "%ROOT%\.env.example" (
        copy "%ROOT%\.env.example" "%ROOT%\.env" >nul
        echo [OK] Created .env from .env.example. Edit it if needed.
    ) else (
        echo [NOTE] .env.example not found. Create .env manually if needed.
    )
)

rem --- Backend checks (lint / test / syntax) ---
cd /d "%ROOT%\backend"
echo.
echo Running ruff check ...
"%VENV_PY%" -m ruff check .
if errorlevel 1 (
    echo [ERROR] ruff found problems.
    goto :fail
)
echo Running pytest ...
"%VENV_PY%" -m pytest -q
if errorlevel 1 (
    echo [ERROR] pytest failed.
    goto :fail
)
echo Running compileall ...
"%VENV_PY%" -m compileall app -q
if errorlevel 1 (
    echo [ERROR] Python syntax check failed.
    goto :fail
)

rem --- Frontend checks (lint / typecheck / build) ---
cd /d "%ROOT%\frontend"
echo.
echo Running npm run lint ...
call npm run lint
if errorlevel 1 (
    echo [ERROR] lint failed.
    goto :fail
)
echo Running npm run typecheck ...
call npm run typecheck
if errorlevel 1 (
    echo [ERROR] typecheck failed.
    goto :fail
)
echo Running npm run build ...
call npm run build
if errorlevel 1 (
    echo [ERROR] build failed.
    goto :fail
)

echo.
echo ==============================================
echo  Setup and checks completed successfully
echo ==============================================
echo Start: scripts\start_windows.bat
if /i not "%NOPAUSE%"=="nopause" pause
exit /b 0

:fail
echo.
echo Setup aborted. See the messages above for details.
if /i not "%NOPAUSE%"=="nopause" pause
exit /b 1
