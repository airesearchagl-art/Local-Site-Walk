"""スキャン実行ログ(scan_runs)。

差分スキャン・削除検知・Diagnostics・Dashboard(Roadmap Phase 2以降)の基盤として、
スキャン1回ごとの開始・終了・集計値を記録する。このモジュール自体はスキャン処理
(全件スキャン・差分判定・削除検知)を行わず、実行結果の記録のみを担当する。

durationはウォールクロック時刻のずれに影響されないよう time.monotonic() で計測する
(scan_runs.started_at列はDB上の表示・検索用のISO8601文字列で、duration計算には使わない)。
"""

import sqlite3
import time
from dataclasses import dataclass

from .db import now_iso


@dataclass
class ScanRunCounts:
    scanned_count: int = 0
    added_count: int = 0
    updated_count: int = 0
    missing_count: int = 0
    skipped_count: int = 0
    error_count: int = 0


def start_scan_run(conn: sqlite3.Connection, project_id: int) -> tuple[int, float]:
    """scan_runsへ実行開始行(status='running')を作成する。

    戻り値は (scan_run_id, 計測開始時刻(time.monotonic())) のタプル。
    計測開始時刻はfinish_scan_run()のduration_ms計算にそのまま渡す。
    """
    cur = conn.execute(
        "INSERT INTO scan_runs (project_id, status) VALUES (?, 'running')",
        (project_id,),
    )
    return cur.lastrowid, time.monotonic()


def finish_scan_run(
    conn: sqlite3.Connection,
    scan_run_id: int,
    *,
    status: str,
    counts: ScanRunCounts,
    started_monotonic: float,
) -> None:
    """scan_runsへ終了時の集計値を書き込む。

    statusは 'finished'(正常終了) または 'failed'(異常終了) を渡す。
    例外発生時も呼び出し側がこの関数を呼べば、scan_runsは無音のまま
    'running' に残らない。
    """
    duration_ms = round((time.monotonic() - started_monotonic) * 1000)
    conn.execute(
        "UPDATE scan_runs SET finished_at = ?, status = ?, scanned_count = ?,"
        " added_count = ?, updated_count = ?, missing_count = ?,"
        " skipped_count = ?, error_count = ?, duration_ms = ? WHERE id = ?",
        (
            now_iso(),
            status,
            counts.scanned_count,
            counts.added_count,
            counts.updated_count,
            counts.missing_count,
            counts.skipped_count,
            counts.error_count,
            duration_ms,
            scan_run_id,
        ),
    )
