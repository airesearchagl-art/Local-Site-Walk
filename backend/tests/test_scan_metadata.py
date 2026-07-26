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


_FULL_METADATA = {
    "duration_seconds": 12.5,
    "width": 1920,
    "height": 1080,
    "codec": "h264",
    "container_format": "mov,mp4,m4a,3gp,3g2,mj2",
    "audio_codec": "aac",
    "frame_rate": 30000 / 1001,
    "bit_rate": 1234567,
    "rotation": 90,
    "captured_at": "2026-01-02T03:04:05+00:00",
}


# --- migration ------------------------------------------------------------------


def test_existing_videos_table_gets_metadata_columns_via_migration(data_dir) -> None:
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
                file_mtime REAL,
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
        expected = {
            "container_format",
            "audio_codec",
            "frame_rate",
            "bit_rate",
            "rotation",
            "captured_at",
        }
        assert expected <= columns
        row = conn.execute(
            "SELECT container_format, audio_codec, frame_rate, bit_rate,"
            " rotation, captured_at FROM videos WHERE file_name = 'old.mp4'"
        ).fetchone()
    finally:
        conn.close()

    assert tuple(row) == (None, None, None, None, None, None)


def test_metadata_migration_is_idempotent(data_dir) -> None:
    conn1 = get_connection()
    conn1.close()
    conn2 = get_connection()
    try:
        columns = {row["name"] for row in conn2.execute("PRAGMA table_info(videos)")}
    finally:
        conn2.close()
    assert {"container_format", "audio_codec", "frame_rate", "bit_rate"} <= columns


# --- new scan saves extended metadata ---------------------------------------------


def test_new_scan_saves_extended_metadata(data_dir, video_folder, monkeypatch) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["container_format"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert video["audio_codec"] == "aac"
    assert video["frame_rate"] == pytest.approx(30000 / 1001)
    assert video["bit_rate"] == 1234567
    assert video["rotation"] == 90
    assert video["captured_at"] == "2026-01-02T03:04:05+00:00"
    # 既存フィールドも維持される。
    assert video["codec"] == "h264"
    assert video["duration_seconds"] == 12.5


def test_size_change_updates_extended_metadata(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"abcdef")
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["bit_rate"] == 1234567
    assert video["audio_codec"] == "aac"


def test_mtime_change_updates_extended_metadata(
    data_dir, video_folder, monkeypatch
) -> None:
    import os

    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    new_mtime = video_path.stat().st_mtime + 120
    os.utime(video_path, (new_mtime, new_mtime))
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["rotation"] == 90
    assert video["container_format"] == "mov,mp4,m4a,3gp,3g2,mj2"


def test_missing_restore_updates_extended_metadata(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"restored")
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["is_missing"] is False
    assert video["captured_at"] == "2026-01-02T03:04:05+00:00"


# --- unchanged: skip does not touch extended metadata ------------------------------


def test_unchanged_scan_does_not_call_probe_metadata_or_change_metadata(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    calls = {"n": 0}

    def counting_probe(path):
        calls["n"] += 1
        return dict(_FULL_METADATA)

    monkeypatch.setattr("app.main.media.probe_metadata", counting_probe)

    videos_before = client.get(f"/api/projects/{project['id']}/videos").json()
    video_before = _video_by_name(videos_before, "walk1.mp4")

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 0
    assert calls["n"] == 0

    videos_after = client.get(f"/api/projects/{project['id']}/videos").json()
    video_after = _video_by_name(videos_after, "walk1.mp4")
    for key in (
        "container_format",
        "audio_codec",
        "frame_rate",
        "bit_rate",
        "rotation",
        "captured_at",
    ):
        assert video_after[key] == video_before[key]


# --- partial / total metadata failure does not block registration ------------------


def test_partial_metadata_failure_still_registers_video(
    data_dir, video_folder, monkeypatch
) -> None:
    """probe_metadataが一部項目のみ返しても、動画登録は継続し、
    欠落項目はNULLになる。"""
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata",
        lambda path: {"duration_seconds": 5.0, "codec": "h264"},
    )

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["duration_seconds"] == 5.0
    assert video["codec"] == "h264"
    assert video["container_format"] is None
    assert video["audio_codec"] is None
    assert video["frame_rate"] is None
    assert video["bit_rate"] is None
    assert video["rotation"] is None
    assert video["captured_at"] is None


def test_ffprobe_unavailable_still_registers_video(
    data_dir, video_folder, monkeypatch
) -> None:
    """probe_metadataがNoneを返す(ffprobe利用不可・失敗)場合でも、
    既存のgraceful degradationどおり動画登録は継続する。"""
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.probe_metadata", lambda path: None)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["duration_seconds"] is None
    assert video["container_format"] is None
    assert video["audio_codec"] is None


# --- failed scan rollback -----------------------------------------------------------


def test_failed_scan_rolls_back_extended_metadata(
    data_dir, video_folder, monkeypatch
) -> None:
    project = _create_project(video_folder)
    (video_folder / "walk1.mp4").write_bytes(b"x")
    (video_folder / "walk2.mp4").write_bytes(b"x")

    call_count = {"n": 0}

    def flaky_probe(path):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise FileNotFoundError("gone")
        return dict(_FULL_METADATA)

    monkeypatch.setattr("app.main.media.probe_metadata", flaky_probe)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert videos == []

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "failed"


# --- cross project isolation --------------------------------------------------------


def test_extended_metadata_is_scoped_to_project(
    data_dir, video_folder, tmp_path, monkeypatch
) -> None:
    folder_b = tmp_path / "videos_b"
    folder_b.mkdir()
    (video_folder / "shared.mp4").write_bytes(b"x")
    (folder_b / "shared.mp4").write_bytes(b"x")

    project_a = _create_project(video_folder, name="現場A")
    project_b = _create_project(folder_b, name="現場B")

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )
    client.post(f"/api/projects/{project_a['id']}/scan")

    monkeypatch.setattr("app.main.media.probe_metadata", lambda path: None)
    client.post(f"/api/projects/{project_b['id']}/scan")

    videos_a = client.get(f"/api/projects/{project_a['id']}/videos").json()
    videos_b = client.get(f"/api/projects/{project_b['id']}/videos").json()
    assert _video_by_name(videos_a, "shared.mp4")["audio_codec"] == "aac"
    assert _video_by_name(videos_b, "shared.mp4")["audio_codec"] is None


# --- API does not leak raw ffprobe JSON / absolute paths / traceback ---------------


def test_api_response_only_contains_expected_video_fields(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_FULL_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    expected_keys = {
        "id",
        "project_id",
        "file_name",
        "file_path",
        "size_bytes",
        "duration_seconds",
        "width",
        "height",
        "codec",
        "has_thumbnail",
        "scanned_at",
        "is_missing",
        "missing_since",
        "last_seen_at",
        "container_format",
        "audio_codec",
        "frame_rate",
        "bit_rate",
        "rotation",
        "captured_at",
    }
    assert set(video.keys()) == expected_keys
