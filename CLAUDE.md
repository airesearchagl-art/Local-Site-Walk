# Local Site Walk

## 目的

既存の360°動画を外部クラウドへ送信せず、ローカルPC・社内ネットワーク内で
処理・保存し、関係者が敷地・現場状況を閲覧できるアプリを作る。
初期は寸法精度より「見た目と閲覧性」を優先する。

## 絶対的な方針

- ローカル・社内完結を最優先。外部クラウドへ360°映像・現場データを送信しない
- 原動画・抽出フレーム・Gaussian Splat・PLY・DB等の大容量/生成データをGitへ追加しない
- APIキー・トークン・個人情報をリポジトリへ保存しない(`.env`はGit管理外)
- `main`へ直接commitしない。作業ブランチ→PR
- 不明な仕様を推測で拡張しない。未実装機能を実装済みに見せない

## ディレクトリ

- `frontend/` — React + TypeScript + Vite
- `backend/` — Python + FastAPI
- `docs/` — 簡潔なドキュメント
- `scripts/` — 開発補助スクリプト
- `sample-data/` — ダミーメタデータのみ(実動画は置かない)
- 実データは既定で `<ホーム>/LocalSiteWalkData`(環境変数 `LSW_DATA_DIR` で変更)

## コマンド

### backend(`backend/` で実行)

- 初回: `python -m venv .venv` → activate → `pip install -r requirements-dev.txt`
- 起動: `uvicorn app.main:app --reload --port 8000`
- lint: `ruff check .`
- test: `pytest`

### frontend(`frontend/` で実行)

- 初回: `npm install`
- 起動: `npm run dev`(http://localhost:5173、`/api`は8000へプロキシ)
- lint: `npm run lint` / 型: `npm run typecheck` / build: `npm run build`

## サブエージェントの使い分け

- `repo-explorer` — 構造調査・関連ファイル特定(read-only、要約のみ返す)
- `test-runner` — lint/型/テスト/build/起動確認の実行と要点整理(実装編集禁止)
- `security-reviewer` — 実装完了後のセキュリティレビュー(read-only)

小さな作業を過剰分割しない。同じファイルを複数エージェントに重複して読ませない。

## 作業完了時の報告項目

ブランチ / commit / 変更ファイル / 実行したchecksと結果 /
未実行の確認とその理由 / セキュリティ上の確認 / 次の推奨タスク
