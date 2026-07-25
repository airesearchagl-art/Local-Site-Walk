"""スキャン実行エラーログ(scan_errors)。

1つのscan_run(app/scan_runs.py)に対して、発生したエラーを構造化して
複数件記録できるようにする。Diagnostics/Dashboard/Export(将来のPhase)で
再利用できる最小基盤であり、このモジュール自体はスキャン処理を行わない。

安全性の方針:
- 絶対パスはDB・APIへ一切保存しない(safe_relative_path()経由のみ)。
- secret・token・環境変数値・完全なstack trace・raw exception全文は
  保存しない(classify_scan_exception()が返す定型メッセージのみを使う)。
"""

import sqlite3
from pathlib import Path

from . import paths

# error_codeの一元管理。schema側のCHECK制約とは独立に、アプリ側で
# 許可する値をここで固定する。
#
# 現在の実装(classify_scan_exception)から実際に生成されるのは
# PERMISSION_DENIED / FILE_NOT_FOUND / DATABASE_ERROR / UNEXPECTED_ERROR
# のみ。BROKEN_SYMLINK / OUTSIDE_ROOT / METADATA_READ_FAILED は、
# paths.py(resolve_safe/is_within)・scan.py(iter_scan_candidates)・
# media.py(probe_metadata/generate_thumbnail)がいずれも例外を投げず
# None/False/skipで無音に処理する設計であるため、現時点のscan_project
# からは到達しない。将来これらの条件を明示的に例外として扱うようになった
# 場合のために語彙として予約している。
PERMISSION_DENIED = "permission_denied"
FILE_NOT_FOUND = "file_not_found"
BROKEN_SYMLINK = "broken_symlink"
OUTSIDE_ROOT = "outside_root"
METADATA_READ_FAILED = "metadata_read_failed"
DATABASE_ERROR = "database_error"
UNEXPECTED_ERROR = "unexpected_error"

ERROR_CODES = frozenset(
    {
        PERMISSION_DENIED,
        FILE_NOT_FOUND,
        BROKEN_SYMLINK,
        OUTSIDE_ROOT,
        METADATA_READ_FAILED,
        DATABASE_ERROR,
        UNEXPECTED_ERROR,
    }
)

_MESSAGES: dict[str, str] = {
    PERMISSION_DENIED: "ファイルまたはフォルダへのアクセスが拒否されました",
    FILE_NOT_FOUND: "ファイルが見つかりませんでした"
    "(スキャン中に削除された可能性があります)",
    BROKEN_SYMLINK: "リンク先が存在しないか無効です",
    OUTSIDE_ROOT: "登録フォルダの外を指しているため対象外にしました",
    METADATA_READ_FAILED: "動画メタデータの取得に失敗しました",
    DATABASE_ERROR: "データベース処理でエラーが発生しました",
    UNEXPECTED_ERROR: "予期しないエラーが発生しました",
}


def classify_scan_exception(exc: Exception) -> tuple[str, str]:
    """例外を(error_code, 定型message)へ正規化する。

    exc自体の文言・repr・tracebackはそのまま使わない。型で判別できる
    例外だけを個別分類し、それ以外はすべてunexpected_errorへ丸める。
    """
    if isinstance(exc, PermissionError):
        code = PERMISSION_DENIED
    elif isinstance(exc, FileNotFoundError):
        code = FILE_NOT_FOUND
    elif isinstance(exc, sqlite3.Error):
        code = DATABASE_ERROR
    else:
        code = UNEXPECTED_ERROR
    return code, _MESSAGES[code]


def safe_relative_path(path: Path | str | None, root: Path) -> str | None:
    """rootからの相対パス文字列を返す。

    root外・解決不能な場合はNoneを返す(絶対パスを一切外へ出さないための
    唯一の経路とする)。paths.resolve_safe()/is_within()と同じ安全判定を
    再利用する。
    """
    if path is None:
        return None
    resolved_root = paths.resolve_safe(root)
    resolved_path = paths.resolve_safe(Path(path))
    if resolved_root is None or resolved_path is None:
        return None
    if not paths.is_within(resolved_path, resolved_root):
        return None
    return resolved_path.relative_to(resolved_root).as_posix()


def record_scan_error(
    conn: sqlite3.Connection,
    scan_run_id: int,
    *,
    error_code: str,
    message: str,
    relative_path: str | None = None,
    severity: str = "error",
) -> None:
    """scan_errorsへ1件記録する。未知のerror_codeはunexpected_errorへ丸める。"""
    if error_code not in ERROR_CODES:
        error_code = UNEXPECTED_ERROR
    conn.execute(
        "INSERT INTO scan_errors (scan_run_id, error_code, severity,"
        " relative_path, message) VALUES (?, ?, ?, ?, ?)",
        (scan_run_id, error_code, severity, relative_path, message),
    )


def list_scan_errors(conn: sqlite3.Connection, scan_run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM scan_errors WHERE scan_run_id = ? ORDER BY id",
        (scan_run_id,),
    ).fetchall()


def count_scan_errors(conn: sqlite3.Connection, scan_run_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM scan_errors WHERE scan_run_id = ?",
        (scan_run_id,),
    ).fetchone()
    return row[0]
