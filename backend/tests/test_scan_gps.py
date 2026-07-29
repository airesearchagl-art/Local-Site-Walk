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


_GPS_METADATA = {
    "duration_seconds": 1.0,
    "width": 64,
    "height": 64,
    "codec": "h264",
    "gps_latitude": 35.6812,
    "gps_longitude": 139.7671,
    "gps_altitude": 44.0,
}

_NO_GPS_METADATA = {
    "duration_seconds": 1.0,
    "width": 64,
    "height": 64,
    "codec": "h264",
    "gps_latitude": None,
    "gps_longitude": None,
    "gps_altitude": None,
}


# --- migration ------------------------------------------------------------------


def test_existing_videos_table_gets_gps_columns_via_migration(data_dir) -> None:
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
                container_format TEXT,
                audio_codec TEXT,
                frame_rate REAL,
                bit_rate INTEGER,
                rotation INTEGER,
                captured_at TEXT,
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
        expected = {"gps_latitude", "gps_longitude", "gps_altitude"}
        assert expected <= columns
        row = conn.execute(
            "SELECT gps_latitude, gps_longitude, gps_altitude, container_format"
            " FROM videos WHERE file_name = 'old.mp4'"
        ).fetchone()
    finally:
        conn.close()

    assert tuple(row) == (None, None, None, None)


def test_gps_migration_is_idempotent(data_dir) -> None:
    conn1 = get_connection()
    conn1.close()
    conn2 = get_connection()
    try:
        columns = {row["name"] for row in conn2.execute("PRAGMA table_info(videos)")}
    finally:
        conn2.close()
    assert {"gps_latitude", "gps_longitude", "gps_altitude"} <= columns


# --- new scan saves GPS -----------------------------------------------------------


def test_new_scan_saves_gps(data_dir, video_folder, monkeypatch) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] == 35.6812
    assert video["gps_longitude"] == 139.7671
    assert video["gps_altitude"] == 44.0


def test_video_without_gps_has_null_columns(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_NO_GPS_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] is None
    assert video["gps_longitude"] is None
    assert video["gps_altitude"] is None


# --- differential scan connection: update / restore / skip -------------------------


def test_size_change_updates_gps(data_dir, video_folder, monkeypatch) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"abcdef")
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] == 35.6812


def test_mtime_change_updates_gps(data_dir, video_folder, monkeypatch) -> None:
    import os

    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    new_mtime = video_path.stat().st_mtime + 120
    os.utime(video_path, (new_mtime, new_mtime))
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_longitude"] == 139.7671


def test_gps_present_then_removed_becomes_null(
    data_dir, video_folder, monkeypatch
) -> None:
    """GPSがあった動画のファイル内容が変わり、GPSタグが消えた場合、
    3列とも既存値を残さずNULLへ更新される。"""
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["gps_latitude"] == 35.6812

    video_path.write_bytes(b"abcdef")
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_NO_GPS_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] is None
    assert video["gps_longitude"] is None
    assert video["gps_altitude"] is None


def test_missing_restore_updates_gps(data_dir, video_folder, monkeypatch) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"restored")
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["is_missing"] is False
    assert video["gps_latitude"] == 35.6812


def test_unchanged_scan_does_not_probe_and_gps_unchanged(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    calls = {"n": 0}

    def counting_probe(path):
        calls["n"] += 1
        return dict(_GPS_METADATA)

    monkeypatch.setattr("app.main.media.probe_metadata", counting_probe)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 0
    assert calls["n"] == 0

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] == 35.6812
    assert video["gps_longitude"] == 139.7671
    assert video["gps_altitude"] == 44.0


# --- failure safety -----------------------------------------------------------------


def test_failed_scan_rolls_back_gps_update(data_dir, video_folder, monkeypatch) -> None:
    project = _create_project(video_folder)
    (video_folder / "walk1.mp4").write_bytes(b"x")
    (video_folder / "walk2.mp4").write_bytes(b"x")

    call_count = {"n": 0}

    def flaky_probe(path):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise FileNotFoundError("gone")
        return dict(_GPS_METADATA)

    monkeypatch.setattr("app.main.media.probe_metadata", flaky_probe)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert videos == []

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "failed"


def test_malformed_gps_still_registers_video(
    data_dir, video_folder, monkeypatch
) -> None:
    """probe_metadataがGPS抽出処理そのものに委ねられるため、不正GPS文字列は
    media.py内で既にNoneへ正規化済みのはずだが、念のためscan統合でも
    metadata取得失敗だけを理由に動画登録が止まらないことを確認する。"""
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr(
        "app.main.media.probe_metadata",
        lambda path: {
            "duration_seconds": 1.0,
            "codec": "h264",
            "gps_latitude": None,
            "gps_longitude": None,
            "gps_altitude": None,
        },
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] is None


def test_ffprobe_unavailable_gps_is_null(data_dir, video_folder, monkeypatch) -> None:
    """probe_metadataがNone(ffprobe利用不可相当)でも動画登録は継続し、
    GPS3列はNULLになる(既存graceful degradationを維持)。"""
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.probe_metadata", lambda path: None)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] is None
    assert video["gps_longitude"] is None
    assert video["gps_altitude"] is None


# --- cross project isolation --------------------------------------------------------


def test_gps_scoped_to_project(data_dir, video_folder, tmp_path, monkeypatch) -> None:
    folder_b = tmp_path / "videos_b"
    folder_b.mkdir()
    (video_folder / "shared.mp4").write_bytes(b"x")
    (folder_b / "shared.mp4").write_bytes(b"x")

    project_a = _create_project(video_folder, name="現場A")
    project_b = _create_project(folder_b, name="現場B")

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    client.post(f"/api/projects/{project_a['id']}/scan")

    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_NO_GPS_METADATA)
    )
    client.post(f"/api/projects/{project_b['id']}/scan")

    videos_a = client.get(f"/api/projects/{project_a['id']}/videos").json()
    videos_b = client.get(f"/api/projects/{project_b['id']}/videos").json()
    assert _video_by_name(videos_a, "shared.mp4")["gps_latitude"] == 35.6812
    assert _video_by_name(videos_b, "shared.mp4")["gps_latitude"] is None


# --- API ------------------------------------------------------------------------


def test_api_returns_gps_fields_and_no_raw_location_tag(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] == 35.6812
    assert video["gps_longitude"] == 139.7671
    assert video["gps_altitude"] == 44.0

    # 生のGPSタグ文字列・ffprobe生JSON・想定外フィールドが含まれないこと。
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
        "gps_latitude",
        "gps_longitude",
        "gps_altitude",
    }
    assert set(video.keys()) == expected_keys
    for value in video.values():
        if isinstance(value, str):
            assert "location" not in value.lower()


def test_api_returns_null_gps_when_absent(data_dir, video_folder, monkeypatch) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_NO_GPS_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["gps_latitude"] is None
    assert video["gps_longitude"] is None
    assert video["gps_altitude"] is None


def test_api_single_video_endpoint_includes_gps(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    monkeypatch.setattr(
        "app.main.media.probe_metadata", lambda path: dict(_GPS_METADATA)
    )
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video_id = _video_by_name(videos, "walk1.mp4")["id"]

    res = client.get(f"/api/videos/{video_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["gps_latitude"] == 35.6812
    assert body["gps_longitude"] == 139.7671
    assert body["gps_altitude"] == 44.0
