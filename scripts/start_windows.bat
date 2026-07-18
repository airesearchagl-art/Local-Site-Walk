@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Local Site Walk - 起動

rem リポジトリルート = このBATの1つ上のフォルダ
for %%i in ("%~dp0..") do set "ROOT=%%~fi"

echo ==============================================
echo  Local Site Walk 起動
echo ==============================================

rem --- セットアップ済みか確認 ---
if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    echo [エラー] backend\.venv が見つかりません。
    echo 先に scripts\setup_windows.bat を実行してください。
    pause
    exit /b 1
)
if not exist "%ROOT%\frontend\node_modules" (
    echo [エラー] frontend\node_modules が見つかりません。
    echo 先に scripts\setup_windows.bat を実行してください。
    pause
    exit /b 1
)

echo バックエンドを起動します（ポート8000）...
start "Local Site Walk - Backend" /d "%ROOT%\backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo フロントエンドを起動します（ポート5173）...
start "Local Site Walk - Frontend" /d "%ROOT%\frontend" cmd /k "npm run dev"

echo 起動を待っています...
timeout /t 8 /nobreak >nul

echo ブラウザを開きます: http://localhost:5173/
start "" "http://localhost:5173/"

echo.
type "%~dp0start_windows_message.txt"
echo.
pause
exit /b 0
