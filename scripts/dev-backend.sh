#!/usr/bin/env bash
# バックエンド開発サーバー起動(macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")/../backend"
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
