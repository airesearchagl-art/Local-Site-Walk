"""FFprobe/FFmpegラッパー。

どちらも存在しない環境でもアプリ本体は動作し、メタデータ・サムネイルだけが
欠落する(graceful degradation)。外部サービスへの送信は行わない。
"""

import json
import logging
import math
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("local_site_walk.media")

VIDEO_EXTENSIONS = {".mp4", ".mov"}

PROBE_TIMEOUT_SECONDS = 30
THUMBNAIL_TIMEOUT_SECONDS = 60

# ffprobeのformat.tags内で撮影日時として採用する唯一のキー。他のタグや
# ファイルシステムのmtimeは撮影日時として代用しない。
_CAPTURED_AT_TAG = "creation_time"


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def _clean_probe_string(value: object) -> str | None:
    """ffprobeの文字列値を正規化する。空文字・'N/A'相当はNoneにする。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value == "" or value.upper() == "N/A":
        return None
    return value


def _to_finite_float(value: object) -> float | None:
    """数値へ安全に変換する。NaN・Infinity・変換不能な値はNoneにする。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _normalize_frame_rate(value: object) -> float | None:
    """"30000/1001"のような分数、"25/1"、通常の数値文字列を安全にfloat化する。

    denominatorが0、"N/A"、空文字、不正値、NaN/Infinity、負数はNoneにする。
    丸め込みは行わずREALとして扱える精度のまま返す。
    """
    text = _clean_probe_string(value)
    if text is None:
        return None
    if "/" in text:
        parts = text.split("/")
        if len(parts) != 2:
            return None
        numerator = _to_finite_float(parts[0])
        denominator = _to_finite_float(parts[1])
        if numerator is None or denominator is None or denominator == 0:
            return None
        rate = numerator / denominator
    else:
        rate = _to_finite_float(text)
        if rate is None:
            return None
    if rate < 0:
        return None
    return rate


def _normalize_bit_rate(value: object) -> int | None:
    """format.bit_rate(bit/s)を安全にintへ変換する。

    負数・'N/A'・空文字・不正値・NaN/InfinityはNoneにする。
    """
    if isinstance(value, str):
        value = _clean_probe_string(value)
        if value is None:
            return None
    if value is None:
        return None
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0:
        return None
    return number


def _normalize_rotation(video_stream: dict) -> int | None:
    """回転角を0〜360度未満の整数degreeへ正規化する。

    取得元優先順位: side_data_list内のrotationフィールド(新しいffmpegの
    Display Matrix表現) → tags.rotate(古いffmpegのstream tag)。どちらも
    無ければNone。整数として解釈できない値・小数値は推測せずNoneにする。
    """
    side_data_list = video_stream.get("side_data_list")
    if not isinstance(side_data_list, list):
        side_data_list = []

    raw_rotation: object = None
    for side_data in side_data_list:
        if isinstance(side_data, dict) and "rotation" in side_data:
            raw_rotation = side_data.get("rotation")
            break

    if raw_rotation is None:
        tags = video_stream.get("tags")
        if isinstance(tags, dict):
            raw_rotation = tags.get("rotate")

    if raw_rotation is None:
        return None
    number = _to_finite_float(raw_rotation)
    if number is None or number != int(number):
        return None
    return int(number) % 360


def _normalize_captured_at(format_tags: dict) -> str | None:
    """format.tags.creation_timeのみを撮影日時として採用する。

    タイムゾーン情報(Z・±HH:MM オフセット)が明示された値のみ受け付け、
    情報なしの値をUTCと断定したり、filesystem mtimeやGPSタグで代用したり
    しない。採用時はUTCへ変換しアプリ内の他タイムスタンプと同じ
    ISO8601・秒精度の書式に統一する。
    """
    text = _clean_probe_string(format_tags.get(_CAPTURED_AT_TAG))
    if text is None:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_ffprobe_json(data: dict) -> dict:
    """ffprobeのJSON出力から採用項目を抽出・正規化する。

    stream/format情報の欠落・型不正・キー欠落があっても例外を投げず、
    取得できた項目だけを埋めて返す(他は None)。
    """
    streams = data.get("streams")
    if not isinstance(streams, list):
        streams = []
    streams = [s for s in streams if isinstance(s, dict)]

    fmt = data.get("format")
    if not isinstance(fmt, dict):
        fmt = {}
    format_tags = fmt.get("tags")
    if not isinstance(format_tags, dict):
        format_tags = {}

    # primary video streamは先頭のvideo streamに固定する(既存ロジックを維持)。
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"), None
    )
    # audio codecは最初の有効なaudio streamから取得する。
    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"), None
    )

    duration_raw = fmt.get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None

    frame_rate = None
    rotation = None
    if video_stream is not None:
        frame_rate = _normalize_frame_rate(video_stream.get("avg_frame_rate"))
        if frame_rate is None:
            frame_rate = _normalize_frame_rate(video_stream.get("r_frame_rate"))
        rotation = _normalize_rotation(video_stream)

    return {
        "duration_seconds": duration,
        "width": video_stream.get("width") if video_stream else None,
        # codec列は既存どおりvideo codecを表す(video_codecへのrenameはしない)。
        "codec": video_stream.get("codec_name") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "container_format": _clean_probe_string(fmt.get("format_name")),
        "audio_codec": (
            _clean_probe_string(audio_stream.get("codec_name"))
            if audio_stream is not None
            else None
        ),
        "frame_rate": frame_rate,
        "bit_rate": _normalize_bit_rate(fmt.get("bit_rate")),
        "rotation": rotation,
        "captured_at": _normalize_captured_at(format_tags),
    }


def probe_metadata(path: Path) -> dict | None:
    """duration/width/height/codecおよび拡張metadataを返す。取得できなければNone。"""
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

    return _parse_ffprobe_json(data)


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
