@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Local Site Walk - 更新

rem Expected repository this script updates (HTTPS)
set "REPO_URL=https://github.com/airesearchagl-art/Local-Site-Walk.git"
rem Always targets main (not the current branch's upstream)
set "MAIN_BRANCH=main"

rem Repo root = one folder above this BAT
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
cd /d "%ROOT%"

echo ==============================================
echo  Local Site Walk 更新
echo ==============================================

rem --- Check this is a Git repository ---
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [エラー] Gitリポジトリではありません: "%ROOT%"
    goto :fail
)

echo --- remote ---
git remote -v
echo.
echo --- 現在のブランチ ---
set "CUR_BRANCH="
for /f "delims=" %%b in ('git branch --show-current') do set "CUR_BRANCH=%%b"
echo %CUR_BRANCH%
echo.

rem --- Validate remote origin (do not update unless it matches) ---
set "CURRENT_URL="
for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do set "CURRENT_URL=%%u"
if not defined CURRENT_URL (
    echo [エラー] remote origin が設定されていません。中止します。
    goto :fail
)
rem Normalize trailing .git before comparing (same rule as bootstrap_local_site_walk.bat)
set "URL_A=!CURRENT_URL!"
if /i "!URL_A:~-4!"==".git" set "URL_A=!URL_A:~0,-4!"
set "URL_B=%REPO_URL%"
if /i "!URL_B:~-4!"==".git" set "URL_B=!URL_B:~0,-4!"
if /i not "!URL_A!"=="!URL_B!" (
    echo [エラー] remote origin が想定リポジトリと一致しないため中止します。
    echo   現在: !CURRENT_URL!
    echo   想定: %REPO_URL%
    type "%~dp0update_ssh_unsupported_message.txt"
    goto :fail
)
echo [OK] remote origin は想定リポジトリと一致しています。
echo.

rem --- Protect uncommitted changes ---
set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    type "%~dp0update_dirty_message.txt"
    goto :fail
)

echo git fetch を実行します...
git fetch origin
if errorlevel 1 (
    echo [エラー] fetch に失敗しました。ネットワークを確認してください。
    goto :fail
)

rem --- Check origin/main exists ---
git rev-parse --verify --quiet "origin/%MAIN_BRANCH%" >nul 2>&1
if errorlevel 1 (
    echo [エラー] origin/%MAIN_BRANCH% が見つかりません。中止します。
    goto :fail
)

if /i "%CUR_BRANCH%"=="%MAIN_BRANCH%" goto :update_main

rem --- On a branch other than main: show status and confirm before switching ---
echo.
type "%~dp0update_branch_switch_message.txt"
echo 現在のブランチ:
git log --oneline -1 HEAD
echo origin/%MAIN_BRANCH% の最新:
git log --oneline -1 "origin/%MAIN_BRANCH%"
echo.
set "SWITCH="
set /p "SWITCH=main へ切り替えて更新しますか? [Y/N]: "
if /i not "!SWITCH!"=="Y" (
    echo mainへの切り替えは行いませんでした。fetchのみ完了しています。
    goto :done
)

git rev-parse --verify --quiet "%MAIN_BRANCH%" >nul 2>&1
if errorlevel 1 (
    git switch -c "%MAIN_BRANCH%" --track "origin/%MAIN_BRANCH%"
) else (
    git switch "%MAIN_BRANCH%"
)
if errorlevel 1 (
    echo [エラー] main への切り替えに失敗しました。
    goto :fail
)

:update_main
rem --- Update only if fast-forward is possible (no merge/rebase/reset) ---
git merge --ff-only "origin/%MAIN_BRANCH%"
if errorlevel 1 (
    type "%~dp0update_diverged_message.txt"
    goto :done
)
echo [OK] main を最新の状態に更新しました。

echo.
set "RUN_SETUP="
set /p "RUN_SETUP=依存関係の再セットアップを実行しますか? [Y/N]: "
if /i "!RUN_SETUP!"=="Y" (
    call "%ROOT%\scripts\setup_windows.bat" nopause
    if errorlevel 1 (
        echo [エラー] 再セットアップに失敗しました。
        goto :fail
    )
)

:done
echo.
echo 更新処理を終了します。
pause
exit /b 0

:fail
echo.
echo 処理を中止しました。上のメッセージを確認してください。
pause
exit /b 1
