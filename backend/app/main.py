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

from . import media, paths, scan, scan_errors, scan_missing, scan_runs
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
    codec: str | None  # video codec(既存列。video_codecへのrenameはしない)
    has_thumbnail: bool
    scanned_at: str | None
    is_missing: bool
    missing_since: str | None
    last_seen_at: str | None
    container_format: str | None
    audio_codec: str | None
    frame_rate: float | None
    bit_rate: int | None  # bit/s
    rotation: int | None  # degree(0〜360未満)
    captured_at: str | None
    gps_latitude: float | None
    gps_longitude: float | None
    gps_altitude: float | None


class ScanResult(BaseModel):
    added: int
    updated: int
    removed: int
    thumbnails_generated: int
    ffprobe_available: bool
    ffmpeg_available: bool


class ScanRunOut(BaseModel):
    id: int
    project_id: int
    started_at: str
    finished_at: str | None
    status: str
    scanned_count: int | None
    added_count: int | None
    updated_count: int | None
    missing_count: int | None
    skipped_count: int | None
    error_count: int | None
    duration_ms: int | None


class ScanErrorOut(BaseModel):
    id: int
    scan_run_id: int
    error_code: str
    severity: str
    relative_path: str | None
    message: str
    created_at: str


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
        is_missing=bool(row["is_missing"]),
        missing_since=row["missing_since"],
        last_seen_at=row["last_seen_at"],
        container_format=row["container_format"],
        audio_codec=row["audio_codec"],
        frame_rate=row["frame_rate"],
        bit_rate=row["bit_rate"],
        rotation=row["rotation"],
        captured_at=row["captured_at"],
        gps_latitude=row["gps_latitude"],
        gps_longitude=row["gps_longitude"],
        gps_altitude=row["gps_altitude"],
    )


def _scan_run_out(row: sqlite3.Row) -> ScanRunOut:
    return ScanRunOut(
        id=row["id"],
        project_id=row["project_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        scanned_count=row["scanned_count"],
        added_count=row["added_count"],
        updated_count=row["updated_count"],
        missing_count=row["missing_count"],
        skipped_count=row["skipped_count"],
        error_count=row["error_count"],
        duration_ms=row["duration_ms"],
    )


def _scan_run_row(
    conn: sqlite3.Connection, project_id: int, scan_run_id: int
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM scan_runs WHERE id = ? AND project_id = ?",
        (scan_run_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="スキャン実行記録が見つかりません")
    return row


def _scan_error_out(row: sqlite3.Row) -> ScanErrorOut:
    return ScanErrorOut(
        id=row["id"],
        scan_run_id=row["scan_run_id"],
        error_code=row["error_code"],
        severity=row["severity"],
        relative_path=row["relative_path"],
        message=row["message"],
        created_at=row["created_at"],
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

    scan_run_id, started_monotonic = scan_runs.start_scan_run(conn, project_id)
    # 'running'行を即commitする。以降で例外が起きても、FastAPIの
    # db_connディペンデンシはyield後のcommitを実行しない(例外がそのまま
    # 呼び出し元へ伝播するため)ので、finished/failed更新は下のexcept節で
    # 明示的にcommitする。
    conn.commit()

    # 例外発生時にscan_errorsへ記録する「どのファイルを処理中だったか」。
    # 候補列挙自体で例外が起きた場合はNoneのまま(対象ファイル不明)。
    current_path: Path | None = None
    try:
        found = sorted(
            p for p in scan.iter_scan_candidates(folder) if media.is_video_file(p)
        )
        now = now_iso()
        thumbnails_dir = get_thumbnails_dir()

        added = updated = skipped = thumbnails_generated = 0
        for path in found:
            current_path = path
            file_path = str(path)
            existing = conn.execute(
                "SELECT * FROM videos WHERE project_id = ? AND file_path = ?",
                (project_id, file_path),
            ).fetchone()

            stat = path.stat()
            current_size = stat.st_size
            current_mtime = stat.st_mtime

            # 差分判定: 既存行があり、missingでもなく、size/mtimeが両方
            # 一致する場合のみ「変更なし」としてmetadata取得はskipする。
            # missingからの復元は常に更新扱いにする(PR #14のmissing判定
            # とは独立させるため、size/mtime一致でも復元はskipしない)。
            if (
                existing is not None
                and not existing["is_missing"]
                and existing["size_bytes"] == current_size
                and existing["file_mtime"] == current_mtime
            ):
                # metadata(probe_metadata/thumbnail)・size・mtimeはそのまま
                # 維持し、今回のスキャンで存在確認できた時刻としてlast_seen_at
                # だけを更新する。updated_countは増やさない。
                conn.execute(
                    "UPDATE videos SET last_seen_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
                skipped += 1
                continue

            meta = media.probe_metadata(path) or {}
            values = (
                current_size,
                meta.get("duration_seconds"),
                meta.get("width"),
                meta.get("height"),
                meta.get("codec"),
                now,
                current_mtime,
                meta.get("container_format"),
                meta.get("audio_codec"),
                meta.get("frame_rate"),
                meta.get("bit_rate"),
                meta.get("rotation"),
                meta.get("captured_at"),
                meta.get("gps_latitude"),
                meta.get("gps_longitude"),
                meta.get("gps_altitude"),
            )
            if existing is None:
                cur = conn.execute(
                    "INSERT INTO videos (project_id, file_name, file_path,"
                    " size_bytes, duration_seconds, width, height, codec,"
                    " scanned_at, file_mtime, container_format, audio_codec,"
                    " frame_rate, bit_rate, rotation, captured_at,"
                    " gps_latitude, gps_longitude, gps_altitude,"
                    " is_missing, missing_since, last_seen_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                    " ?, ?, ?, 0, NULL, ?)",
                    (project_id, path.name, file_path, *values, now),
                )
                video_id = cur.lastrowid
                added += 1
            else:
                # 通常の再検出(size/mtime変更あり)・missingからの復元
                # (is_missing=1だった行が再度見つかった場合)のどちらも
                # ここを通る。復元は別カウンタを持たずupdated_countへ含める。
                # GPSタグが今回消えていればNULLへ上書きされる(旧値は残さない)。
                video_id = existing["id"]
                conn.execute(
                    "UPDATE videos SET size_bytes = ?, duration_seconds = ?,"
                    " width = ?, height = ?, codec = ?, scanned_at = ?,"
                    " file_mtime = ?, container_format = ?, audio_codec = ?,"
                    " frame_rate = ?, bit_rate = ?, rotation = ?,"
                    " captured_at = ?, gps_latitude = ?, gps_longitude = ?,"
                    " gps_altitude = ?, is_missing = 0, missing_since = NULL,"
                    " last_seen_at = ? WHERE id = ?",
                    (*values, now, video_id),
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

        # フォルダから消えたファイルは物理削除せず、is_missing=1へ遷移させる
        # (論理削除)。サムネイルは復元時に再利用できるよう残す。
        current_path = None
        found_set = {str(p) for p in found}
        removed = scan_missing.mark_newly_missing(conn, project_id, found_set, now)
    except Exception as exc:
        # 1. このスキャン試行中にvideosへ加えた変更(候補列挙後にcommitされて
        #    いないINSERT/UPDATE/DELETE)をrollbackし、失敗したスキャンの
        #    部分的な結果がDBへ残らないようにする。scan_runsの'running'行は
        #    tryブロックへ入る前にcommit済みなのでrollbackの影響を受けない。
        conn.rollback()
        # 2. rollback後の新しいトランザクションでscan_errorを1件保存する。
        error_code, message = scan_errors.classify_scan_exception(exc)
        relative_path = scan_errors.safe_relative_path(current_path, folder)
        scan_errors.record_scan_error(
            conn,
            scan_run_id,
            error_code=error_code,
            message=message,
            relative_path=relative_path,
        )
        # 3. scan_runsをfailedへ更新し、4. error_countを実際に保存された
        #    scan_errors件数に合わせる。
        error_count = scan_errors.count_scan_errors(conn, scan_run_id)
        scan_runs.finish_scan_run(
            conn,
            scan_run_id,
            status="failed",
            counts=scan_runs.ScanRunCounts(error_count=error_count),
            started_monotonic=started_monotonic,
        )
        # 5. scan_error保存とfailed更新を同じ最終commitにまとめる。
        conn.commit()
        # 6. 元の例外を再送出する。
        raise

    scan_runs.finish_scan_run(
        conn,
        scan_run_id,
        status="finished",
        counts=scan_runs.ScanRunCounts(
            scanned_count=len(found),
            added_count=added,
            updated_count=updated,
            missing_count=removed,
            skipped_count=skipped,
        ),
        started_monotonic=started_monotonic,
    )

    return ScanResult(
        added=added,
        updated=updated,
        removed=removed,
        thumbnails_generated=thumbnails_generated,
        ffprobe_available=media.ffprobe_available(),
        ffmpeg_available=media.ffmpeg_available(),
    )


@app.get("/api/projects/{project_id}/scan_runs")
def list_scan_runs(project_id: int, conn: DbConn) -> list[ScanRunOut]:
    _project_row(conn, project_id)
    rows = conn.execute(
        "SELECT * FROM scan_runs WHERE project_id = ? ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    return [_scan_run_out(row) for row in rows]


@app.get("/api/projects/{project_id}/scan_runs/{scan_run_id}/errors")
def list_scan_run_errors(
    project_id: int, scan_run_id: int, conn: DbConn
) -> list[ScanErrorOut]:
    _project_row(conn, project_id)
    _scan_run_row(conn, project_id, scan_run_id)
    rows = scan_errors.list_scan_errors(conn, scan_run_id)
    return [_scan_error_out(row) for row in rows]


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
