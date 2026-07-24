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
    UNIQUE (project_id, file_path)
);
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
