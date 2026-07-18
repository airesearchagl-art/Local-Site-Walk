"""FFprobe/FFmpegラッパー。

どちらも存在しない環境でもアプリ本体は動作し、メタデータ・サムネイルだけが
欠落する(graceful degradation)。外部サービスへの送信は行わない。
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("local_site_walk.media")

VIDEO_EXTENSIONS = {".mp4", ".mov"}

PROBE_TIMEOUT_SECONDS = 30
THUMBNAIL_TIMEOUT_SECONDS = 60


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def probe_metadata(path: Path) -> dict | None:
    """duration/width/height/codecを返す。取得できなければNone。"""
    if not ffprobe_available():
        return None
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffprobe 実行に失敗: %s (%s)", path.name, exc)
        return None
    if proc.returncode != 0:
        logger.warning("ffprobe が失敗: %s", path.name)
        return None
    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    duration_raw = data.get("format", {}).get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "duration_seconds": duration,
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "codec": video_stream.get("codec_name") if video_stream else None,
    }


def generate_thumbnail(video_path: Path, out_path: Path) -> bool:
    """動画からJPEGサムネイルを1枚生成する。成功したらTrue。"""
    if not ffmpeg_available():
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 冒頭すぎる真っ黒フレームを避けて1秒地点を試し、短い動画は先頭で再試行する
    for seek in ("1", "0"):
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", seek,
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", "scale=640:-2",
            str(out_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=THUMBNAIL_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("ffmpeg 実行に失敗: %s (%s)", video_path.name, exc)
            return False
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return True
    logger.warning("サムネイル生成に失敗: %s", video_path.name)
    return False
