"""動画の論理削除(missing)状態管理。

物理削除は行わず、videos.is_missing / missing_since / last_seen_at で
状態を管理する。ファイルの検出・復元自体はscan_project(app/main.py)が
行い、このモジュールは「今回のスキャンで見つからなかった既存動画を
missingへ遷移させる」処理だけを担当する。

missing遷移はスキャン全体が正常に完了した場合のみ呼び出すこと
(呼び出し側のtry/exceptで、例外発生時はrollbackされ呼ばれない)。
"""

import sqlite3


def mark_newly_missing(
    conn: sqlite3.Connection,
    project_id: int,
    found_file_paths: set[str],
    now: str,
) -> int:
    """今回のスキャンで見つからなかった既存動画をmissingへ遷移させる。

    既にis_missing=1の行は対象外(missing_sinceを上書きしない)。
    戻り値は新たにmissingへ遷移した件数。
    """
    candidates = conn.execute(
        "SELECT id, file_path FROM videos"
        " WHERE project_id = ? AND is_missing = 0",
        (project_id,),
    ).fetchall()
    newly_missing_ids = [
        row["id"] for row in candidates if row["file_path"] not in found_file_paths
    ]
    for video_id in newly_missing_ids:
        conn.execute(
            "UPDATE videos SET is_missing = 1, missing_since = ? WHERE id = ?",
            (now, video_id),
        )
    return len(newly_missing_ids)
