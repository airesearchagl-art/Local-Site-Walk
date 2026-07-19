@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem chcp 65001 (UTF-8) is needed so "type" below renders the UTF-8
rem Japanese message .txt files correctly. This BAT's own body is
rem ASCII-only, so chcp does not affect how cmd.exe parses it.
chcp 65001 >nul
title Local Site Walk - PR Review

rem Repo root = one folder above this BAT. Computed first so it is
rem available in both the normal path and the __continue__ re-exec path.
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
cd /d "%ROOT%"

rem --- Re-entry after "git switch" below. See the comment at the
rem     "git switch -C" call for why this re-exec exists. ---
if /i "%~1"=="__continue__" (
    set "PR_NUM=%~2"
    set "PR_BRANCH=pr/%PR_NUM%"
    goto :post_switch
)

rem Expected repository (owner/repo, compared after normalizing any
rem of: https://.../repo.git, https://.../repo, git@host:repo.git,
rem ssh://git@host/repo.git)
set "EXPECTED_REPO=airesearchagl-art/Local-Site-Walk"

echo ==============================================
echo  Local Site Walk - PR Review
echo ==============================================

rem --- Check the argument ---
set "PR_NUM=%~1"
if not defined PR_NUM (
    type "%~dp0review_pr_usage_message.txt"
    goto :fail
)
echo %PR_NUM%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo [ERROR] The PR number must be numeric.
    goto :fail
)
set "PR_BRANCH=pr/%PR_NUM%"

rem --- Check this is a Git repository ---
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Not a Git repository: "%ROOT%"
    goto :fail
)

rem --- Validate remote origin (normalize owner/repo, accept https/ssh) ---
set "CURRENT_URL="
for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do set "CURRENT_URL=%%u"
if not defined CURRENT_URL (
    echo [ERROR] remote "origin" is not set. Aborting.
    goto :fail
)
set "URL_NORM=!CURRENT_URL!"
if /i "!URL_NORM:~-4!"==".git" set "URL_NORM=!URL_NORM:~0,-4!"
set "URL_NORM=!URL_NORM:ssh://git@github.com/=!"
set "URL_NORM=!URL_NORM:git@github.com:=!"
set "URL_NORM=!URL_NORM:https://github.com/=!"
set "URL_NORM=!URL_NORM:http://github.com/=!"
if /i not "!URL_NORM!"=="!EXPECTED_REPO!" (
    type "%~dp0review_pr_origin_mismatch_message.txt"
    echo Current : !CURRENT_URL!
    echo Expected: !EXPECTED_REPO! on github.com
    goto :fail
)

rem --- Protect uncommitted changes ---
set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    type "%~dp0review_pr_dirty_message.txt"
    goto :fail
)

rem --- Fetch the PR (no need to know the branch name, only the PR number) ---
echo Fetching PR #%PR_NUM% ...
git fetch origin "refs/pull/%PR_NUM%/head"
if errorlevel 1 (
    echo [ERROR] Could not fetch PR #%PR_NUM%.
    echo Check the PR number and your network connection.
    goto :fail
)

echo.
echo --- current LOCAL ---
git log --oneline -1 HEAD
echo --- PR #%PR_NUM% REMOTE ---
git log --oneline -1 FETCH_HEAD
echo.

rem --- Protect commits on the review branch pr/N that are not in the PR ---
git rev-parse --verify --quiet "%PR_BRANCH%" >nul 2>&1
if not errorlevel 1 (
    set "LOCAL_ONLY="
    for /f "delims=" %%c in ('git log --oneline "FETCH_HEAD..%PR_BRANCH%" 2^>nul') do set "LOCAL_ONLY=1"
    if defined LOCAL_ONLY (
        echo [ABORT] Local %PR_BRANCH% has commits not contained in the PR.
        echo Aborting to avoid overwriting them. Check and back them up first.
        goto :fail
    )
)

rem --- Switch to the review branch. pr/N mirrors the PR for review only.
rem
rem   IMPORTANT: this BAT file lives inside the repository, so "git switch"
rem   below can overwrite THIS VERY FILE on disk with whatever version the
rem   PR contains. cmd.exe reads .bat files incrementally from disk rather
rem   than loading the whole script into memory first, so continuing to
rem   execute inline past this point would read stale/misaligned bytes of
rem   the NEW file at the OLD file's read position - producing garbage
rem   commands (this is what previously caused a bare "id" to be run and
rem   reported as "not recognized"). To avoid that, this script exits and
rem   re-launches itself in a brand-new cmd.exe process, which opens and
rem   reads whatever is now actually on disk from a clean, fresh position.
git switch -C "%PR_BRANCH%" FETCH_HEAD
if errorlevel 1 (
    echo [ERROR] Could not switch branch.
    goto :fail
)
cmd /c "%~f0" __continue__ "%PR_NUM%"
exit /b %errorlevel%

:post_switch
echo [OK] Switched to %PR_BRANCH%.
git log --oneline -1 HEAD

rem --- Setup and start. Confirm before running the fetched PR code ---
echo.
type "%~dp0review_pr_confirm_message.txt"
choice /c YN /n /m "Continue with setup and start? [Y/N]: "
if errorlevel 2 (
    echo Not running setup. Branch remains %PR_BRANCH%.
    goto :fail
)
echo Running setup and checks ...
call "%ROOT%\scripts\setup_windows.bat" nopause
if errorlevel 1 (
    echo [ERROR] Setup failed.
    goto :fail
)

echo Starting the app ...
call "%ROOT%\scripts\start_windows.bat"
if errorlevel 1 (
    echo [ERROR] start_windows.bat failed.
    goto :fail
)

echo.
type "%~dp0review_pr_done_message.txt"
pause
exit /b 0

:fail
echo.
echo Aborted. See the messages above for details.
pause
exit /b 1
