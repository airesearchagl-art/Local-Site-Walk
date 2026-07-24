"""Local Site Walk ローカルバックエンド。

- 外部クラウド・外部APIへの送信処理は持たない
- 案件・動画メタデータはローカルのデータディレクトリ内SQLiteに保存する
- 動画・サムネイルはDB登録済みのidでのみ配信する(クライアント指定パスは受けない)
"""

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import media, paths, scan
from .config import ALLOWED_ORIGINS, get_thumbnails_dir
from .db import db_conn, now_iso

APP_VERSION = "0.2.0"

app = FastAPI(title="Local Site Walk API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

DbConn = Annotated[sqlite3.Connection, Depends(db_conn)]

MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime"}


# --- models -----------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    folder_path: str | None = None
    note: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    folder_path: str | None = None
    note: str | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    folder_path: str | None
    note: str | None
    created_at: str
    video_count: int


class VideoOut(BaseModel):
    id: int
    project_id: int
    file_name: str
    file_path: str
    size_bytes: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    codec: str | None
    has_thumbnail: bool
    scanned_at: str | None


class ScanResult(BaseModel):
    added: int
    updated: int
    removed: int
    thumbnails_generated: int
    ffprobe_available: bool
    ffmpeg_available: bool


# --- helpers ----------------------------------------------------------------


def _validate_folder(folder_path: str | None) -> str | None:
    if folder_path is None or folder_path.strip() == "":
        return None
    path = Path(folder_path).expanduser()
    if not path.is_absolute():
        raise HTTPException(
            status_code=400, detail="フォルダは絶対パスで指定してください"
        )
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="フォルダが見つかりません")
    return str(path)


def _project_row(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    return row


def _project_out(conn: sqlite3.Connection, row: sqlite3.Row) -> ProjectOut:
    count = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE project_id = ?", (row["id"],)
    ).fetchone()[0]
    return ProjectOut(
        id=row["id"],
        name=row["name"],
        folder_path=row["folder_path"],
        note=row["note"],
        created_at=row["created_at"],
        video_count=count,
    )


def _video_out(row: sqlite3.Row) -> VideoOut:
    thumb = row["thumbnail_path"]
    return VideoOut(
        id=row["id"],
        project_id=row["project_id"],
        file_name=row["file_name"],
        file_path=row["file_path"],
        size_bytes=row["size_bytes"],
        duration_seconds=row["duration_seconds"],
        width=row["width"],
        height=row["height"],
        codec=row["codec"],
        has_thumbnail=bool(thumb) and Path(thumb).is_file(),
        scanned_at=row["scanned_at"],
    )


def _video_row(conn: sqlite3.Connection, video_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="動画が見つかりません")
    return row


def _delete_thumbnail_files(conn: sqlite3.Connection, project_id: int) -> None:
    rows = conn.execute(
        "SELECT thumbnail_path FROM videos WHERE project_id = ?", (project_id,)
    ).fetchall()
    thumbnails_dir = get_thumbnails_dir()
    for row in rows:
        paths.safe_unlink_within(row["thumbnail_path"], thumbnails_dir)


# --- system -----------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "ffprobe_available": media.ffprobe_available(),
        "ffmpeg_available": media.ffmpeg_available(),
    }


# --- projects ---------------------------------------------------------------


@app.get("/api/projects")
def list_projects(conn: DbConn) -> list[ProjectOut]:
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return [_project_out(conn, row) for row in rows]


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate, conn: DbConn) -> ProjectOut:
    folder = _validate_folder(payload.folder_path)
    # created_atはSQLのDEFAULTに頼らずここで明示的に生成する。DEFAULT式は
    # テーブル作成時にsqlite_masterへ焼き込まれるため、旧DEFAULT
    # (datetime('now'))で作成済みの既存DBではCREATE TABLE IF NOT EXISTSが
    # 新しいDEFAULT式へ更新してくれない。明示的に渡すことで、既存DB上でも
    # 新規行は常にnow_iso()と同じISO8601形式になる。
    cur = conn.execute(
        "INSERT INTO projects (name, folder_path, note, created_at)"
        " VALUES (?, ?, ?, ?)",
        (payload.name.strip(), folder, payload.note, now_iso()),
    )
    return _project_out(conn, _project_row(conn, cur.lastrowid))


@app.get("/api/projects/{project_id}")
def get_project(project_id: int, conn: DbConn) -> ProjectOut:
    return _project_out(conn, _project_row(conn, project_id))


@app.put("/api/projects/{project_id}")
def update_project(
    project_id: int, payload: ProjectUpdate, conn: DbConn
) -> ProjectOut:
    row = _project_row(conn, project_id)
    name = payload.name.strip() if payload.name is not None else row["name"]
    if "folder_path" in payload.model_fields_set:
        folder = _validate_folder(payload.folder_path)
    else:
        folder = row["folder_path"]
    note = payload.note if "note" in payload.model_fields_set else row["note"]
    conn.execute(
        "UPDATE projects SET name = ?, folder_path = ?, note = ? WHERE id = ?",
        (name, folder, note, project_id),
    )
    return _project_out(conn, _project_row(conn, project_id))


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, conn: DbConn) -> None:
    _project_row(conn, project_id)
    _delete_thumbnail_files(conn, project_id)
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# --- videos -----------------------------------------------------------------


@app.post("/api/projects/{project_id}/scan")
def scan_project(project_id: int, conn: DbConn) -> ScanResult:
    row = _project_row(conn, project_id)
    if not row["folder_path"]:
        raise HTTPException(status_code=400, detail="フォルダが登録されていません")
    folder = Path(row["folder_path"])
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="登録フォルダが見つかりません")

    found = sorted(
        p for p in scan.iter_scan_candidates(folder) if media.is_video_file(p)
    )
    now = now_iso()
    thumbnails_dir = get_thumbnails_dir()

    added = updated = thumbnails_generated = 0
    for path in found:
        file_path = str(path)
        existing = conn.execute(
            "SELECT * FROM videos WHERE project_id = ? AND file_path = ?",
            (project_id, file_path),
        ).fetchone()
        meta = media.probe_metadata(path) or {}
        values = (
            path.stat().st_size,
            meta.get("duration_seconds"),
            meta.get("width"),
            meta.get("height"),
            meta.get("codec"),
            now,
        )
        if existing is None:
            cur = conn.execute(
                "INSERT INTO videos (project_id, file_name, file_path, size_bytes,"
                " duration_seconds, width, height, codec, scanned_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, path.name, file_path, *values),
            )
            video_id = cur.lastrowid
            added += 1
        else:
            video_id = existing["id"]
            conn.execute(
                "UPDATE videos SET size_bytes = ?, duration_seconds = ?, width = ?,"
                " height = ?, codec = ?, scanned_at = ? WHERE id = ?",
                (*values, video_id),
            )
            updated += 1

        thumb_path = thumbnails_dir / f"{video_id}.jpg"
        if not thumb_path.is_file():
            if media.generate_thumbnail(path, thumb_path):
                thumbnails_generated += 1
            else:
                thumb_path = None
        if thumb_path is not None:
            conn.execute(
                "UPDATE videos SET thumbnail_path = ? WHERE id = ?",
                (str(thumb_path), video_id),
            )

    # フォルダから消えたファイルの行とサムネイルを片付ける
    removed = 0
    found_set = {str(p) for p in found}
    for row_v in conn.execute(
        "SELECT id, file_path, thumbnail_path FROM videos WHERE project_id = ?",
        (project_id,),
    ).fetchall():
        if row_v["file_path"] not in found_set:
            paths.safe_unlink_within(row_v["thumbnail_path"], thumbnails_dir)
            conn.execute("DELETE FROM videos WHERE id = ?", (row_v["id"],))
            removed += 1

    return ScanResult(
        added=added,
        updated=updated,
        removed=removed,
        thumbnails_generated=thumbnails_generated,
        ffprobe_available=media.ffprobe_available(),
        ffmpeg_available=media.ffmpeg_available(),
    )


@app.get("/api/projects/{project_id}/videos")
def list_videos(project_id: int, conn: DbConn) -> list[VideoOut]:
    _project_row(conn, project_id)
    rows = conn.execute(
        "SELECT * FROM videos WHERE project_id = ? ORDER BY file_name",
        (project_id,),
    ).fetchall()
    return [_video_out(row) for row in rows]


@app.get("/api/videos/{video_id}")
def get_video(video_id: int, conn: DbConn) -> VideoOut:
    return _video_out(_video_row(conn, video_id))


@app.get("/api/videos/{video_id}/thumbnail")
def get_thumbnail(video_id: int, conn: DbConn) -> FileResponse:
    row = _video_row(conn, video_id)
    thumb = row["thumbnail_path"]
    if not thumb or not Path(thumb).is_file():
        raise HTTPException(status_code=404, detail="サムネイルがありません")
    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/api/videos/{video_id}/stream")
def stream_video(video_id: int, conn: DbConn) -> FileResponse:
    row = _video_row(conn, video_id)
    path = Path(row["file_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="動画ファイルが見つかりません")
    media_type = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)
