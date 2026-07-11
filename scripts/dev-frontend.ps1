# フロントエンド開発サーバー起動(Windows PowerShell)
# 事前に frontend/ で npm install を実行しておくこと
Set-Location -Path (Join-Path $PSScriptRoot "..\frontend")
npm run dev
