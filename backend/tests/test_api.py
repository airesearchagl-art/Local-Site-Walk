from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
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


def test_health(data_dir) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "ffprobe_available" in body
    assert "ffmpeg_available" in body


def test_projects_empty(data_dir) -> None:
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.json() == []


def test_project_crud(data_dir, video_folder) -> None:
    created = _create_project(video_folder)
    assert created["name"] == "テスト現場"
    assert created["folder_path"] == str(video_folder)
    assert created["video_count"] == 0

    res = client.get("/api/projects")
    assert [p["id"] for p in res.json()] == [created["id"]]

    res = client.get(f"/api/projects/{created['id']}")
    assert res.status_code == 200

    res = client.put(
        f"/api/projects/{created['id']}", json={"name": "改名後", "note": "メモ"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "改名後"
    assert res.json()["note"] == "メモ"
    assert res.json()["folder_path"] == str(video_folder)

    res = client.delete(f"/api/projects/{created['id']}")
    assert res.status_code == 204
    assert client.get(f"/api/projects/{created['id']}").status_code == 404


def test_create_project_rejects_missing_folder(data_dir, tmp_path) -> None:
    res = client.post(
        "/api/projects",
        json={"name": "x", "folder_path": str(tmp_path / "not-there")},
    )
    assert res.status_code == 400


def test_create_project_rejects_relative_folder(data_dir) -> None:
    res = client.post(
        "/api/projects", json={"name": "x", "folder_path": "relative/path"}
    )
    assert res.status_code == 400


def test_scan_registers_and_removes_videos(data_dir, video_folder) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"not a real video")
    (video_folder / "walk2.MOV").write_bytes(b"not a real video")
    (video_folder / "ignore.txt").write_text("x")
    project = _create_project(video_folder)

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    body = res.json()
    assert body["added"] == 2
    assert body["removed"] == 0

    res = client.get(f"/api/projects/{project['id']}/videos")
    videos = res.json()
    assert [v["file_name"] for v in videos] == ["walk1.mp4", "walk2.MOV"]
    # 壊れたファイルはffprobe/ffmpegが失敗し、メタデータ・サムネイルなしで登録される
    assert videos[0]["duration_seconds"] is None
    assert videos[0]["has_thumbnail"] is False

    (video_folder / "walk2.MOV").unlink()
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.json()["updated"] == 1
    assert res.json()["removed"] == 1
    res = client.get(f"/api/projects/{project['id']}/videos")
    assert [v["file_name"] for v in res.json()] == ["walk1.mp4"]


def test_scan_without_folder_fails(data_dir) -> None:
    project = _create_project(None)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 400


def test_video_detail_thumbnail_and_stream(data_dir, video_folder) -> None:
    (video_folder / "walk.mp4").write_bytes(b"dummy-bytes")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    video = client.get(f"/api/projects/{project['id']}/videos").json()[0]

    res = client.get(f"/api/videos/{video['id']}")
    assert res.status_code == 200
    assert res.json()["file_name"] == "walk.mp4"

    res = client.get(f"/api/videos/{video['id']}/thumbnail")
    assert res.status_code == 404

    res = client.get(f"/api/videos/{video['id']}/stream")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("video/mp4")
    assert res.content == b"dummy-bytes"

    assert client.get("/api/videos/99999").status_code == 404


def test_scan_ignores_video_reachable_only_via_symlinked_directory(
    data_dir, video_folder
) -> None:
    (video_folder / "walk1.mp4").write_bytes(b"x")

    outside = video_folder.parent / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"x")

    link = video_folder / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    project = _create_project(video_folder)
    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200
    assert res.json()["added"] == 1

    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert [v["file_name"] for v in videos] == ["walk1.mp4"]


def test_delete_project_does_not_remove_thumbnail_outside_thumbnails_dir(
    data_dir, video_folder
) -> None:
    (video_folder / "walk.mp4").write_bytes(b"x")
    project = _create_project(video_folder)
    client.post(f"/api/projects/{project['id']}/scan")
    video = client.get(f"/api/projects/{project['id']}/videos").json()[0]

    outside_dir = data_dir.parent / "outside-thumbs"
    outside_dir.mkdir()
    outside_file = outside_dir / "should-survive.jpg"
    outside_file.write_bytes(b"not-a-real-thumbnail")

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE videos SET thumbnail_path = ? WHERE id = ?",
            (str(outside_file), video["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    res = client.delete(f"/api/projects/{project['id']}")
    assert res.status_code == 204
    assert outside_file.exists()
