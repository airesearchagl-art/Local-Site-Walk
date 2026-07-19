# scripts

開発・運用補助スクリプトです。用途に応じて使い分けてください。

## Windows利用者向け(BAT)

| ファイル | 用途 |
| --- | --- |
| `..\bootstrap_local_site_walk.bat` | 初回導入の入口。clone→セットアップ→起動確認(clone前に単体取得して使う) |
| `setup_windows.bat` | 依存関係の導入と動作確認。何度実行しても既存環境を壊さない |
| `start_windows.bat` | backend/frontendを別ウィンドウで起動しブラウザを開く(日常起動用) |
| `update_windows.bat` | 安全な更新。未commit変更があれば中止、fast-forward可能な場合のみ更新 |
| `review_pr_windows.bat <PR番号>` | PR確認の1コマンド化。fetch→`pr/<番号>`へ切替→setup→起動 |
| `diagnose_windows.bat` | 環境診断。Git/Python/Node/ポート/データフォルダ等の状態表示 |

BATはGit・Python・Node.js本体を自動インストールしません(存在確認と案内のみ)。

## 開発者向け(PowerShell / bash)

| ファイル | 用途 |
| --- | --- |
| `dev-backend.ps1` / `dev-backend.sh` | backendのみを現在のターミナルで起動(開発用) |
| `dev-frontend.ps1` / `dev-frontend.sh` | frontendのみを現在のターミナルで起動(開発用) |
