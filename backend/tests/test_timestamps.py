from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection, now_iso
from app.main import app

client = TestClient(app)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("LSW_DATA_DIR", str(d))
    return d


def _insert_project(created_at: str, name: str = "legacy") -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)",
            (name, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _read_created_at(name: str = "legacy") -> str:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT created_at FROM projects WHERE name = ?", (name,)
        ).fetchone()
    finally:
        conn.close()
    return row["created_at"]


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


def test_create_project_api_returns_iso8601_created_at(data_dir) -> None:
    res = client.post("/api/projects", json={"name": "API経由の案件"})
    assert res.status_code == 201
    created_at = res.json()["created_at"]

    parsed = datetime.fromisoformat(created_at)
    assert parsed.utcoffset() == timedelta(0)
    assert created_at.endswith("+00:00")
    assert "T" in created_at


def test_legacy_sqlite_format_is_normalized_on_next_connection(data_dir) -> None:
    # PR #2〜#8時点のSQLite datetime('now')が生成していた旧形式
    # ("YYYY-MM-DD HH:MM:SS"、19文字、'T'区切りもUTCオフセットもない)を
    # 直接書き込み、既存DBのシミュレーションとする。
    _insert_project("2026-07-20 10:11:12")

    # 新しい接続を開くたびに正規化処理が走る想定。
    assert _read_created_at() == "2026-07-20T10:11:12+00:00"
    # 同じUTC時刻を表すことを確認(単なる文字列置換ではなく意味も保持)。
    assert datetime.fromisoformat(_read_created_at()) == datetime(
        2026, 7, 20, 10, 11, 12, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-20T10:11:12+00:00",  # 既に新形式(ISO8601+オフセット)
        "",  # 空文字
        "not-a-date",  # 任意の文字列
        "2026-07-20 10:11:12 extra",  # 19文字を超える(末尾に余分な文字)
        "2026-07-20 10:11:1",  # 19文字未満(桁欠け)
        "2026/07/20 10:11:12",  # 区切り文字が異なる未知形式
        "2026-07-20",  # 日付のみ(短い)
    ],
)
def test_non_legacy_values_are_left_unmodified(data_dir, value: str) -> None:
    _insert_project(value)
    assert _read_created_at() == value


def test_normalization_is_idempotent(data_dir) -> None:
    _insert_project("2026-07-20 10:11:12")

    for _ in range(3):
        assert _read_created_at() == "2026-07-20T10:11:12+00:00"


def test_normalization_only_touches_legacy_shaped_rows(data_dir) -> None:
    _insert_project("2026-07-20 10:11:12", name="legacy")
    _insert_project("2026-07-21T09:00:00+00:00", name="already-new")
    _insert_project("", name="empty")

    assert _read_created_at("legacy") == "2026-07-20T10:11:12+00:00"
    assert _read_created_at("already-new") == "2026-07-21T09:00:00+00:00"
    assert _read_created_at("empty") == ""
