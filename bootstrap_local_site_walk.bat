@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Local Site Walk - 初回導入

set "REPO_URL=https://github.com/airesearchagl-art/Local-Site-Walk.git"
set "PARENT_DIR=%USERPROFILE%\.claude\projects"
set "TARGET_DIR=%PARENT_DIR%\Local Site Walk"

echo ==============================================
echo  Local Site Walk 初回導入（bootstrap）
echo ==============================================
echo clone先: "%TARGET_DIR%"
echo.

rem --- 1. Git の存在確認 ---
git --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Git が見つかりません。
    echo Git for Windows を手動でインストールしてから再実行してください。
    echo このスクリプトはインストーラーを自動取得しません。
    goto :fail
)
echo [OK] Git を確認しました。

rem --- 2. 親フォルダの作成 ---
if not exist "%PARENT_DIR%" (
    echo フォルダを作成します: "%PARENT_DIR%"
    mkdir "%PARENT_DIR%"
    if errorlevel 1 (
        echo [エラー] フォルダを作成できませんでした。
        goto :fail
    )
)

rem --- 3. clone 先の状態確認 ---
if exist "%TARGET_DIR%\.git" goto :existing_repo
if exist "%TARGET_DIR%" (
    echo [エラー] clone先フォルダは存在しますが、Gitリポジトリではありません。
    echo 中身を確認して手動で対応してください。このスクリプトは削除を行いません。
    goto :fail
)

echo リポジトリを clone します...
git clone "%REPO_URL%" "%TARGET_DIR%"
if errorlevel 1 (
    echo [エラー] clone に失敗しました。ネットワークとリポジトリへのアクセス権を確認してください。
    goto :fail
)
echo [OK] clone が完了しました。
goto :run_setup

:existing_repo
echo 既存のリポジトリが見つかりました。clone はスキップします。

rem remote URL の確認（末尾 .git の有無は無視して比較）
set "CURRENT_URL="
for /f "delims=" %%u in ('git -C "%TARGET_DIR%" remote get-url origin 2^>nul') do set "CURRENT_URL=%%u"
if not defined CURRENT_URL (
    echo [エラー] remote origin を取得できませんでした。中止します。
    goto :fail
)
set "URL_A=!CURRENT_URL!"
if /i "!URL_A:~-4!"==".git" set "URL_A=!URL_A:~0,-4!"
set "URL_B=%REPO_URL%"
if /i "!URL_B:~-4!"==".git" set "URL_B=!URL_B:~0,-4!"
if /i not "!URL_A!"=="!URL_B!" (
    echo [エラー] remote が想定リポジトリと異なるため中止します。
    echo   現在: !CURRENT_URL!
    echo   想定: %REPO_URL%
    goto :fail
)
echo [OK] remote は想定リポジトリと一致しています。

rem 未commit変更の確認（上書き防止）
set "DIRTY="
for /f "delims=" %%s in ('git -C "%TARGET_DIR%" status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo [エラー] 未commitの変更があるため中止します。pull や上書きは行いません。
    echo 変更内容を確認してから、更新には scripts\update_windows.bat を使用してください。
    goto :fail
)
echo [OK] 未commit変更はありません。pull は自動実行しません。

:run_setup
echo.
echo セットアップを開始します...
call "%TARGET_DIR%\scripts\setup_windows.bat" nopause
if errorlevel 1 (
    echo [エラー] セットアップに失敗しました。上のメッセージを確認してください。
    goto :fail
)

echo.
set "START_NOW="
set /p "START_NOW=アプリを起動しますか? [Y/N]: "
if /i "!START_NOW!"=="Y" call "%TARGET_DIR%\scripts\start_windows.bat"

echo.
echo 初回導入が完了しました。
echo 次回以降の起動: scripts\start_windows.bat
echo 更新: scripts\update_windows.bat  ／  診断: scripts\diagnose_windows.bat
pause
exit /b 0

:fail
echo.
echo 処理を中止しました。上のメッセージを確認して対応してください。
pause
exit /b 1
