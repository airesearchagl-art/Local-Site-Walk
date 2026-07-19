@echo off
setlocal EnableExtensions
title Local Site Walk - Diagnose

rem Repo root = one folder above this BAT
for %%i in ("%~dp0..") do set "ROOT=%%~fi"

echo ==============================================
echo  Local Site Walk - Diagnose
echo ==============================================
echo Target: "%ROOT%"
echo No secrets, API keys, tokens, or the full environment are shown.

echo.
echo --- Windows ---
ver

echo.
echo --- Git ---
git --version 2>nul || echo Git not found
git -C "%ROOT%" remote -v 2>nul
echo current branch:
git -C "%ROOT%" branch --show-current 2>nul
echo uncommitted changes (nothing shown = clean):
git -C "%ROOT%" status --short 2>nul

echo.
echo --- Python ---
py -3 --version 2>nul || python --version 2>nul || echo Python not found

echo.
echo --- Node.js / npm ---
node --version 2>nul || echo Node.js not found
call npm --version 2>nul || echo npm not found

echo.
echo --- FFmpeg (for future video processing; not required yet) ---
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo FFmpeg not found (not required at this stage)
) else (
    for /f "delims=" %%v in ('ffmpeg -version 2^>nul ^| findstr /b /c:"ffmpeg version"') do echo %%v
)

echo.
echo --- Setup state ---
if exist "%ROOT%\backend\.venv\Scripts\python.exe" (echo backend\.venv : present) else (echo backend\.venv : missing, run scripts\setup_windows.bat)
if exist "%ROOT%\frontend\node_modules" (echo frontend\node_modules : present) else (echo frontend\node_modules : missing, run scripts\setup_windows.bat)
if exist "%ROOT%\.env" (echo .env : present) else (echo .env : missing, optional, defaults are used)

echo.
echo --- Key config files ---
for %%f in ("backend\requirements.txt" "backend\requirements-dev.txt" "backend\app\main.py" "backend\pyproject.toml" "frontend\package.json" "frontend\vite.config.ts" ".env.example") do (
    if exist "%ROOT%\%%~f" (echo %%~f : present) else (echo %%~f : not found)
)

echo.
echo --- Port usage (backend:8000 / frontend:5173) ---
netstat -ano 2>nul | findstr /c:":8000 " | findstr "LISTENING"
if errorlevel 1 echo port 8000 : not in use
netstat -ano 2>nul | findstr /c:":5173 " | findstr "LISTENING"
if errorlevel 1 echo port 5173 : not in use

echo.
echo --- Data directory ---
if defined LSW_DATA_DIR (echo LSW_DATA_DIR : %LSW_DATA_DIR%) else (echo LSW_DATA_DIR : not set, using the default)
if exist "%USERPROFILE%\LocalSiteWalkData" (echo default data folder %%USERPROFILE%%\LocalSiteWalkData : present) else (echo default data folder %%USERPROFILE%%\LocalSiteWalkData : missing, setup_windows.bat will create it)

echo.
echo Diagnostics complete.
pause
exit /b 0
