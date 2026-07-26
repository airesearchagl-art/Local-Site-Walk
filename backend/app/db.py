"""SQLiteアクセス層。

DBファイルはデータディレクトリ(LSW_DATA_DIR)内に置き、Git管理しない。
接続はリクエストごとに開閉する(テストで環境変数を切り替えられるようにするため)。

タイムスタンプ(TEXT列)はすべてISO8601・UTC・秒精度・タイムゾーンオフセット付き
(例: "2026-07-24T12:34:56+00:00")で統一する。Python側は datetime.now(timezone.utc)
.isoformat(timespec="seconds") と同じ形式になるため、そのまま datetime.fromisoformat()
で読み戻せる。SQL側のDEFAULTもこの形式に合わせて strftime で生成する。
"""

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone

from .config import get_data_dir

DB_FILE_NAME = "local_site_walk.db"

# strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') は now_iso() と同じ書式
# (ISO8601, UTC, 秒精度, +00:00オフセット)を返す。'now' は常にUTC。
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    folder_path TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    size_bytes INTEGER,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    codec TEXT,
    thumbnail_path TEXT,
    scanned_at TEXT,
    is_missing INTEGER NOT NULL DEFAULT 0,
    missing_since TEXT,
    last_seen_at TEXT,
    file_mtime REAL,
    UNIQUE (project_id, file_path)
);

-- 差分スキャン・削除検知・Diagnostics・Dashboard(Roadmap Phase 2以降)の基盤。
-- 今回のPRはこのログ機構のみを追加し、スキャン処理自体(全件スキャン)は変更しない。
-- statusは 'running' -> 'finished' または 'failed' のいずれかで終了する。
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    scanned_count INTEGER,
    added_count INTEGER,
    updated_count INTEGER,
    missing_count INTEGER,
    skipped_count INTEGER,
    error_count INTEGER,
    duration_ms INTEGER
);

-- scan_runごとの構造化エラーログ。1 scan_runに複数件紐付く。
-- relative_path/messageは絶対パス・機密情報・生のexception表現を含まない
-- (app/scan_errors.pyのsafe_relative_path()/classify_scan_exception()
-- 経由でのみ書き込む)。
CREATE TABLE IF NOT EXISTS scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    error_code TEXT NOT NULL CHECK (error_code <> ''),
    severity TEXT NOT NULL DEFAULT 'error' CHECK (severity IN ('error', 'warning')),
    relative_path TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_scan_errors_scan_run_id ON scan_errors(scan_run_id);
"""

# 旧形式(SQLiteのdatetime('now')が生成した "YYYY-MM-DD HH:MM:SS"、19文字・
# UTCだが'T'区切りもオフセットもない)で保存された既存行だけを新形式へ
# 正規化する。対象はUTC値そのままなので情報欠落はなく、文字数と桁位置を
# GLOBで厳密に絞ることで、想定外の文字列(空文字・既にISO8601・任意の
# 文字列)は一切変更しない。起動のたびに実行しても、変換後の行は19文字の
# 数字シェイプに一致しなくなるため副作用がない(冪等)。
_NORMALIZE_LEGACY_CREATED_AT = """
UPDATE projects
SET created_at = REPLACE(created_at, ' ', 'T') || '+00:00'
WHERE length(created_at) = 19
  AND created_at GLOB
    '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    || ' [0-9][0-9]:[0-9][0-9]:[0-9][0-9]';
"""


def now_iso() -> str:
    """現在時刻をISO8601・UTC・秒精度の文字列で返す(scanned_at等で使用)。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# videosは既存テーブルのため、CREATE TABLE IF NOT EXISTSだけでは
# 既にDBファイルを持つ環境へ新カラムが追加されない(projects.created_atの
# DEFAULT追加時と同じ落とし穴)。PRAGMA table_infoで実際のカラムを確認し、
# 不足分だけALTER TABLE ADD COLUMNする。既存行はis_missingがNOT NULL
# DEFAULT 0のため0で埋まり、missing_since/last_seen_atはNULLのままになる。
_VIDEOS_MISSING_COLUMNS: dict[str, str] = {
    "is_missing": "INTEGER NOT NULL DEFAULT 0",
    "missing_since": "TEXT",
    "last_seen_at": "TEXT",
}


def _ensure_videos_missing_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(videos)")
    }
    for column, ddl in _VIDEOS_MISSING_COLUMNS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE videos ADD COLUMN {column} {ddl}")


# 差分スキャン(Phase 2)用。file_mtimeも同じ理由でALTER TABLEが必要。
# サイズ比較は既存のsize_bytes列を再利用するため、新規カラムはfile_mtimeのみ。
_VIDEOS_DIFF_COLUMNS: dict[str, str] = {
    "file_mtime": "REAL",
}


def _ensure_videos_diff_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(videos)")
    }
    for column, ddl in _VIDEOS_DIFF_COLUMNS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE videos ADD COLUMN {column} {ddl}")


def get_connection() -> sqlite3.Connection:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    # FastAPIは依存関係のセットアップとエンドポイント本体を別スレッドで
    # 実行することがある。接続は1リクエスト内で逐次利用しかしないため、
    # スレッド間の持ち回りを許可する。
    conn = sqlite3.connect(data_dir / DB_FILE_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _ensure_videos_missing_columns(conn)
    _ensure_videos_diff_columns(conn)
    conn.execute(_NORMALIZE_LEGACY_CREATED_AT)
    conn.commit()
    return conn


def db_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency。リクエスト単位で接続を開き、正常時はcommitする。"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
