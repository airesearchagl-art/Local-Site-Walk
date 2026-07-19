@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem chcp 65001 (UTF-8) is needed so "type" below renders the UTF-8
rem Japanese message .txt files correctly. This BAT's own body is
rem ASCII-only, so chcp does not affect how cmd.exe parses it.
chcp 65001 >nul
title Local Site Walk - Update

rem Expected repository (owner/repo, compared after normalizing any
rem of: https://.../repo.git, https://.../repo, git@host:repo.git,
rem ssh://git@host/repo.git)
set "EXPECTED_REPO=airesearchagl-art/Local-Site-Walk"
rem Always targets main (not the current branch's upstream)
set "MAIN_BRANCH=main"

rem Repo root = one folder above this BAT. These are set unconditionally,
rem before the re-entry check below, so they are available in both the
rem normal path and any __continue_*__ re-exec path.
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
cd /d "%ROOT%"

rem --- Re-entry after "git switch"/"git merge" below. See the comments
rem     at those calls for why this re-exec exists. ---
if /i "%~1"=="__continue_after_switch__" goto :do_merge
if /i "%~1"=="__continue_after_merge__" goto :post_update

echo ==============================================
echo  Local Site Walk - Update
echo ==============================================

rem --- Check this is a Git repository ---
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Not a Git repository: "%ROOT%"
    goto :fail
)

echo --- remote ---
git remote -v
echo.
echo --- current branch ---
set "CUR_BRANCH="
for /f "delims=" %%b in ('git branch --show-current') do set "CUR_BRANCH=%%b"
echo %CUR_BRANCH%
echo.

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
    type "%~dp0update_origin_mismatch_message.txt"
    echo Current : !CURRENT_URL!
    echo Expected: !EXPECTED_REPO! on github.com
    goto :fail
)
echo [OK] origin matches the expected repository.
echo.

rem --- Protect uncommitted changes ---
set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    type "%~dp0update_dirty_message.txt"
    goto :fail
)

echo Running git fetch ...
git fetch origin
if errorlevel 1 (
    echo [ERROR] fetch failed. Check your network connection.
    goto :fail
)

rem --- Check origin/main exists ---
git rev-parse --verify --quiet "origin/%MAIN_BRANCH%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] origin/%MAIN_BRANCH% not found. Aborting.
    goto :fail
)

rem --- Ensure a local main branch exists, tracking origin/main.
rem     "git branch" (no checkout) never touches the working tree, so it
rem     cannot overwrite this running script; no re-exec needed here. ---
git rev-parse --verify --quiet "%MAIN_BRANCH%" >nul 2>&1
if errorlevel 1 (
    git branch "%MAIN_BRANCH%" "origin/%MAIN_BRANCH%"
    if errorlevel 1 (
        echo [ERROR] Could not create local %MAIN_BRANCH% from origin/%MAIN_BRANCH%.
        goto :fail
    )
)

rem --- Ahead/behind check: local main vs origin/main ---
rem left  = commits only on local main  (AHEAD)
rem right = commits only on origin/main (BEHIND)
set "AHEAD="
set "BEHIND="
for /f "tokens=1,2" %%a in ('git rev-list --left-right --count "%MAIN_BRANCH%...origin/%MAIN_BRANCH%"') do (
    set "AHEAD=%%a"
    set "BEHIND=%%b"
)
if not defined AHEAD set "AHEAD=0"
if not defined BEHIND set "BEHIND=0"
echo main ahead of origin/main : !AHEAD! commit(s)
echo main behind origin/main   : !BEHIND! commit(s)
echo.

if not "!AHEAD!"=="0" (
    if "!BEHIND!"=="0" (
        type "%~dp0update_local_ahead_message.txt"
        goto :done
    )
    if not "!BEHIND!"=="0" (
        type "%~dp0update_diverged_message.txt"
        goto :done
    )
)

rem --- At this point AHEAD is 0: fast-forward is always safe ---
if /i "%CUR_BRANCH%"=="%MAIN_BRANCH%" goto :do_merge

rem --- On a branch other than main: show status and confirm before switching ---
type "%~dp0update_branch_switch_message.txt"
echo Current HEAD:
git log --oneline -1 HEAD
echo origin/%MAIN_BRANCH% latest:
git log --oneline -1 "origin/%MAIN_BRANCH%"
echo.
choice /c YN /n /m "Switch to main and update it? [Y/N]: "
if errorlevel 2 (
    echo Not switching to main. Fetch is complete.
    goto :done
)

rem   IMPORTANT: this BAT file lives inside the repository, so "git switch"
rem   can overwrite THIS VERY FILE on disk with main's version of it.
rem   cmd.exe reads .bat files incrementally from disk rather than loading
rem   the whole script into memory first, so continuing to execute inline
rem   past this point could read stale/misaligned bytes at the old file's
rem   read position. To avoid that, re-launch in a brand-new cmd.exe
rem   process, which opens and reads whatever is now actually on disk.
git switch "%MAIN_BRANCH%"
if errorlevel 1 (
    echo [ERROR] Could not switch to %MAIN_BRANCH%.
    goto :fail
)
rem   The outer pair of quotes below is required by cmd.exe's own /C
rem   argument parsing: see the identical comment in review_pr_windows.bat
rem   next to its own "cmd /c" call for the full explanation.
cmd /c ""%~f0" __continue_after_switch__"
exit /b %errorlevel%

:do_merge
rem --- Update only if fast-forward is possible (no merge/rebase/reset).
rem     This can ALSO overwrite this running file (main advancing changes
rem     its own content), so it gets the same re-exec treatment below. ---
git merge --ff-only "origin/%MAIN_BRANCH%"
if errorlevel 1 (
    type "%~dp0update_diverged_message.txt"
    goto :done
)
rem   Same /C quoting reason as the switch re-exec above.
cmd /c ""%~f0" __continue_after_merge__"
exit /b %errorlevel%

:post_update
echo [OK] main updated:
git log --oneline -1 HEAD

echo.
choice /c YN /n /m "Reinstall dependencies now? [Y/N]: "
if not errorlevel 2 (
    call "%ROOT%\scripts\setup_windows.bat" nopause
    if errorlevel 1 (
        echo [ERROR] Setup failed.
        goto :fail
    )
)

echo.
choice /c YN /n /m "Start the app now? [Y/N]: "
if not errorlevel 2 (
    call "%ROOT%\scripts\start_windows.bat"
    if errorlevel 1 (
        echo [ERROR] start_windows.bat failed.
        goto :fail
    )
)

:done
echo.
echo Update finished.
pause
exit /b 0

:fail
echo.
echo Aborted. See the messages above for details.
pause
exit /b 1
