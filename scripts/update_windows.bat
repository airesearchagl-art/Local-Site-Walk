@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Local Site Walk - 更新

rem このスクリプトが更新対象とする想定リポジトリ(HTTPS)
set "REPO_URL=https://github.com/airesearchagl-art/Local-Site-Walk.git"

rem リポジトリルート = このBATの1つ上のフォルダ
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
cd /d "%ROOT%"

echo ==============================================
echo  Local Site Walk 更新
echo ==============================================

rem --- Git リポジトリであることを確認 ---
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [エラー] Gitリポジトリではありません: "%ROOT%"
    goto :fail
)

echo --- remote ---
git remote -v
echo.
echo --- 現在のブランチ ---
git branch --show-current
echo.

rem --- remote origin の検証(想定リポジトリ以外は更新しない)---
set "CURRENT_URL="
for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do set "CURRENT_URL=%%u"
if not defined CURRENT_URL (
    echo [エラー] remote origin が設定されていません。中止します。
    goto :fail
)
rem 末尾 .git の有無を正規化して比較(bootstrap_local_site_walk.bat と同じ判定基準)
set "URL_A=!CURRENT_URL!"
if /i "!URL_A:~-4!"==".git" set "URL_A=!URL_A:~0,-4!"
set "URL_B=%REPO_URL%"
if /i "!URL_B:~-4!"==".git" set "URL_B=!URL_B:~0,-4!"
if /i not "!URL_A!"=="!URL_B!" (
    echo [エラー] remote origin が想定リポジトリと一致しないため中止します。
    echo   現在: !CURRENT_URL!
    echo   想定: %REPO_URL%
    echo   ※SSH形式のURLはこのスクリプトの対象外です。HTTPSのURLをご利用いただくか、
    echo     手動で git fetch と fast-forward merge を実行してください。
    goto :fail
)
echo [OK] remote origin は想定リポジトリと一致しています。
echo.

rem --- 未commit変更の保護 ---
set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo [中止] 未commitの変更があるため、自動更新は行いません。
    echo 変更内容を確認し、commit または退避してから再実行してください。
    echo 参考: git status
    goto :fail
)

echo git fetch を実行します...
git fetch origin
if errorlevel 1 (
    echo [エラー] fetch に失敗しました。ネットワークを確認してください。
    goto :fail
)

echo.
echo --- upstream との状態 ---
git status -sb
echo.

rem --- upstream が未設定なら表示のみで終了 ---
git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>&1
if errorlevel 1 (
    echo upstream が設定されていないため、自動更新は行いません。
    echo 取得（fetch）までは完了しています。
    goto :done
)

rem --- fast-forward できる場合だけ更新(merge/rebase/reset は行わない)---
git merge --ff-only @{u}
if errorlevel 1 (
    echo [情報] fast-forward できないため、自動更新は行いませんでした。
    echo ローカルとremoteの履歴が分岐しています。状況を確認して手動で対応してください。
    goto :done
)
echo [OK] 最新の状態に更新しました。

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
