import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import app
from app.scan_runs import ScanRunCounts, finish_scan_run, start_scan_run

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


def test_scan_runs_table_is_created(data_dir) -> None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name = 'scan_runs'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_start_scan_run_creates_running_row(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, _ = start_scan_run(conn, project["id"])
        conn.commit()
        row = conn.execute(
            "SELECT * FROM scan_runs WHERE id = ?", (scan_run_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row["project_id"] == project["id"]
    assert row["status"] == "running"
    assert row["started_at"] is not None
    assert row["finished_at"] is None
    assert row["scanned_count"] is None


def test_finish_scan_run_normal(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, started = start_scan_run(conn, project["id"])
        conn.commit()
        finish_scan_run(
            conn,
            scan_run_id,
            status="finished",
            counts=ScanRunCounts(
                scanned_count=3,
                added_count=2,
                updated_count=1,
                missing_count=0,
                skipped_count=0,
                error_count=0,
            ),
            started_monotonic=started,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM scan_runs WHERE id = ?", (scan_run_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row["status"] == "finished"
    assert row["finished_at"] is not None
    assert row["scanned_count"] == 3
    assert row["added_count"] == 2
    assert row["updated_count"] == 1
    assert row["missing_count"] == 0


def test_finish_scan_run_failed(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, started = start_scan_run(conn, project["id"])
        conn.commit()
        finish_scan_run(
            conn,
            scan_run_id,
            status="failed",
            counts=ScanRunCounts(),
            started_monotonic=started,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM scan_runs WHERE id = ?", (scan_run_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row["status"] == "failed"
    assert row["finished_at"] is not None


def test_finish_scan_run_records_duration_ms(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, started = start_scan_run(conn, project["id"])
        conn.commit()
        time.sleep(0.02)
        finish_scan_run(
            conn,
            scan_run_id,
            status="finished",
            counts=ScanRunCounts(),
            started_monotonic=started,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM scan_runs WHERE id = ?", (scan_run_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row["duration_ms"] is not None
    assert row["duration_ms"] >= 15


def test_scan_run_counts_match_via_api(data_dir, video_folder) -> None:
    project = _create_project(video_folder)
    (video_folder / "walk1.mp4").write_bytes(b"x")
    (video_folder / "walk2.mp4").write_bytes(b"x")

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200

    runs_res = client.get(f"/api/projects/{project['id']}/scan_runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) == 1
    run = runs[0]
    assert run["project_id"] == project["id"]
    assert run["status"] == "finished"
    assert run["scanned_count"] == 2
    assert run["added_count"] == 2
    assert run["updated_count"] == 0
    assert run["missing_count"] == 0
    assert run["finished_at"] is not None
    assert run["duration_ms"] is not None and run["duration_ms"] >= 0

    # 2回目のスキャン: 1件削除・既存2件はupdateとして記録され、
    # スキャンログは新しい行として追記される(上書きされない)。
    (video_folder / "walk1.mp4").unlink()
    res2 = client.post(f"/api/projects/{project['id']}/scan")
    assert res2.status_code == 200

    runs2 = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert len(runs2) == 2
    latest = runs2[0]
    assert latest["scanned_count"] == 1
    assert latest["updated_count"] == 1
    assert latest["missing_count"] == 1


def test_scan_run_records_failure_on_exception(
    data_dir, video_folder, monkeypatch
) -> None:
    project = _create_project(video_folder)
    (video_folder / "walk.mp4").write_bytes(b"x")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.media.probe_metadata", boom)

    with pytest.raises(RuntimeError):
        client.post(f"/api/projects/{project['id']}/scan")

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["finished_at"] is not None
    assert runs[0]["duration_ms"] is not None and runs[0]["duration_ms"] >= 0
    # 失敗時は集計値を確定できないため、追加・更新カウントは記録しない。
    assert runs[0]["added_count"] == 0
    assert runs[0]["scanned_count"] == 0
