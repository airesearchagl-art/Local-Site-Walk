import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import DB_FILE_NAME, get_connection
from app.main import app

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


def _touch(path: Path, *, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


# --- migration ------------------------------------------------------------------


def test_existing_videos_table_gets_file_mtime_column_via_migration(data_dir) -> None:
    """file_mtime追加前の(is_missing等は既にある)videosテーブルへ接続すると、
    ALTER TABLEでfile_mtimeが追加される。"""
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
                is_missing INTEGER NOT NULL DEFAULT 0,
                missing_since TEXT,
                last_seen_at TEXT,
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
        assert "file_mtime" in columns
        row = conn.execute(
            "SELECT file_mtime FROM videos WHERE file_name = 'old.mp4'"
        ).fetchone()
    finally:
        conn.close()

    assert row["file_mtime"] is None


def test_file_mtime_migration_is_idempotent(data_dir) -> None:
    conn1 = get_connection()
    conn1.close()
    conn2 = get_connection()
    try:
        columns = {row["name"] for row in conn2.execute("PRAGMA table_info(videos)")}
    finally:
        conn2.close()
    assert "file_mtime" in columns


# --- new video --------------------------------------------------------------------


def test_new_video_is_added_and_probed(data_dir, video_folder, monkeypatch) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    calls = {"n": 0}

    def counting_probe(path):
        calls["n"] += 1
        return {}

    monkeypatch.setattr("app.main.media.probe_metadata", counting_probe)

    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["added"] == 1
    assert body["updated"] == 0
    assert calls["n"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["added_count"] == 1
    assert runs[0]["skipped_count"] == 0


# --- unchanged: skip ----------------------------------------------------------------


def test_unchanged_file_is_skipped_and_metadata_not_probed(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)
    res1 = client.post(f"/api/projects/{project['id']}/scan")
    assert res1.json()["added"] == 1

    calls = {"n": 0}

    def counting_probe(path):
        calls["n"] += 1
        return {}

    monkeypatch.setattr("app.main.media.probe_metadata", counting_probe)

    res2 = client.post(f"/api/projects/{project['id']}/scan")
    body = res2.json()
    assert body["added"] == 0
    assert body["updated"] == 0
    assert body["removed"] == 0
    # 変更なしのためmetadata取得(probe_metadata)は一切呼ばれない。
    assert calls["n"] == 0

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    latest = runs[0]
    assert latest["skipped_count"] == 1
    assert latest["added_count"] == 0
    assert latest["updated_count"] == 0


def test_unchanged_file_with_valid_thumbnail_is_not_regenerated(
    data_dir, video_folder, monkeypatch
) -> None:
    """skip対象で既に有効なthumbnailがある場合は、生成を再試行しない。

    (無効/未生成の場合の再試行はbackend/tests/test_scan_thumbnail_retry.py
    を参照。thumbnail再試行機能の追加により、有効な既存thumbnailがある
    このケースだけがgenerate_thumbnail未呼び出しのまま維持される。)
    """
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    def fake_generate_thumbnail(video_path, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"jpeg-bytes")
        return True

    monkeypatch.setattr(
        "app.main.media.generate_thumbnail", fake_generate_thumbnail
    )
    res1 = client.post(f"/api/projects/{project['id']}/scan")
    assert res1.json()["thumbnails_generated"] == 1

    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return False

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)

    client.post(f"/api/projects/{project['id']}/scan")
    assert calls["n"] == 0


def test_skipped_video_last_seen_at_is_updated(
    data_dir, video_folder, monkeypatch
) -> None:
    """skip対象でもlast_seen_atだけは今回のスキャン時刻へ更新される。"""
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    timestamps = iter(
        ["2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"]
    )
    monkeypatch.setattr("app.main.now_iso", lambda: next(timestamps))

    client.post(f"/api/projects/{project['id']}/scan")
    videos1 = client.get(f"/api/projects/{project['id']}/videos").json()
    video1 = _video_by_name(videos1, "walk1.mp4")
    assert video1["last_seen_at"] == "2026-01-01T00:00:00+00:00"

    res2 = client.post(f"/api/projects/{project['id']}/scan")
    body = res2.json()
    assert body["added"] == 0
    assert body["updated"] == 0

    videos2 = client.get(f"/api/projects/{project['id']}/videos").json()
    video2 = _video_by_name(videos2, "walk1.mp4")
    assert video2["last_seen_at"] == "2026-01-01T00:05:00+00:00"
    # scanned_at(metadata取得時刻)はskipのため更新されず維持される。
    assert video2["scanned_at"] == video1["scanned_at"]
    assert video2["size_bytes"] == video1["size_bytes"]

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["skipped_count"] == 1
    assert runs[0]["updated_count"] == 0


def test_skipped_video_only_last_seen_at_changes_in_db(
    data_dir, video_folder
) -> None:
    """DB行を直接比較し、last_seen_at以外(size_bytes/file_mtime/
    duration_seconds等)がskip時に一切書き換わらないことを確認する。"""
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"hello")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    conn = get_connection()
    try:
        row_before = dict(
            conn.execute(
                "SELECT * FROM videos WHERE project_id = ?", (project["id"],)
            ).fetchone()
        )
    finally:
        conn.close()

    client.post(f"/api/projects/{project['id']}/scan")

    conn = get_connection()
    try:
        row_after = dict(
            conn.execute(
                "SELECT * FROM videos WHERE project_id = ?", (project["id"],)
            ).fetchone()
        )
    finally:
        conn.close()

    for key in row_before:
        if key == "last_seen_at":
            continue
        assert row_after[key] == row_before[key], key


def test_failed_scan_rolls_back_last_seen_at_update_for_skipped_video(
    data_dir, video_folder, monkeypatch
) -> None:
    """skip対象のlast_seen_at更新は、同じスキャン内の後続ファイルで
    例外が起きた場合にrollbackされ、部分的な更新が残らない。"""
    walk1 = video_folder / "walk1.mp4"
    walk2 = video_folder / "walk2.mp4"
    walk1.write_bytes(b"x")
    walk2.write_bytes(b"y")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    conn = get_connection()
    try:
        row_before = dict(
            conn.execute(
                "SELECT * FROM videos WHERE file_name = 'walk1.mp4'"
            ).fetchone()
        )
    finally:
        conn.close()

    # walk2だけ内容を変えてmetadata取得(probe_metadata)が呼ばれるように
    # し、そこで例外を発生させる。walk1は変更しないためskip対象のまま。
    walk2.write_bytes(b"yy")

    def boom(path):
        raise FileNotFoundError("gone")

    monkeypatch.setattr("app.main.media.probe_metadata", boom)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    conn = get_connection()
    try:
        row_after = dict(
            conn.execute(
                "SELECT * FROM videos WHERE file_name = 'walk1.mp4'"
            ).fetchone()
        )
    finally:
        conn.close()

    assert row_after == row_before


# --- size / mtime changes: update ----------------------------------------------------


def test_size_change_triggers_update(data_dir, video_folder) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    original_mtime = video_path.stat().st_mtime

    # sizeだけを変え、mtimeは明示的に元の値へ戻して変数を分離する。
    video_path.write_bytes(b"abcdef")
    _touch(video_path, mtime=original_mtime)

    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["updated"] == 1
    assert body["added"] == 0

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["updated_count"] == 1
    assert runs[0]["skipped_count"] == 0


def test_mtime_change_triggers_update(data_dir, video_folder) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    original_mtime = video_path.stat().st_mtime

    # 内容(size)は変えず、mtimeだけを変える。
    _touch(video_path, mtime=original_mtime + 120)

    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["updated"] == 1
    assert body["added"] == 0

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["updated_count"] == 1
    assert runs[0]["skipped_count"] == 0


def test_size_and_mtime_change_triggers_update(data_dir, video_folder) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    original_mtime = video_path.stat().st_mtime

    video_path.write_bytes(b"abcdefgh")
    _touch(video_path, mtime=original_mtime + 120)

    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["updated"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["updated_count"] == 1
    assert runs[0]["skipped_count"] == 0


# --- missing / restore / empty directory (PR #14挙動維持) ----------------------------


def test_missing_detection_still_works_with_differential_scan(
    data_dir, video_folder
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.unlink()
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["removed"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["is_missing"] is True


def test_restore_after_missing_is_always_updated_even_if_unchanged(
    data_dir, video_folder
) -> None:
    """復元は差分判定(size/mtime一致)に関わらず常にupdated扱いになる。"""
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    original_size = video_path.stat().st_size
    original_mtime = video_path.stat().st_mtime

    video_path.unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    # 同じ内容・同じmtimeで復元する(=size/mtimeはmissingになる直前と一致)。
    video_path.write_bytes(b"x")
    _touch(video_path, mtime=original_mtime)
    assert video_path.stat().st_size == original_size

    res = client.post(f"/api/projects/{project['id']}/scan")
    body = res.json()
    assert body["updated"] == 1
    assert body["added"] == 0

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    restored = _video_by_name(videos, "walk1.mp4")
    assert restored["is_missing"] is False
    assert restored["missing_since"] is None


def test_empty_directory_scan_still_marks_missing(data_dir, video_folder) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    (video_folder / "walk1.mp4").unlink()
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["removed"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "finished"


# --- cross project isolation --------------------------------------------------------


def test_skip_decision_is_scoped_to_project(data_dir, video_folder, tmp_path) -> None:
    """同名・同内容のファイルでも、他projectの差分判定には影響しない。"""
    folder_a = video_folder
    folder_b = tmp_path / "videos_b"
    folder_b.mkdir()
    (folder_a / "shared.mp4").write_bytes(b"x")
    (folder_b / "shared.mp4").write_bytes(b"x")

    project_a = _create_project(folder_a, name="現場A")
    project_b = _create_project(folder_b, name="現場B")
    client.post(f"/api/projects/{project_a['id']}/scan")
    client.post(f"/api/projects/{project_b['id']}/scan")

    # project_aのファイルだけ内容を変える。
    (folder_a / "shared.mp4").write_bytes(b"changed")

    res_a = client.post(f"/api/projects/{project_a['id']}/scan")
    res_b = client.post(f"/api/projects/{project_b['id']}/scan")

    assert res_a.json()["updated"] == 1
    assert res_b.json()["updated"] == 0

    runs_b = client.get(f"/api/projects/{project_b['id']}/scan_runs").json()
    assert runs_b[0]["skipped_count"] == 1


# --- error_count / missing_count unaffected -----------------------------------------


def test_error_count_still_recorded_on_failure_with_new_files(
    data_dir, video_folder, monkeypatch
) -> None:
    """新規ファイルでの失敗時挙動(error_count)は差分スキャン追加前と同じ。"""
    (video_folder / "walk1.mp4").write_bytes(b"x")
    (video_folder / "walk2.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    call_count = {"n": 0}

    def flaky_probe(path):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise FileNotFoundError("gone")
        return {}

    monkeypatch.setattr("app.main.media.probe_metadata", flaky_probe)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_count"] == 1


def test_missing_count_definition_unaffected_by_skip(data_dir, video_folder) -> None:
    """skipされた動画はmissing_countの計算対象(foundに含まれる)のままで、
    誤ってmissing扱いされない。"""
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    # 変更せず2回rescanする(2回ともskip対象)。
    client.post(f"/api/projects/{project['id']}/scan")
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["removed"] == 0

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["missing_count"] == 0
    assert runs[0]["skipped_count"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["is_missing"] is False
