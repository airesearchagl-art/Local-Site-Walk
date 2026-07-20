"""SQLiteアクセス層。

DBファイルはデータディレクトリ(LSW_DATA_DIR)内に置き、Git管理しない。
接続はリクエストごとに開閉する(テストで環境変数を切り替えられるようにするため)。
"""

import sqlite3
from collections.abc import Iterator

from .config import get_data_dir

DB_FILE_NAME = "local_site_walk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    folder_path TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    return conn


def db_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency。リクエスト単位で接続を開き、正常時はcommitする。"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
