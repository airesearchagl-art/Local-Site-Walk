@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Local Site Walk - セットアップ

rem 引数 nopause 付きで呼ばれた場合は最後に pause しない（bootstrap等からの呼び出し用）
set "NOPAUSE=%~1"

rem リポジトリルート = このBATの1つ上のフォルダ
for %%i in ("%~dp0..") do set "ROOT=%%~fi"

echo ==============================================
echo  Local Site Walk セットアップ
echo ==============================================
echo 対象: "%ROOT%"
echo.

rem --- Python の検出（py -3 を優先し、なければ python）---
set "PY_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [エラー] Python が見つかりません。Python 3.11 以上をインストールしてください。
    goto :fail
)
echo [OK] Python: %PY_CMD%

rem --- Node.js / npm の確認 ---
node --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Node.js が見つかりません。Node.js 20 以上をインストールしてください。
    goto :fail
)
call npm --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] npm が見つかりません。Node.js のインストール状態を確認してください。
    goto :fail
)
echo [OK] Node.js / npm を確認しました。

rem --- backend 仮想環境（既存の .venv は再作成しない）---
set "VENV_PY=%ROOT%\backend\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo backend\.venv を作成します...
    %PY_CMD% -m venv "%ROOT%\backend\.venv"
    if errorlevel 1 (
        echo [エラー] 仮想環境の作成に失敗しました。
        goto :fail
    )
)
echo Python 依存関係をインストールします...
"%VENV_PY%" -m pip install -r "%ROOT%\backend\requirements-dev.txt"
if errorlevel 1 (
    echo [エラー] pip install に失敗しました。
    goto :fail
)

rem --- frontend 依存関係（lockfile があれば npm ci で再現性を確保）---
cd /d "%ROOT%\frontend"
if exist "package-lock.json" (
    echo npm ci を実行します...
    call npm ci
) else (
    echo npm install を実行します...
    call npm install
)
if errorlevel 1 (
    echo [エラー] frontend の依存関係インストールに失敗しました。
    goto :fail
)

rem --- データ保存先（リポジトリ外・既定値）---
if not exist "%USERPROFILE%\LocalSiteWalkData" (
    echo データフォルダを作成します: "%USERPROFILE%\LocalSiteWalkData"
    mkdir "%USERPROFILE%\LocalSiteWalkData"
    if errorlevel 1 (
        echo [エラー] データフォルダを作成できませんでした。
        goto :fail
    )
)

rem --- .env（なければ .env.example から作成。機密情報は含まれません）---
if not exist "%ROOT%\.env" (
    if exist "%ROOT%\.env.example" (
        copy "%ROOT%\.env.example" "%ROOT%\.env" >nul
        echo [OK] .env を .env.example から作成しました。必要に応じて編集してください。
    ) else (
        echo [注意] .env.example が見つかりません。必要なら .env を手動で作成してください。
    )
)

rem --- backend の確認（lint / test / 構文）---
cd /d "%ROOT%\backend"
echo.
echo ruff check を実行します...
"%VENV_PY%" -m ruff check .
if errorlevel 1 (
    echo [エラー] ruff で問題が検出されました。
    goto :fail
)
echo pytest を実行します...
"%VENV_PY%" -m pytest -q
if errorlevel 1 (
    echo [エラー] pytest が失敗しました。
    goto :fail
)
echo compileall を実行します...
"%VENV_PY%" -m compileall app -q
if errorlevel 1 (
    echo [エラー] Python の構文確認に失敗しました。
    goto :fail
)

rem --- frontend の確認（lint / 型 / build）---
cd /d "%ROOT%\frontend"
echo.
echo npm run lint を実行します...
call npm run lint
if errorlevel 1 (
    echo [エラー] lint が失敗しました。
    goto :fail
)
echo npm run typecheck を実行します...
call npm run typecheck
if errorlevel 1 (
    echo [エラー] 型チェックが失敗しました。
    goto :fail
)
echo npm run build を実行します...
call npm run build
if errorlevel 1 (
    echo [エラー] build が失敗しました。
    goto :fail
)

echo.
echo ==============================================
echo  セットアップと確認がすべて完了しました
echo ==============================================
echo 起動: scripts\start_windows.bat
if /i not "%NOPAUSE%"=="nopause" pause
exit /b 0

:fail
echo.
echo セットアップを中止しました。上のメッセージを確認してください。
if /i not "%NOPAUSE%"=="nopause" pause
exit /b 1
