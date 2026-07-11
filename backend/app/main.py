"""Local Site Walk ローカルバックエンド(MVP)。

- 外部クラウド・外部APIへの送信処理は持たない
- 案件メタデータはローカルのデータディレクトリ内 projects.json から読む
"""

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import ALLOWED_ORIGINS, get_data_dir

logger = logging.getLogger("local_site_walk")

APP_VERSION = "0.1.0"

app = FastAPI(title="Local Site Walk API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


class Project(BaseModel):
    """案件メタデータ(MVP版)。"""

    id: str
    name: str
    recorded_at: str | None = None
    status: str = "registered"
    note: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/projects")
def list_projects() -> list[Project]:
    """データディレクトリの projects.json から案件一覧を返す。

    ファイルが無い場合は空リスト(初期状態)。
    """
    projects_file = get_data_dir() / "projects.json"
    if not projects_file.exists():
        return []
    try:
        raw = json.loads(projects_file.read_text(encoding="utf-8"))
        return [Project.model_validate(item) for item in raw]
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("projects.json の読み込みに失敗: %s", exc)
        raise HTTPException(
            status_code=500, detail="projects.json が不正な形式です"
        ) from exc
