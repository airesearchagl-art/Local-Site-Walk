from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db import get_connection, now_iso


@pytest.fixture()
def data_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("LSW_DATA_DIR", str(d))
    return d


def test_now_iso_is_utc_offset_seconds_precision() -> None:
    value = now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0)
    assert value.endswith("+00:00")


def test_new_project_created_at_matches_now_iso_format(data_dir) -> None:
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO projects (name) VALUES ('a')")
        row = conn.execute(
            "SELECT created_at FROM projects WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    parsed = datetime.fromisoformat(row["created_at"])
    assert parsed.utcoffset() == timedelta(0)
    assert row["created_at"].endswith("+00:00")
    assert "T" in row["created_at"]


def test_legacy_created_at_is_normalized_on_next_connection(data_dir) -> None:
    conn = get_connection()
    try:
        # PR #2〜#8時点のSQLite datetime('now')が生成していた旧形式
        # ("YYYY-MM-DD HH:MM:SS"、'T'区切りもUTCオフセットもない)を
        # 直接書き込み、既存DBのシミュレーションとする。
        conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)",
            ("legacy", "2026-07-20 10:11:12"),
        )
        conn.commit()
    finally:
        conn.close()

    # 新しい接続を開くたびに正規化処理が走る想定。
    conn2 = get_connection()
    try:
        row = conn2.execute(
            "SELECT created_at FROM projects WHERE name = 'legacy'"
        ).fetchone()
    finally:
        conn2.close()

    assert row["created_at"] == "2026-07-20T10:11:12+00:00"
    # 同じUTC時刻を表すことを確認(単なる文字列置換ではなく意味も保持)。
    assert datetime.fromisoformat(row["created_at"]) == datetime(
        2026, 7, 20, 10, 11, 12, tzinfo=timezone.utc
    )


def test_normalization_is_idempotent(data_dir) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)",
            ("legacy", "2026-07-20 10:11:12"),
        )
        conn.commit()
    finally:
        conn.close()

    for _ in range(3):
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT created_at FROM projects WHERE name = 'legacy'"
            ).fetchone()
        finally:
            conn.close()
        assert row["created_at"] == "2026-07-20T10:11:12+00:00"
