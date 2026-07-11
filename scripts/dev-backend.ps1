# バックエンド開発サーバー起動(Windows PowerShell)
# 事前に backend/.venv を作成し、requirements-dev.txt をインストールしておくこと
Set-Location -Path (Join-Path $PSScriptRoot "..\backend")
& ".venv\Scripts\Activate.ps1"
uvicorn app.main:app --reload --port 8000
