@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem chcp 65001 (UTF-8) is needed so the "type" command below renders
rem the UTF-8 Japanese message .txt files correctly. This BAT's own
rem body is ASCII-only, so chcp does not affect how cmd.exe parses it.
chcp 65001 >nul
title Local Site Walk - Bootstrap

rem Expected repository (owner/repo, compared after normalizing any
rem of: https://.../repo.git, https://.../repo, git@host:repo.git,
rem ssh://git@host/repo.git)
set "EXPECTED_REPO=airesearchagl-art/Local-Site-Walk"
set "REPO_URL=https://github.com/airesearchagl-art/Local-Site-Walk.git"
set "PARENT_DIR=%USERPROFILE%\.claude\projects"
set "TARGET_DIR=%PARENT_DIR%\Local Site Walk"

echo ==============================================
echo  Local Site Walk - Bootstrap
echo ==============================================
echo Clone destination: "%TARGET_DIR%"
echo.

rem --- 1. Check Git is installed ---
git --version >nul 2>&1
if errorlevel 1 (
    type "%~dp0bootstrap_git_missing_message.txt"
    goto :fail
)
echo [OK] Git found.

rem --- 2. Create parent folder ---
if not exist "%PARENT_DIR%" (
    echo Creating folder: "%PARENT_DIR%"
    mkdir "%PARENT_DIR%"
    if errorlevel 1 (
        echo [ERROR] Could not create the folder.
        goto :fail
    )
)

rem --- 3. Check clone destination state ---
if exist "%TARGET_DIR%\.git" goto :existing_repo
if exist "%TARGET_DIR%" (
    type "%~dp0bootstrap_existing_not_git_message.txt"
    goto :fail
)

echo Cloning the repository...
git clone "%REPO_URL%" "%TARGET_DIR%"
if errorlevel 1 (
    echo [ERROR] Clone failed. Check your network and repository access.
    goto :fail
)
echo [OK] Clone complete.
goto :run_setup

:existing_repo
echo Existing repository found. Skipping clone.

rem --- Validate remote origin (normalize owner/repo, accept https/ssh) ---
set "CURRENT_URL="
for /f "delims=" %%u in ('git -C "%TARGET_DIR%" remote get-url origin 2^>nul') do set "CURRENT_URL=%%u"
if not defined CURRENT_URL (
    echo [ERROR] Could not read the "origin" remote. Aborting.
    goto :fail
)
set "URL_NORM=!CURRENT_URL!"
if /i "!URL_NORM:~-4!"==".git" set "URL_NORM=!URL_NORM:~0,-4!"
set "URL_NORM=!URL_NORM:ssh://git@github.com/=!"
set "URL_NORM=!URL_NORM:git@github.com:=!"
set "URL_NORM=!URL_NORM:https://github.com/=!"
set "URL_NORM=!URL_NORM:http://github.com/=!"
if /i not "!URL_NORM!"=="!EXPECTED_REPO!" (
    type "%~dp0bootstrap_origin_mismatch_message.txt"
    echo Current : !CURRENT_URL!
    echo Expected: !EXPECTED_REPO! on github.com
    goto :fail
)
echo [OK] origin matches the expected repository.

rem --- Check for uncommitted changes (prevent overwrite) ---
set "DIRTY="
for /f "delims=" %%s in ('git -C "%TARGET_DIR%" status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    type "%~dp0bootstrap_dirty_message.txt"
    goto :fail
)
echo [OK] No uncommitted changes. Not pulling automatically.

:run_setup
echo.
echo Starting setup...
call "%TARGET_DIR%\scripts\setup_windows.bat" nopause
if errorlevel 1 (
    echo [ERROR] Setup failed. Check the messages above.
    goto :fail
)

echo.
set "START_NOW="
set /p "START_NOW=Start the app now? [Y/N]: "
if /i "!START_NOW!"=="Y" (
    call "%TARGET_DIR%\scripts\start_windows.bat"
    if errorlevel 1 (
        echo [ERROR] start_windows.bat failed. Check the messages above.
        goto :fail
    )
)

echo.
type "%~dp0bootstrap_done_message.txt"
pause
exit /b 0

:fail
echo.
echo Aborted. See the messages above for details.
pause
exit /b 1
