import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import media
from app.db import get_connection
from app.main import _is_valid_thumbnail, app

client = TestClient(app)

_HAS_REAL_FFMPEG = media.ffmpeg_available() and media.ffprobe_available()


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


def _valid_thumbnail_stub(video_path, out_path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"jpeg-bytes")
    return True


def _failing_thumbnail_stub(video_path, out_path) -> bool:
    return False


# --- _is_valid_thumbnail --------------------------------------------------------


def test_is_valid_thumbnail_none_is_invalid(tmp_path) -> None:
    assert _is_valid_thumbnail(None, tmp_path) is False


def test_is_valid_thumbnail_empty_string_is_invalid(tmp_path) -> None:
    assert _is_valid_thumbnail("", tmp_path) is False


def test_is_valid_thumbnail_nonexistent_file_is_invalid(tmp_path) -> None:
    assert _is_valid_thumbnail(str(tmp_path / "missing.jpg"), tmp_path) is False


def test_is_valid_thumbnail_directory_is_invalid(tmp_path) -> None:
    sub = tmp_path / "adir"
    sub.mkdir()
    assert _is_valid_thumbnail(str(sub), tmp_path) is False


def test_is_valid_thumbnail_zero_byte_file_is_invalid(tmp_path) -> None:
    thumb = tmp_path / "1.jpg"
    thumb.write_bytes(b"")
    assert _is_valid_thumbnail(str(thumb), tmp_path) is False


def test_is_valid_thumbnail_nonzero_byte_file_is_valid(tmp_path) -> None:
    thumb = tmp_path / "1.jpg"
    thumb.write_bytes(b"jpeg-bytes")
    assert _is_valid_thumbnail(str(thumb), tmp_path) is True


def test_is_valid_thumbnail_rejects_outside_directory(tmp_path) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    thumbnails_dir.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")
    assert _is_valid_thumbnail(str(outside), thumbnails_dir) is False


def test_is_valid_thumbnail_rejects_path_traversal(tmp_path) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    thumbnails_dir.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")
    traversal = str(thumbnails_dir / ".." / "outside.jpg")
    assert _is_valid_thumbnail(traversal, thumbnails_dir) is False


def test_is_valid_thumbnail_rejects_symlink_escaping_directory(tmp_path) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    thumbnails_dir.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")
    link = thumbnails_dir / "escape.jpg"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")
    assert _is_valid_thumbnail(str(link), thumbnails_dir) is False


def test_is_valid_thumbnail_windows_style_path_is_safe(tmp_path) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    thumbnails_dir.mkdir()
    # Windowsスタイルのパス文字列(バックスラッシュ)を渡しても、
    # 存在しないパスとして安全にFalseになる(例外を投げない)。
    assert _is_valid_thumbnail("C:\\nonexistent\\1.jpg", thumbnails_dir) is False


def test_is_valid_thumbnail_does_not_raise_on_unexpected_input(tmp_path) -> None:
    for value in ("\x00bad", "   ", "/" * 500):
        assert _is_valid_thumbnail(value, tmp_path) is False


# --- unchanged scan: retry conditions ---------------------------------------------


def test_unchanged_thumbnail_null_generates_once(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    # 初回scan: ffmpeg利用不可相当にしてthumbnail未生成のままにする。
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["has_thumbnail"] is False

    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert calls["n"] == 1
    assert res.json()["updated"] == 0
    assert res.json()["thumbnails_generated"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["skipped_count"] == 1
    assert runs[0]["updated_count"] == 0

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["has_thumbnail"] is True


def test_unchanged_thumbnail_file_missing_generates_once(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video_id = _video_by_name(videos, "walk1.mp4")["id"]

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        Path(row["thumbnail_path"]).unlink()
    finally:
        conn.close()

    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert calls["n"] == 1
    assert res.json()["updated"] == 0

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["has_thumbnail"] is True


def test_unchanged_thumbnail_zero_byte_generates_once(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video_id = _video_by_name(videos, "walk1.mp4")["id"]

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        Path(row["thumbnail_path"]).write_bytes(b"")
    finally:
        conn.close()

    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)
    client.post(f"/api/projects/{project['id']}/scan")
    assert calls["n"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["has_thumbnail"] is True


def test_retry_success_does_not_touch_metadata_or_gps(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    monkeypatch.setattr(
        "app.main.media.probe_metadata",
        lambda path: {
            "duration_seconds": 9.0,
            "codec": "h264",
            "gps_latitude": 1.0,
            "gps_longitude": 2.0,
            "gps_altitude": None,
        },
    )
    client.post(f"/api/projects/{project['id']}/scan")

    videos_before = client.get(f"/api/projects/{project['id']}/videos").json()
    before = _video_by_name(videos_before, "walk1.mp4")

    probe_calls = {"n": 0}

    def counting_probe(path):
        probe_calls["n"] += 1
        return {}

    monkeypatch.setattr("app.main.media.probe_metadata", counting_probe)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)

    client.post(f"/api/projects/{project['id']}/scan")
    assert probe_calls["n"] == 0

    videos_after = client.get(f"/api/projects/{project['id']}/videos").json()
    after = _video_by_name(videos_after, "walk1.mp4")
    assert after["duration_seconds"] == before["duration_seconds"]
    assert after["codec"] == before["codec"]
    assert after["gps_latitude"] == before["gps_latitude"]
    assert after["gps_longitude"] == before["gps_longitude"]
    assert after["has_thumbnail"] is True


def test_retry_failure_still_skipped_and_scan_continues(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["updated"] == 0

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "finished"
    assert runs[0]["skipped_count"] == 1
    assert runs[0]["error_count"] == 0


def test_retry_failure_does_not_change_thumbnail_path_value(
    data_dir, video_folder, monkeypatch
) -> None:
    """再試行失敗時、既存のthumbnail_path(NULLまたは無効な旧パス)を維持する。"""
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video_id = _video_by_name(videos, "walk1.mp4")["id"]

    conn = get_connection()
    try:
        before = conn.execute(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,)
        ).fetchone()["thumbnail_path"]
    finally:
        conn.close()
    assert before is None

    client.post(f"/api/projects/{project['id']}/scan")

    conn = get_connection()
    try:
        after = conn.execute(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,)
        ).fetchone()["thumbnail_path"]
    finally:
        conn.close()
    assert after is None


def test_retry_does_not_call_probe_metadata(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    calls = {"n": 0}

    def counting_probe(path):
        calls["n"] += 1
        return {}

    monkeypatch.setattr("app.main.media.probe_metadata", counting_probe)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")
    assert calls["n"] == 0


def test_retry_updates_last_seen_at(data_dir, video_folder, monkeypatch) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"x")
    project = _create_project(video_folder)

    timestamps = iter(
        ["2026-02-01T00:00:00+00:00", "2026-02-01T00:10:00+00:00"]
    )
    monkeypatch.setattr("app.main.now_iso", lambda: next(timestamps))
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    before_last_seen = _video_by_name(videos, "walk1.mp4")["last_seen_at"]
    assert before_last_seen == "2026-02-01T00:00:00+00:00"

    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    after_last_seen = _video_by_name(videos, "walk1.mp4")["last_seen_at"]
    assert after_last_seen == "2026-02-01T00:10:00+00:00"


# --- new / update / restore regression --------------------------------------------


def test_new_video_thumbnail_generated_as_before(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["added"] == 1
    assert res.json()["thumbnails_generated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert _video_by_name(videos, "walk1.mp4")["has_thumbnail"] is True


def test_size_change_regenerates_thumbnail(
    data_dir, video_folder, monkeypatch
) -> None:
    """update分岐は従来どおり、有効なthumbnailが無ければ生成を試みる。

    (deterministicなthumbnail_pathに既に有効なファイルがある場合は
    従来から再生成しないため、初回は生成失敗させファイルが無い状態から
    確認する。)
    """
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"abcdef")
    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1
    assert calls["n"] == 1


def test_mtime_change_regenerates_thumbnail(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    new_mtime = video_path.stat().st_mtime + 120
    os.utime(video_path, (new_mtime, new_mtime))
    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1
    assert calls["n"] == 1


def test_missing_restore_regenerates_thumbnail(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.unlink()
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"restored")
    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1
    assert calls["n"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["is_missing"] is False
    assert video["has_thumbnail"] is True


def test_update_thumbnail_generation_failure_does_not_break_update(
    data_dir, video_folder, monkeypatch
) -> None:
    video_path = video_folder / "walk1.mp4"
    video_path.write_bytes(b"abc")
    project = _create_project(video_folder)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    video_path.write_bytes(b"abcdef")
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["updated"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    assert video["has_thumbnail"] is False


# --- transaction / filesystem consistency ------------------------------------------


def test_failed_scan_rolls_back_thumbnail_retry_and_cleans_up_file(
    data_dir, video_folder, monkeypatch
) -> None:
    walk_a = video_folder / "walkA.mp4"
    walk_b = video_folder / "walkB.mp4"
    walk_a.write_bytes(b"x")
    walk_b.write_bytes(b"y")
    project = _create_project(video_folder)

    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project['id']}/scan")

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video_a_id = _video_by_name(videos, "walkA.mp4")["id"]

    generated_paths: list[Path] = []

    def recording_thumb(video_path, out_path):
        ok = _valid_thumbnail_stub(video_path, out_path)
        if ok:
            generated_paths.append(out_path)
        return ok

    def boom(path):
        raise FileNotFoundError("gone")

    # walkA(先に処理される)はunchanged+thumbnail再試行成功、
    # walkBはsize変更によりmetadata取得(probe_metadata)で例外発生。
    walk_b.write_bytes(b"yy")
    monkeypatch.setattr("app.main.media.generate_thumbnail", recording_thumb)
    monkeypatch.setattr("app.main.media.probe_metadata", boom)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    assert len(generated_paths) == 1
    assert not generated_paths[0].exists(), "rollback後は生成済みfileも削除される"

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_a_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row["thumbnail_path"] is None


def test_failed_scan_does_not_leave_extra_thumbnail_files(
    data_dir, video_folder, monkeypatch
) -> None:
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
    monkeypatch.setattr("app.main.media.generate_thumbnail", _valid_thumbnail_stub)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    from app.config import get_thumbnails_dir

    thumbnails_dir = get_thumbnails_dir()
    if thumbnails_dir.exists():
        assert list(thumbnails_dir.iterdir()) == []


def test_thumbnail_retry_scoped_to_project(
    data_dir, video_folder, tmp_path, monkeypatch
) -> None:
    folder_b = tmp_path / "videos_b"
    folder_b.mkdir()
    (video_folder / "shared.mp4").write_bytes(b"x")
    (folder_b / "shared.mp4").write_bytes(b"x")

    project_a = _create_project(video_folder, name="現場A")
    project_b = _create_project(folder_b, name="現場B")

    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)
    client.post(f"/api/projects/{project_a['id']}/scan")
    client.post(f"/api/projects/{project_b['id']}/scan")

    calls = {"n": 0}

    def counting_thumb(video_path, out_path):
        calls["n"] += 1
        return _valid_thumbnail_stub(video_path, out_path)

    monkeypatch.setattr("app.main.media.generate_thumbnail", counting_thumb)
    client.post(f"/api/projects/{project_a['id']}/scan")
    assert calls["n"] == 1

    videos_a = client.get(f"/api/projects/{project_a['id']}/videos").json()
    videos_b = client.get(f"/api/projects/{project_b['id']}/videos").json()
    assert _video_by_name(videos_a, "shared.mp4")["has_thumbnail"] is True
    assert _video_by_name(videos_b, "shared.mp4")["has_thumbnail"] is False


# --- generate_thumbnail: atomic write / ffmpeg failure modes -----------------------


def test_generate_thumbnail_atomic_success_leaves_no_temp_file(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def fake_run(cmd, capture_output, timeout, check):
        out = Path(cmd[-1])
        out.write_bytes(b"jpeg-bytes")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    out_path = tmp_path / "1.jpg"

    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is True
    assert out_path.read_bytes() == b"jpeg-bytes"
    assert list(tmp_path.iterdir()) == [out_path]


def test_generate_thumbnail_failure_leaves_no_temp_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def fake_run(cmd, capture_output, timeout, check):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    out_path = tmp_path / "1.jpg"

    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False
    assert not out_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_generate_thumbnail_does_not_destroy_existing_file_on_failure(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    out_path = tmp_path / "1.jpg"
    out_path.write_bytes(b"original-valid-thumbnail")

    def fake_run(cmd, capture_output, timeout, check):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(media.subprocess, "run", fake_run)

    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False
    assert out_path.read_bytes() == b"original-valid-thumbnail"


def test_generate_thumbnail_command_not_found(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    out_path = tmp_path / "1.jpg"
    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False
    assert not out_path.exists()


def test_generate_thumbnail_subprocess_oserror(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def raise_oserror(cmd, capture_output, timeout, check):
        raise OSError("no such file")

    monkeypatch.setattr(media.subprocess, "run", raise_oserror)
    out_path = tmp_path / "1.jpg"
    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False
    assert list(tmp_path.iterdir()) == []


def test_generate_thumbnail_timeout(monkeypatch, tmp_path) -> None:
    import subprocess as subprocess_module

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def raise_timeout(cmd, capture_output, timeout, check):
        raise subprocess_module.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(media.subprocess, "run", raise_timeout)
    out_path = tmp_path / "1.jpg"
    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False
    assert list(tmp_path.iterdir()) == []


def test_generate_thumbnail_zero_byte_output_is_rejected(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def fake_run(cmd, capture_output, timeout, check):
        out = Path(cmd[-1])
        out.write_bytes(b"")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    out_path = tmp_path / "1.jpg"

    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False
    assert not out_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_generate_thumbnail_missing_output_file_is_rejected(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)

    def fake_run(cmd, capture_output, timeout, check):
        # returncode=0だが出力ファイル自体を書かない異常系。
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    out_path = tmp_path / "1.jpg"

    assert media.generate_thumbnail(Path("dummy.mp4"), out_path) is False


@pytest.mark.skipif(
    not _HAS_REAL_FFMPEG, reason="この環境にはffmpeg/ffprobeがインストールされていない"
)
def test_generate_thumbnail_with_real_ffmpeg_produces_valid_jpeg_and_no_temp(
    tmp_path,
) -> None:
    """実際のffmpegを使った統合確認。

    一時ファイル名の拡張子誤りにより、実際のffmpegがmuxer形式を推測
    できず失敗する不具合が手動確認で見つかったため、mockだけでなく
    実プロセス経由でも検証する回帰テスト。動画はこのテスト内でのみ
    生成し、repositoryへは一切追加しない。
    """
    video_path = tmp_path / "walk.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=25",
            "-c:v", "libx264",
            "-movflags", "+faststart",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    out_path = tmp_path / "thumb.jpg"

    assert media.generate_thumbnail(video_path, out_path) is True
    assert out_path.is_file()
    assert out_path.stat().st_size > 0
    # 一時ファイルが残っていないこと(out_path以外のファイルが無いこと)。
    assert set(tmp_path.iterdir()) == {video_path, out_path}


# --- graceful degradation / scan continues -----------------------------------------


def test_ffmpeg_unavailable_scan_still_succeeds(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    monkeypatch.setattr("app.main.media.generate_thumbnail", _failing_thumbnail_stub)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "finished"
    assert runs[0]["error_count"] == 0


def test_thumbnail_failure_stderr_not_leaked_to_api(
    data_dir, video_folder, monkeypatch
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")
    project = _create_project(video_folder)

    def failing_with_absolute_path_in_log(video_path, out_path):
        # 実際のログには絶対パスが出ることがあるが、API/DBには漏れない
        # ことを確認するためのstub(戻り値は常にFalse)。
        return False

    monkeypatch.setattr(
        "app.main.media.generate_thumbnail", failing_with_absolute_path_in_log
    )
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    video = _video_by_name(videos, "walk1.mp4")
    # file_pathは既存仕様どおり絶対パスを含む(今回のPRで新たに追加した
    # 漏洩ではない)。それ以外のフィールドにthumbnail生成失敗由来の
    # stderr・絶対パスが混入していないことを確認する。
    for key, value in video.items():
        if key == "file_path":
            continue
        if isinstance(value, str):
            assert str(video_folder) not in value

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["error_count"] == 0
    errors = client.get(
        f"/api/projects/{project['id']}/scan_runs/{runs[0]['id']}/errors"
    ).json()
    assert errors == []
