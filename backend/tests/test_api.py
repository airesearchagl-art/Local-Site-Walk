import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


def test_projects_empty_when_no_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LSW_DATA_DIR", str(tmp_path))
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.json() == []


def test_projects_reads_local_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LSW_DATA_DIR", str(tmp_path))
    projects = [
        {"id": "p-001", "name": "テスト現場A", "status": "registered"},
    ]
    (tmp_path / "projects.json").write_text(
        json.dumps(projects, ensure_ascii=False), encoding="utf-8"
    )
    res = client.get("/api/projects")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == "p-001"
    assert body[0]["name"] == "テスト現場A"


def test_projects_invalid_json_returns_500(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LSW_DATA_DIR", str(tmp_path))
    (tmp_path / "projects.json").write_text("{ broken", encoding="utf-8")
    res = client.get("/api/projects")
    assert res.status_code == 500
