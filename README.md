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

- Git for Windows
- Python 3.11 以上
- Node.js 20 以上(npm 同梱)

BATスクリプトはこれらの存在確認と案内のみを行い、**本体の自動インストールは行いません**。

## 初回導入(Windows)

> **重要**: clone前はリポジトリ内のBATを実行できません。初回導入には
> 「方法A: `bootstrap_local_site_walk.bat` だけをGitHubまたは社内共有から先に取得する」か、
> 「方法B: 最初の `git clone` だけ手動で実行する」のどちらかが必要です。

### 方法A: bootstrap BAT

1. `bootstrap_local_site_walk.bat` をGitHub(リポジトリルート)または社内共有から取得する
2. ダブルクリックまたはコマンドプロンプトから実行する
3. BATが以下を自動で行います
   - Gitの存在確認(ない場合はGit for Windowsのインストールを案内して終了)
   - `%USERPROFILE%\.claude\projects\Local Site Walk` へのclone
     (既存リポジトリがある場合は上書き・pullをせず状態確認のみ)
   - `scripts\setup_windows.bat` による自動セットアップと動作確認
   - 確認後、`scripts\start_windows.bat` によるアプリ起動

### 方法B: 最初だけ手動clone

コマンドプロンプトで以下を実行します。

```bat
cd /d "%USERPROFILE%\.claude\projects"
git clone https://github.com/airesearchagl-art/Local-Site-Walk.git "Local Site Walk"
cd /d "%USERPROFILE%\.claude\projects\Local Site Walk"
scripts\setup_windows.bat
scripts\start_windows.bat
```

## 2回目以降(Windows)

エクスプローラーから以下をダブルクリックで実行できます。

| 操作 | 実行するファイル |
| --- | --- |
| 起動 | `scripts\start_windows.bat`(backend/frontendを別ウィンドウで起動しブラウザを開く) |
| 更新 | `scripts\update_windows.bat`(未commit変更があれば中止。fast-forward可能な場合のみ更新) |
| 問題調査 | `scripts\diagnose_windows.bat`(Git/Python/Node/ポート/データフォルダ等の状態表示) |

## 手動セットアップ(開発者向け)

```powershell
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

## BAT運用の注意事項(Windows)

- clone前はリポジトリ内のBATを実行できません。初回は bootstrap BAT の別途取得か手動cloneが必要です
- BATは利便性向上用であり、Git・Python・Node.js本体を自動インストールしません
- 未commit変更がある場合、`update_windows.bat` と bootstrap は自動更新・上書きを行わず中止します
- 原動画や生成物(フレーム・PLY・Splat等)をGitへ追加しないでください
- データは既定で `%USERPROFILE%\LocalSiteWalkData` に保存されます(`LSW_DATA_DIR` で変更可)
- 外部クラウドへの自動送信は行いません(BATにも外部ダウンロード・アップロード処理はありません)

## ライセンス

未定(社内利用前提。公開ライセンスの選定はリポジトリオーナーが決定してください)

## 今後の予定

1. 案件登録API・動画ファイルのローカル保存
2. FFmpegによる動画メタデータ取得
3. 閲覧用フレーム・サムネイル生成
4. 撮影順に移動できる360°ツアービューア
5. 条件のよい素材への3D Gaussian Splatting生成
6. 社内ファイルサーバー・NAS共有対応
