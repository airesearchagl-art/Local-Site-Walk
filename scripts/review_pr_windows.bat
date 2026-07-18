@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Local Site Walk - PR確認

rem このスクリプトが対象とする想定リポジトリ(HTTPS)
set "REPO_URL=https://github.com/airesearchagl-art/Local-Site-Walk.git"

rem リポジトリルート = このBATの1つ上のフォルダ
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
cd /d "%ROOT%"

echo ==============================================
echo  Local Site Walk PR確認
echo ==============================================

rem --- 引数の確認 ---
set "PR_NUM=%~1"
if not defined PR_NUM (
    echo 使い方: scripts\review_pr_windows.bat PR番号
    echo 例:     scripts\review_pr_windows.bat 2
    goto :fail
)
echo %PR_NUM%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo [エラー] PR番号は数字で指定してください。
    goto :fail
)
set "PR_BRANCH=pr/%PR_NUM%"

rem --- Git リポジトリであることを確認 ---
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [エラー] Gitリポジトリではありません: "%ROOT%"
    goto :fail
)

rem --- remote origin の検証(想定リポジトリ以外では実行しない)---
set "CURRENT_URL="
for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do set "CURRENT_URL=%%u"
if not defined CURRENT_URL (
    echo [エラー] remote origin が設定されていません。中止します。
    goto :fail
)
set "URL_A=!CURRENT_URL!"
if /i "!URL_A:~-4!"==".git" set "URL_A=!URL_A:~0,-4!"
set "URL_B=%REPO_URL%"
if /i "!URL_B:~-4!"==".git" set "URL_B=!URL_B:~0,-4!"
if /i not "!URL_A!"=="!URL_B!" (
    echo [エラー] remote origin が想定リポジトリと一致しないため中止します。
    echo   現在: !CURRENT_URL!
    echo   想定: %REPO_URL%
    goto :fail
)

rem --- 未commit変更の保護 ---
set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo [中止] 未commitの変更があります。上書きを避けるため中止します。
    echo 変更内容を確認し、commit または退避してから再実行してください。
    goto :fail
)

rem --- PR内容の取得(ブランチ名を知らなくてもPR番号だけで取得できる)---
echo PR #%PR_NUM% を取得します...
git fetch origin "pull/%PR_NUM%/head"
if errorlevel 1 (
    echo [エラー] PR #%PR_NUM% を取得できませんでした。
    echo PR番号が正しいか、ネットワークに接続できているかを確認してください。
    goto :fail
)

echo.
echo --- 現在のLOCAL ---
git log --oneline -1 HEAD
echo --- PR #%PR_NUM% のREMOTE ---
git log --oneline -1 FETCH_HEAD
echo.

rem --- レビュー用ブランチ pr/N 上の独自commitを保護 ---
git rev-parse --verify --quiet "%PR_BRANCH%" >nul 2>&1
if not errorlevel 1 (
    set "LOCAL_ONLY="
    for /f "delims=" %%c in ('git log --oneline "FETCH_HEAD..%PR_BRANCH%" 2^>nul') do set "LOCAL_ONLY=1"
    if defined LOCAL_ONLY (
        echo [中止] ローカルの %PR_BRANCH% にPRへ含まれないcommitがあります。
        echo 上書きを避けるため中止します。内容を確認して退避してください。
        goto :fail
    )
)

rem --- レビュー用ブランチへ切替。pr/N はPR内容を映す確認専用ブランチ ---
git switch -C "%PR_BRANCH%" FETCH_HEAD
if errorlevel 1 (
    echo [エラー] ブランチの切替に失敗しました。
    goto :fail
)
echo [OK] %PR_BRANCH% に切り替えました。
git log --oneline -1 HEAD

rem --- セットアップと起動。PRのコードを実行するため事前に確認を取る ---
echo.
echo この後、取り込んだPRのコードで依存関係の導入とcheckを実行します。
echo 内容を信頼できるPRであることを確認してから進めてください。
set "GO="
set /p "GO=セットアップと起動を続けますか? [Y/N]: "
if /i not "!GO!"=="Y" (
    echo セットアップは実行せず終了します。ブランチは %PR_BRANCH% のままです。
    goto :fail
)
echo セットアップと動作確認を実行します...
call "%ROOT%\scripts\setup_windows.bat" nopause
if errorlevel 1 (
    echo [エラー] セットアップに失敗しました。
    goto :fail
)

echo アプリを起動します...
call "%ROOT%\scripts\start_windows.bat"

echo.
echo PR確認を終えたら、元のブランチへ戻ってください。
echo 例: git switch main
pause
exit /b 0

:fail
echo.
echo 処理を中止しました。上のメッセージを確認してください。
pause
exit /b 1
