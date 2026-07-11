@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Local Site Walk - 環境診断

rem リポジトリルート = このBATの1つ上のフォルダ
for %%i in ("%~dp0..") do set "ROOT=%%~fi"

echo ==============================================
echo  Local Site Walk 環境診断
echo ==============================================
echo 対象: "%ROOT%"
echo ※APIキー・トークン等の機密情報や環境変数一覧は表示しません。

echo.
echo --- Windows ---
ver

echo.
echo --- Git ---
git --version 2>nul || echo Git が見つかりません
git -C "%ROOT%" remote -v 2>nul
echo 現在のブランチ:
git -C "%ROOT%" branch --show-current 2>nul
echo 未commit変更（表示がなければクリーン）:
git -C "%ROOT%" status --short 2>nul

echo.
echo --- Python ---
py -3 --version 2>nul || python --version 2>nul || echo Python が見つかりません

echo.
echo --- Node.js / npm ---
node --version 2>nul || echo Node.js が見つかりません
call npm --version 2>nul || echo npm が見つかりません

echo.
echo --- FFmpeg（将来の動画処理用。現段階では必須ではありません）---
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo FFmpeg は見つかりませんでした（現段階では不要）
) else (
    for /f "delims=" %%v in ('ffmpeg -version 2^>nul ^| findstr /b /c:"ffmpeg version"') do echo %%v
)

echo.
echo --- セットアップ状態 ---
if exist "%ROOT%\backend\.venv\Scripts\python.exe" (echo backend\.venv : あり) else (echo backend\.venv : なし ※scripts\setup_windows.bat を実行してください)
if exist "%ROOT%\frontend\node_modules" (echo frontend\node_modules : あり) else (echo frontend\node_modules : なし ※scripts\setup_windows.bat を実行してください)
if exist "%ROOT%\.env" (echo .env : あり) else (echo .env : なし ※任意。既定値で動作します)

echo.
echo --- 主要設定ファイル ---
for %%f in ("backend\requirements.txt" "backend\requirements-dev.txt" "backend\app\main.py" "backend\pyproject.toml" "frontend\package.json" "frontend\vite.config.ts" ".env.example") do (
    if exist "%ROOT%\%%~f" (echo %%~f : あり) else (echo %%~f : 見つかりません)
)

echo.
echo --- ポート使用状況（backend:8000 / frontend:5173）---
netstat -ano 2>nul | findstr /c:":8000 " | findstr "LISTENING"
if errorlevel 1 echo ポート8000 : 未使用
netstat -ano 2>nul | findstr /c:":5173 " | findstr "LISTENING"
if errorlevel 1 echo ポート5173 : 未使用

echo.
echo --- データ保存先 ---
if defined LSW_DATA_DIR (echo LSW_DATA_DIR : %LSW_DATA_DIR%) else (echo LSW_DATA_DIR : 未設定 ※既定値を使用します)
if exist "%USERPROFILE%\LocalSiteWalkData" (echo 既定データフォルダ %%USERPROFILE%%\LocalSiteWalkData : あり) else (echo 既定データフォルダ %%USERPROFILE%%\LocalSiteWalkData : なし ※setup_windows.bat が作成します)

echo.
echo 診断は以上です。
pause
exit /b 0
