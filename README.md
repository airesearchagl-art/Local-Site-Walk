# Local Site Walk

既存の360°動画を**外部クラウドへ送信せず**、ローカルPCまたは社内ネットワーク内で
処理・保存し、関係者が敷地・現場状況を閲覧できるようにするアプリケーションです。
初期段階では寸法計測の正確さより、見た目と閲覧性を優先します。

## 現在のMVP範囲

- 案件(Project)の作成・一覧・更新・削除(SQLiteに保存)
- 案件へのローカルフォルダ登録と、フォルダ内360°動画(mp4/mov)のスキャン
- FFprobeによるメタデータ取得・FFmpegによるサムネイル生成
  (FFmpeg/FFprobeがない環境でも動画登録自体は動作し、メタデータ・サムネイルのみ欠落)
- サムネイルカード付きの動画一覧
- ブラウザ上の360°(equirectangular)動画プレイヤー(ドラッグで見回し・ホイールでズーム)
- 3D Gaussian Splatting・COLMAP・Nerfstudio・AI解析・クラウド同期は**未実装**

### API一覧

| メソッド | パス | 内容 |
| --- | --- | --- |
| GET | `/api/health` | ヘルスチェック(FFmpeg/FFprobe有無を含む) |
| GET | `/api/projects` | 案件一覧 |
| POST | `/api/projects` | 案件作成(name / folder_path / note) |
| GET | `/api/projects/{id}` | 案件取得 |
| PUT | `/api/projects/{id}` | 案件更新 |
| DELETE | `/api/projects/{id}` | 案件削除(動画レコード・サムネイルも削除) |
| POST | `/api/projects/{id}/scan` | 登録フォルダをスキャンし動画を登録・更新 |
| GET | `/api/projects/{id}/videos` | 案件の動画一覧 |
| GET | `/api/videos/{id}` | 動画詳細 |
| GET | `/api/videos/{id}/thumbnail` | サムネイルJPEG |
| GET | `/api/videos/{id}/stream` | 動画ファイル配信(ローカル再生用) |

## 前提ソフトウェア

- Git for Windows
- Python 3.11 以上
- Node.js 20 以上(npm 同梱)
- FFmpeg(任意・推奨。動画メタデータ取得とサムネイル生成に使用。なくても起動・動画登録は可能)

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

いずれの操作も、まずリポジトリへ移動してから実行してください。

```bat
cd /d "%USERPROFILE%\.claude\projects\Local Site Walk"
```

| 操作 | 実行するファイル |
| --- | --- |
| 起動 | `scripts\start_windows.bat`(backend/frontendを別ウィンドウで起動しブラウザを開く) |
| 更新 | `scripts\update_windows.bat`(下記参照) |
| PR確認 | `scripts\review_pr_windows.bat <PR番号>`(下記参照) |
| 問題調査 | `scripts\diagnose_windows.bat`(Git/Python/Node/ポート/データフォルダ等の状態表示) |

### main更新

```bat
cd /d "%USERPROFILE%\.claude\projects\Local Site Walk"
scripts\update_windows.bat
```

- 更新対象は常に `main` です。現在のブランチが何であっても、ローカルの`main`と
  `origin/main`を比較します(現在のブランチ自身のupstreamは見ません)
- 未commit変更がある場合は中止します
- ローカルの`main`に`origin/main`へ含まれない独自commitがある場合、または履歴が
  divergeしている場合も、上書きを避けるため中止します(reset/rebase/force切替は行いません)
- `main`以外のブランチにいる場合は、現在のcommitと`origin/main`の最新commitを
  表示したうえでY/N確認してから切り替えます
- 更新後、依存関係の再インストールとアプリ起動はそれぞれ個別にY/N確認します
  (自動では実行しません)

### PRをWindows実機で確認する

```bat
cd /d "%USERPROFILE%\.claude\projects\Local Site Walk"
scripts\review_pr_windows.bat 3
```

`3`は例です。確認したいPR番号に置き換えてください。自動で以下を行います。

1. remote・未commit変更の安全確認(変更があれば中止)
2. `refs/pull/<PR番号>/head` の取得(PRのブランチ名を知らなくてもよい)
3. LOCALとPRのcommitを表示
4. 確認専用ブランチ `pr/<PR番号>` へ切替(PR内容と同期。独自commitがあれば中止)
5. 確認プロンプト — **信頼できるPRであることを確認してから**Y/Nを答えてください。
   Yと答えると、取得したPRのコードでセットアップとcheckが実行されます
6. `setup_windows.bat` による依存関係導入とcheck実行
7. `start_windows.bat` による起動

確認を終えたら `git switch main` などで元のブランチへ戻ってください。
`pr/<PR番号>` は確認専用のため、そこへ直接commitしないでください。

`review_pr_windows.bat`はこのリポジトリ内のファイルであるため、`git switch`が
実行中のスクリプト自身をPR側の内容へ書き換えることがあります。そのため
ブランチ切替の直後に新しいcmd.exeプロセスへ自分自身を再実行させ、
書き換え後のファイルを最初から正しく読み直す構造にしています
(`update_windows.bat`の`git switch`/`git merge --ff-only`も同様)。

この再実行(`cmd /c ""%~f0" ..."`)は、パスに空白を含む既定のclone先
(`%USERPROFILE%\.claude\projects\Local Site Walk`)でも正しく動くよう、
外側をもう一段引用符で囲んでいます。cmd.exeの`/C`引数解析は、コマンドライン上の
引用符が**ちょうど2個**のときだけパスの引用符をそのまま保持する仕様のため、
追加の引数を引用符で囲むと引用符が4個になり、先頭と末尾の引用符だけを
機械的に取り除く古い互換動作へフォールバックします。これによりパス途中の
閉じ引用符が取り残され、空白で区切られた"Local"のような断片が
未知のコマンドとして実行されてしまいます。外側をもう一段引用符で囲むことで、
この機械的な取り除き処理が外側のラップだけを剥がすようにしています。

実行後、期待される表示は次のとおりです。

- ブランチ切替(`Reset branch 'pr/<番号>'`等)の直後に、未知のコマンドエラー
  (`'...' is not recognized as an internal or external command`)が出ない
- 現在のcommitが正しく表示される
- 信頼確認メッセージが表示される
- Y/N入力待ちで停止する(`choice`による入力のみを受け付ける)
- Nを選ぶとsetupを実行せず終了する
- Yを選ぶとsetupへ進み、setup失敗時はstartを実行しない

### 診断

```bat
cd /d "%USERPROFILE%\.claude\projects\Local Site Walk"
scripts\diagnose_windows.bat
```

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
| Windows BAT静的検査 | `python scripts/check_windows_scripts.py`(`pytest`実行時にも自動で走ります) |
| Windows実機check(CI) | `.github/workflows/windows-bat-check.yml`(windows-latest上でBATを実際に実行) |

## データの取り扱い方針

- 360°動画・現場データを外部クラウドへ送信しません(バックエンドに外部送信処理はありません)
- 原動画・抽出フレーム・Gaussian Splat・PLY・生成物はGit管理しません(`.gitignore`で除外)
- 実データはリポジトリ外のデータディレクトリに保存します
  - 既定: `<ホームディレクトリ>/LocalSiteWalkData`(例: `C:\Users\<username>\LocalSiteWalkData`)
  - 環境変数 `LSW_DATA_DIR` で変更できます(`.env.example`参照)
- 案件・動画メタデータはデータディレクトリ内のSQLite(`local_site_walk.db`)に保存します
- サムネイルはデータディレクトリ内 `thumbnails/` に生成します(いずれもGit管理外)
- 動画ファイル自体は登録フォルダから移動・コピーせず、その場所のまま参照します

## BAT運用の注意事項(Windows)

- clone前はリポジトリ内のBATを実行できません。初回は bootstrap BAT の別途取得か手動cloneが必要です
- BATは利便性向上用であり、Git・Python・Node.js本体を自動インストールしません
- 全BATファイル本体はASCII-onlyです。ユーザー向けの日本語メッセージは同梱の
  `*_message.txt`(UTF-8・CRLF・BOMなし)を`type`で表示する方式に統一しています
  (`scripts\check_windows_scripts.py` で機械的に検証。`pytest`実行時にも自動で走ります)
- 未commit変更がある場合、`update_windows.bat` と bootstrap は自動更新・上書きを行わず中止します
- ローカルの`main`に`origin/main`へ含まれない独自commitがある場合、および履歴が
  divergeしている場合も、`update_windows.bat`は自動更新を行わず中止します
- 原動画や生成物(フレーム・PLY・Splat等)をGitへ追加しないでください
- データは既定で `%USERPROFILE%\LocalSiteWalkData` に保存されます(`LSW_DATA_DIR` で変更可)
- 外部クラウドへの自動送信は行いません(BATにも外部ダウンロード・アップロード処理はありません)
- `reset --hard` / `git clean` / 自動stash / force切替は使用しません
- `scripts\update_windows.bat`・`scripts\review_pr_windows.bat`・`bootstrap_local_site_walk.bat`は
  remote originを検証してから動作します。HTTPS
  (`https://github.com/owner/repo.git` または末尾`.git`なし)とSSH
  (`git@github.com:owner/repo.git`、`ssh://git@github.com/owner/repo.git`)の
  いずれの形式も owner/repo として正規化し、同一リポジトリとして扱います
- `scripts\setup_windows.bat` の `npm ci`/`npm install` が失敗した場合(例: `EPERM` で
  ファイルをロック解除できない)は、その場で停止しruff/pytest/lint/buildへは進みません。
  「Local Site Walk - Frontend」ウィンドウを閉じ、タスクマネージャーで`node.exe`や
  Viteのプロセスが残っていないか確認してから再実行してください。node_modulesの自動削除や
  プロセスの自動終了は行いません
- Y/N確認は `set /p` ではなく `choice /c YN` を使用します。任意の文字列ではなく
  Y/Nキー入力のみを受け付けるため、想定外の入力による構文破損を避けられます
- `update_windows.bat`・`review_pr_windows.bat`は、リポジトリ内の自分自身のファイルを
  `git switch`/`git merge --ff-only`で書き換える可能性があるため、その直後に新しい
  cmd.exeプロセスへ自分自身を再実行させます(実行中のファイルが書き換わった状態のまま
  読み進めると、cmd.exeが無関係なバイト列を未知のコマンドとして実行することがあるため)
- `scripts\check_windows_scripts.py`はASCII-only・CRLF・BOMなし・危険コマンドに加え、
  行末caret・`call echo`/`call set`等の二重展開・`*_message.txt`の`call`・
  `for /f`ループ変数の直接実行・`set /p`の残存・自己書き換えgitコマンドの
  再実行ガード不在も検出します(`pytest`実行時にも自動で走ります)
- `.github/workflows/windows-bat-check.yml`が、実際のWindowsランナー上で、
  かつ`C:\ci workspace\Local Site Walk`という**空白を含むパス**へ配置した状態で、
  診断・使用方法表示・不正なPR番号・dirty tree停止・非main branchの各経路を実行し、
  「未知のコマンドとして認識されない」ことを確認します。さらに`cmd /c ""%~f0" ..."`
  という再実行の仕組み自体を、gitやネットワークに依存しない最小スクリプトで
  直接検証します(実PRのfetchはCIでは行いません。ネットワーク・PR番号依存で
  CIが不安定になるのを避けるためです)

## PR #1 merge前後の実施順序(運用メモ)

> **警告**: PRをmergeする**前に**GitHubのデフォルトブランチを空の`main`へ変更しないでください。
> その時点の`main`は空のベースcommitのみのため、通常の`git clone`でアプリファイルも
> `scripts\setup_windows.bat`も取得できず、bootstrap BATによる導入も失敗します。
> デフォルトブランチの変更は必ずmergeと反映確認の**後**に行ってください。

1. feature branch(`claude/local-site-walk-scaffold-v3ab3x`)でWindows実機確認を行う
2. PR #1 を `main` へmergeする
3. `main` にアプリファイル一式(backend / frontend / scripts / BAT)が反映されたことを確認する
4. GitHubのデフォルトブランチを `main` へ変更する
5. bootstrap BATによる新規clone(初回導入)が問題なく動くことを再確認する
6. 問題なければ `backup/scaffold-2da9522` ブランチを削除する

## ライセンス

未定(社内利用前提。公開ライセンスの選定はリポジトリオーナーが決定してください)

## 今後の予定

1. 案件登録API・動画ファイルのローカル保存
2. FFmpegによる動画メタデータ取得
3. 閲覧用フレーム・サムネイル生成
4. 撮影順に移動できる360°ツアービューア
5. 条件のよい素材への3D Gaussian Splatting生成
6. 社内ファイルサーバー・NAS共有対応
