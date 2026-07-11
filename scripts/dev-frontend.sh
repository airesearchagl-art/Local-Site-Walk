#!/usr/bin/env bash
# フロントエンド開発サーバー起動(macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm run dev
