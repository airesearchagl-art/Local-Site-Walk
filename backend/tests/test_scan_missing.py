import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import DB_FILE_NAME, get_connection
from app.main import app
from app.scan_missing import mark_newly_missing

client = TestClient(app)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("LSW_DATA_DIR", str(d))
    return d


@pytest.fixture()
def video_folder(tmp_path) -> Path:
    folder = tmp_path / "videos"
    folder.mkdir()
    return folder


def _create_project(folder: Path | None = None, name: str = "テスト現場") -> dict:
    payload: dict = {"name": name}
    if folder is not None:
        payload["folder_path"] = str(folder)
    res = client.post("/api/projects", json=payload)
    assert res.status_code == 201
    return res.json()


def _video_by_name(videos: list[dict], file_name: str) -> dict:
    return next(v for v in videos if v["file_name"] == file_name)


# --- migration ----------------------------------------------------------------


def test_existing_videos_table_gets_missing_columns_via_migration(data_dir) -> None:
    """新カラム追加前に作られたvideosテーブル(旧スキーマ)を持つDBへ接続すると、
    ALTER TABLEでis_missing/missing_since/last_seen_atが追加される。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / DB_FILE_NAME
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            """
            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
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
            )
            """
        )
        raw.execute(
            "INSERT INTO videos (project_id, file_name, file_path)"
            " VALUES (1, 'old.mp4', '/tmp/old.mp4')"
        )
        raw.commit()
    finally:
        raw.close()

    conn = get_connection()
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
        assert {"is_missing", "missing_since", "last_seen_at"} <= columns
        row = conn.execute(
            "SELECT is_missing, missing_since, last_seen_at FROM videos"
            " WHERE file_name = 'old.mp4'"
        ).fetchone()
    finally:
        conn.close()

    # 既存行はNOT NULL DEFAULT 0によりis_missing=0で埋まり、
    # missing_since/last_seen_atはNULLのまま。
    assert row["is_missing"] == 0
    assert row["missing_since"] is None
    assert row["last_seen_at"] is None


def test_migration_is_idempotent(data_dir) -> None:
    """複数回接続してもALTER TABLEが重複実行されずエラーにならない。"""
    conn1 = get_connection()
    conn1.close()
    conn2 = get_connection()
    try:
        columns = {row["name"] for row in conn2.execute("PRAGMA table_info(videos)")}
    finally:
        conn2.close()
    assert {"is_missing", "missing_since", "last_seen_at"} <= columns


# --- state transitions via scan API -------------------------------------------


def test_new_video_is_not_missing_and_has_last_seen_at(data_dir, video_folder) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["is_missing"] is False
    assert video["missing_since"] is None
    assert video["last_seen_at"] is not None


def test_rescan_unchanged_file_stays_not_missing(data_dir, video_folder) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    res = client.post(f"/api/projects/{project['id']}/scan")
    # size/mtimeが不変のため差分スキャンによりskipされ、updatedは0。
    assert res.json()["updated"] == 0
    assert res.json()["removed"] == 0

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["skipped_count"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["is_missing"] is False
    assert video["missing_since"] is None


def test_first_time_undetected_becomes_missing(data_dir, video_folder) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    (video_folder / "walk1.mp4").unlink()
    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["removed"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    latest = runs[0]
    assert latest["missing_count"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["is_missing"] is True
    assert video["missing_since"] is not None


def test_already_missing_video_is_not_recounted_on_next_scan(
    data_dir, video_folder
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    (video_folder / "walk1.mp4").unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    videos_before = client.get(f"/api/projects/{project['id']}/videos").json()
    missing_since_before = _video_by_name(videos_before, "walk1.mp4")["missing_since"]

    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    # 既にis_missing=1の行はmark_newly_missingの対象外なので、
    # このスキャンでのmissing_count(=removed)は0。
    assert body["removed"] == 0

    videos_after = client.get(f"/api/projects/{project['id']}/videos").json()
    video_after = _video_by_name(videos_after, "walk1.mp4")
    assert video_after["is_missing"] is True
    assert video_after["missing_since"] == missing_since_before


def test_redetected_missing_video_is_restored_via_updated_count(
    data_dir, video_folder
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    video_path.unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["is_missing"] is True

    # 同じパスへ復元する。
    video_path.write_bytes(b"x")
    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["updated"] == 1
    assert body["added"] == 0
    assert body["removed"] == 0

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    restored = _video_by_name(videos, "walk1.mp4")
    assert restored["is_missing"] is False
    assert restored["missing_since"] is None
    assert restored["last_seen_at"] is not None


def test_moved_file_marks_old_path_missing_and_adds_new_path(
    data_dir, video_folder
) -> None:
    old_path = video_folder / "walk1.mp4"
    old_path.write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    old_path.unlink()
    (video_folder / "walk1_renamed.mp4").write_bytes(b"x")
    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["added"] == 1
    assert body["removed"] == 1
    assert body["updated"] == 0

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert len(videos) == 2
    old_video = _video_by_name(videos, "walk1.mp4")
    new_video = _video_by_name(videos, "walk1_renamed.mp4")
    assert old_video["is_missing"] is True
    assert new_video["is_missing"] is False
    assert old_video["id"] != new_video["id"]


def test_scan_of_now_empty_directory_marks_existing_videos_missing(
    data_dir, video_folder
) -> None:
    """空フォルダのスキャンはエラーではなく、既存動画をmissingにする正常系。"""
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    (video_folder / "walk1.mp4").unlink()
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    body = res.json()
    assert body["added"] == 0
    assert body["removed"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "finished"

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["is_missing"] is True


# --- failure safety -------------------------------------------------------------


def test_failed_scan_does_not_alter_missing_state(
    data_dir, video_folder, monkeypatch
) -> None:
    """スキャン途中で例外が起きた場合、missing判定フェーズには到達せず、
    既存動画のis_missing/missing_sinceは変化しない(rollbackにより担保)。"""
    (video_folder / "walkA.mp4").write_bytes(b"x")
    (video_folder / "walkB.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200

    videos_before = client.get(f"/api/projects/{project['id']}/videos").json()
    assert all(v["is_missing"] is False for v in videos_before)

    # walkBだけを残し、walkAは(取得順で先に処理される想定で)probe失敗させる。
    # walkBはsizeを変えて差分ありにしておかないと、差分スキャンにより
    # metadata取得(probe_metadata呼び出し)自体がskipされてしまう。
    (video_folder / "walkA.mp4").unlink()
    (video_folder / "walkB.mp4").write_bytes(b"xx")

    def boom(path):
        raise FileNotFoundError("gone")

    monkeypatch.setattr("app.main.media.probe_metadata", boom)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    videos_after = client.get(f"/api/projects/{project['id']}/videos").json()
    walk_a_after = _video_by_name(videos_after, "walkA.mp4")
    walk_b_after = _video_by_name(videos_after, "walkB.mp4")
    # walkAがフォルダから消えていても、スキャン失敗によりmissing判定
    # フェーズ自体が実行されない(rollback済み)ため、is_missingは
    # どちらもFalseのまま変化しない。
    assert walk_a_after["is_missing"] is False
    assert walk_a_after["missing_since"] is None
    assert walk_b_after["is_missing"] is False
    assert walk_b_after["missing_since"] is None

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "failed"


# --- cross-project isolation -----------------------------------------------------


def test_missing_detection_is_scoped_to_project(
    data_dir, video_folder, tmp_path
) -> None:
    folder_a = video_folder
    folder_b = tmp_path / "videos_b"
    folder_b.mkdir()
    (folder_a / "shared.mp4").write_bytes(b"x")
    (folder_b / "shared.mp4").write_bytes(b"x")

    project_a = _create_project(folder_a, name="現場A")
    project_b = _create_project(folder_b, name="現場B")
    client.post(f"/api/projects/{project_a['id']}/scan")
    client.post(f"/api/projects/{project_b['id']}/scan")

    (folder_a / "shared.mp4").unlink()
    client.post(f"/api/projects/{project_a['id']}/scan")

    videos_a = client.get(f"/api/projects/{project_a['id']}/videos").json()
    videos_b = client.get(f"/api/projects/{project_b['id']}/videos").json()
    assert _video_by_name(videos_a, "shared.mp4")["is_missing"] is True
    assert _video_by_name(videos_b, "shared.mp4")["is_missing"] is False


# --- API response does not leak absolute paths -----------------------------------


def test_video_out_missing_fields_do_not_leak_absolute_path(
    data_dir, video_folder
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    (video_folder / "walk1.mp4").unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    # missing_since/last_seen_atはタイムスタンプのみで絶対パスを含まない。
    assert video["missing_since"] is not None
    assert str(video_folder) not in video["missing_since"]
    assert video["last_seen_at"] is not None
    assert str(video_folder) not in video["last_seen_at"]


# --- mark_newly_missing unit tests -----------------------------------------------


def test_mark_newly_missing_returns_count_and_updates_rows(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO videos (project_id, file_name, file_path, is_missing)"
            " VALUES (?, 'a.mp4', '/tmp/a.mp4', 0)",
            (project["id"],),
        )
        conn.execute(
            "INSERT INTO videos (project_id, file_name, file_path, is_missing)"
            " VALUES (?, 'b.mp4', '/tmp/b.mp4', 0)",
            (project["id"],),
        )
        conn.commit()

        count = mark_newly_missing(
            conn, project["id"], {"/tmp/a.mp4"}, "2026-01-01T00:00:00+00:00"
        )
        conn.commit()

        rows = {
            row["file_path"]: (row["is_missing"], row["missing_since"])
            for row in conn.execute(
                "SELECT file_path, is_missing, missing_since FROM videos"
                " WHERE project_id = ?",
                (project["id"],),
            )
        }
    finally:
        conn.close()

    assert count == 1
    assert rows["/tmp/a.mp4"] == (0, None)
    assert rows["/tmp/b.mp4"] == (1, "2026-01-01T00:00:00+00:00")


def test_mark_newly_missing_does_not_touch_already_missing_rows(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO videos (project_id, file_name, file_path, is_missing,"
            " missing_since) VALUES (?, 'b.mp4', '/tmp/b.mp4', 1, 'original')",
            (project["id"],),
        )
        conn.commit()

        count = mark_newly_missing(conn, project["id"], set(), "later")
        conn.commit()

        row = conn.execute(
            "SELECT is_missing, missing_since FROM videos WHERE project_id = ?",
            (project["id"],),
        ).fetchone()
    finally:
        conn.close()

    assert count == 0
    assert row["is_missing"] == 1
    assert row["missing_since"] == "original"
