from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import app
from app.scan_errors import (
    DATABASE_ERROR,
    FILE_NOT_FOUND,
    PERMISSION_DENIED,
    UNEXPECTED_ERROR,
    classify_scan_exception,
    count_scan_errors,
    list_scan_errors,
    record_scan_error,
    safe_relative_path,
)
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


# --- migration / schema ------------------------------------------------------


def test_scan_errors_table_is_created(data_dir) -> None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name = 'scan_errors'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


# --- record_scan_error / list_scan_errors / count_scan_errors ---------------


def test_record_scan_error_saves_one_row(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, _ = start_scan_run(conn, project["id"])
        conn.commit()
        record_scan_error(
            conn,
            scan_run_id,
            error_code=UNEXPECTED_ERROR,
            message="テストエラー",
            relative_path="a.mp4",
        )
        conn.commit()
        rows = list_scan_errors(conn, scan_run_id)
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["error_code"] == UNEXPECTED_ERROR
    assert rows[0]["message"] == "テストエラー"
    assert rows[0]["relative_path"] == "a.mp4"
    assert rows[0]["severity"] == "error"
    assert rows[0]["created_at"] is not None


def test_multiple_scan_errors_can_be_saved_for_one_scan_run(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, _ = start_scan_run(conn, project["id"])
        conn.commit()
        record_scan_error(
            conn, scan_run_id, error_code=FILE_NOT_FOUND, message="1件目"
        )
        record_scan_error(
            conn, scan_run_id, error_code=PERMISSION_DENIED, message="2件目"
        )
        conn.commit()
        rows = list_scan_errors(conn, scan_run_id)
        count = count_scan_errors(conn, scan_run_id)
    finally:
        conn.close()

    assert len(rows) == 2
    assert count == 2
    assert [r["message"] for r in rows] == ["1件目", "2件目"]


def test_unknown_error_code_is_normalized_to_unexpected_error(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, _ = start_scan_run(conn, project["id"])
        conn.commit()
        record_scan_error(
            conn, scan_run_id, error_code="not_a_real_code", message="x"
        )
        conn.commit()
        rows = list_scan_errors(conn, scan_run_id)
    finally:
        conn.close()

    assert rows[0]["error_code"] == UNEXPECTED_ERROR


def test_scan_error_cascade_deletes_with_scan_run(data_dir) -> None:
    project = _create_project()
    conn = get_connection()
    try:
        scan_run_id, _ = start_scan_run(conn, project["id"])
        conn.commit()
        record_scan_error(conn, scan_run_id, error_code=UNEXPECTED_ERROR, message="x")
        conn.commit()
        assert len(list_scan_errors(conn, scan_run_id)) == 1

        conn.execute("DELETE FROM scan_runs WHERE id = ?", (scan_run_id,))
        conn.commit()
        remaining = list_scan_errors(conn, scan_run_id)
    finally:
        conn.close()

    assert remaining == []


# --- classify_scan_exception --------------------------------------------------


def test_classify_scan_exception_permission_denied() -> None:
    code, message = classify_scan_exception(PermissionError("denied"))
    assert code == PERMISSION_DENIED
    assert "denied" not in message  # 生の例外文言をそのまま使わない


def test_classify_scan_exception_file_not_found() -> None:
    code, _ = classify_scan_exception(FileNotFoundError("missing"))
    assert code == FILE_NOT_FOUND


def test_classify_scan_exception_database_error() -> None:
    import sqlite3

    code, _ = classify_scan_exception(sqlite3.OperationalError("locked"))
    assert code == DATABASE_ERROR


def test_classify_scan_exception_unknown_falls_back_to_unexpected() -> None:
    code, _ = classify_scan_exception(ValueError("something else"))
    assert code == UNEXPECTED_ERROR


# --- safe_relative_path -------------------------------------------------------


def test_safe_relative_path_returns_relative_posix_path(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "sub" / "video.mp4"
    target.parent.mkdir()
    target.write_bytes(b"x")

    result = safe_relative_path(target, root)

    assert result == "sub/video.mp4"
    assert not result.startswith("/")
    assert str(root) not in result


def test_safe_relative_path_returns_none_outside_root(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "x.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"x")

    assert safe_relative_path(outside, root) is None


def test_safe_relative_path_returns_none_for_none() -> None:
    assert safe_relative_path(None, Path("/tmp")) is None


# --- integration via scan_project API ----------------------------------------


def test_failed_scan_saves_scan_error_and_rolls_back_partial_videos(
    data_dir, video_folder, monkeypatch
) -> None:
    """2件目で例外が起きた場合: 1件目のvideo挿入はrollbackされ、
    scan_errorsに1件保存され、scan_runsはfailed・error_count=1になる。"""
    project = _create_project(video_folder)
    (video_folder / "walk1.mp4").write_bytes(b"x")
    (video_folder / "walk2.mp4").write_bytes(b"x")

    call_count = {"n": 0}

    def flaky_probe(path):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise FileNotFoundError("gone")
        return {}

    monkeypatch.setattr("app.main.media.probe_metadata", flaky_probe)

    with pytest.raises(FileNotFoundError):
        client.post(f"/api/projects/{project['id']}/scan")

    # 動画DB変更はrollbackされている。
    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert videos == []

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "failed"
    assert run["error_count"] == 1

    errors = client.get(
        f"/api/projects/{project['id']}/scan_runs/{run['id']}/errors"
    ).json()
    assert len(errors) == 1
    assert errors[0]["error_code"] == FILE_NOT_FOUND
    assert errors[0]["scan_run_id"] == run["id"]
    # 相対パス(walk2.mp4)のみで、絶対パス(video_folderの実パス)を含まない。
    assert errors[0]["relative_path"] == "walk2.mp4"
    assert str(video_folder) not in errors[0]["relative_path"]
    assert str(video_folder) not in errors[0]["message"]


def test_failed_scan_on_candidate_enumeration_exception_saves_scan_error(
    data_dir, video_folder, monkeypatch
) -> None:
    project = _create_project(video_folder)
    (video_folder / "walk.mp4").write_bytes(b"x")

    def boom(root):
        raise PermissionError("no access")

    monkeypatch.setattr("app.main.scan.iter_scan_candidates", boom)

    with pytest.raises(PermissionError):
        client.post(f"/api/projects/{project['id']}/scan")

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "failed"
    assert run["error_count"] == 1

    errors = client.get(
        f"/api/projects/{project['id']}/scan_runs/{run['id']}/errors"
    ).json()
    assert len(errors) == 1
    assert errors[0]["error_code"] == PERMISSION_DENIED
    # 候補列挙自体の失敗なので、対象ファイルは特定できずrelative_pathはNone。
    assert errors[0]["relative_path"] is None


def test_successful_scan_has_zero_error_count_and_no_scan_errors(
    data_dir, video_folder
) -> None:
    project = _create_project(video_folder)
    (video_folder / "walk.mp4").write_bytes(b"x")

    res = client.post(f"/api/projects/{project['id']}/scan")
    assert res.status_code == 200

    runs = client.get(f"/api/projects/{project['id']}/scan_runs").json()
    assert runs[0]["status"] == "finished"
    assert runs[0]["error_count"] == 0

    errors = client.get(
        f"/api/projects/{project['id']}/scan_runs/{runs[0]['id']}/errors"
    ).json()
    assert errors == []


def test_scan_run_errors_api_scoped_to_owning_project(data_dir, video_folder) -> None:
    """別projectのscan_run idを指定しても取得できない(404)。"""
    project_a = _create_project(video_folder, name="現場A")
    conn = get_connection()
    try:
        scan_run_id, started = start_scan_run(conn, project_a["id"])
        conn.commit()
        finish_scan_run(
            conn,
            scan_run_id,
            status="failed",
            counts=ScanRunCounts(error_count=0),
            started_monotonic=started,
        )
        conn.commit()
    finally:
        conn.close()

    project_b = _create_project(name="現場B")

    res = client.get(
        f"/api/projects/{project_b['id']}/scan_runs/{scan_run_id}/errors"
    )
    assert res.status_code == 404

    # project_a自身からは取得できる(0件でもエラーではない)。
    res_a = client.get(
        f"/api/projects/{project_a['id']}/scan_runs/{scan_run_id}/errors"
    )
    assert res_a.status_code == 200
    assert res_a.json() == []


def test_scan_run_errors_api_missing_scan_run_returns_404(data_dir) -> None:
    project = _create_project()
    res = client.get(f"/api/projects/{project['id']}/scan_runs/999999/errors")
    assert res.status_code == 404


def test_scan_run_errors_api_missing_project_returns_404(data_dir) -> None:
    res = client.get("/api/projects/999999/scan_runs/1/errors")
    assert res.status_code == 404
