# Local Site Walk

既存の360°動画を**外部クラウドへ送信せず**、ローカルPCまたは社内ネットワーク内で
処理・保存し、関係者が敷地・現場状況を閲覧できるようにするアプリケーションです。
初期段階では寸法計測の正確さより、見た目と閲覧性を優先します。

## 現在のMVP範囲

- FastAPIバックエンド: `GET /api/health`、`GET /api/projects`(ローカルJSONから読込)
- Reactフロントエンド: トップ画面(案件一覧・新規案件登録の入口・バックエンド接続状態表示)
- 案件登録(360°動画アップロード)は**未実装**(入口のみ)
- 360°変換処理・3D Gaussian Splatting は未実装(将来: FFmpeg / OpenCV / COLMAP / Nerfstudio / gsplat)

## 前提ソフトウェア

- Python 3.11 以上
- Node.js 20 以上(npm 同梱)
- Git

## セットアップ(Windows)

```powershell
git clone https://github.com/airesearchagl-art/Local-Site-Walk.git
cd Local-Site-Walk
copy .env.example .env   # 必要に応じて編集(任意)
```

### バックエンド起動

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

確認: http://127.0.0.1:8000/api/health

### フロントエンド起動(別ターミナル)

```powershell
cd frontend
npm install
npm run dev
```

確認: http://localhost:5173 (`/api` は自動的にポート8000へプロキシされます)

## test / lint / build

| 対象 | コマンド(各ディレクトリ内で実行) |
| --- | --- |
| backend lint | `ruff check .` |
| backend test | `pytest` |
| frontend lint | `npm run lint` |
| frontend 型チェック | `npm run typecheck` |
| frontend build | `npm run build` |

## データの取り扱い方針

- 360°動画・現場データを外部クラウドへ送信しません(バックエンドに外部送信処理はありません)
- 原動画・抽出フレーム・Gaussian Splat・PLY・生成物はGit管理しません(`.gitignore`で除外)
- 実データはリポジトリ外のデータディレクトリに保存します
  - 既定: `<ホームディレクトリ>/LocalSiteWalkData`(例: `C:\Users\<username>\LocalSiteWalkData`)
  - 環境変数 `LSW_DATA_DIR` で変更できます(`.env.example`参照)
- 案件メタデータはデータディレクトリ内の `projects.json` から読み込みます
  (書式は `sample-data/projects.sample.json` を参照)

## ライセンス

未定(社内利用前提。公開ライセンスの選定はリポジトリオーナーが決定してください)

## 今後の予定

1. 案件登録API・動画ファイルのローカル保存
2. FFmpegによる動画メタデータ取得
3. 閲覧用フレーム・サムネイル生成
4. 撮影順に移動できる360°ツアービューア
5. 条件のよい素材への3D Gaussian Splatting生成
6. 社内ファイルサーバー・NAS共有対応
