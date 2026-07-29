"""FFprobe/FFmpegラッパー。

どちらも存在しない環境でもアプリ本体は動作し、メタデータ・サムネイルだけが
欠落する(graceful degradation)。外部サービスへの送信は行わない。
"""

import json
import logging
import math
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("local_site_walk.media")

VIDEO_EXTENSIONS = {".mp4", ".mov"}

PROBE_TIMEOUT_SECONDS = 30
THUMBNAIL_TIMEOUT_SECONDS = 60

# ffprobeのformat.tags内で撮影日時として採用する唯一のキー。他のタグや
# ファイルシステムのmtimeは撮影日時として代用しない。
_CAPTURED_AT_TAG = "creation_time"

# ISO 6709形式の位置情報文字列(例: "+35.6812+139.7671+44.000/")。
# 緯度・経度は符号必須、altitudeは省略可、末尾の"/"は必須(実際に
# ffmpeg/ffprobeが読み書きする形式に合わせる。手元で
# `ffmpeg -metadata location="+35.6812+139.7671+44.0/" ...`により
# 生成したmp4をffprobeした際に得られたformat.tags.locationの実値で確認済み)。
_GPS_ISO6709_RE = re.compile(
    r"^"
    r"(?P<lat>[+-]\d+(?:\.\d+)?)"
    r"(?P<lon>[+-]\d+(?:\.\d+)?)"
    r"(?P<alt>[+-]\d+(?:\.\d+)?)?"
    r"/$"
)

_GPS_LATITUDE_RANGE = (-90.0, 90.0)
_GPS_LONGITUDE_RANGE = (-180.0, 180.0)

# GPS位置情報タグの候補キー。手元で生成したffmpeg出力ではformat.tagsへ
# "location"/"location-eng"として書き込まれることを実測で確認した。
# "com.apple.quicktime.location.ISO6709"はiPhone等の実撮影動画で使われる
# ことが広く知られている等価なQuickTimeタグ名で、同じISO 6709文字列形式を
# 値に持つ(ffmpegのmovマルチプレクサでは生成できなかったためparserの
# 単体テストではJSON fixtureとして直接検証する)。優先順位はこの並び順
# (先頭ほど優先)。
_GPS_TAG_KEYS: tuple[str, ...] = (
    "location",
    "com.apple.quicktime.location.ISO6709",
    "location-eng",
)


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


def _parse_iso6709_location(
    value: object,
) -> tuple[float | None, float | None, float | None]:
    """ISO 6709形式の位置情報文字列を(latitude, longitude, altitude)へ変換する。

    - 緯度・経度は符号(+/-)必須(北緯・東経を正、南緯・西経を負とする)。
    - 末尾の"/"は必須(省略された文字列は無効とする)。
    - altitudeは省略可。存在すれば緯度・経度と同じ数値表記のみ受け付ける。
    - 数値以外・数値の過不足・カンマ小数・符号なし・NaN/Infinity相当・
      末尾"/"欠落・余分な文字はすべて無効とし、(None, None, None)を返す。
    - 緯度・経度のどちらかでも範囲外(緯度: -90〜90、経度: -180〜180)の
      場合は、altitudeが有効な数値であっても位置情報全体を
      (None, None, None)にする(片方だけの推測保存はしない)。
    - 小数点以下の丸め込みは行わず、eval等の危険な変換も行わない。
    - 例外を外へ一切漏らさない。
    """
    text = _clean_probe_string(value)
    if text is None:
        return None, None, None

    match = _GPS_ISO6709_RE.match(text)
    if match is None:
        return None, None, None

    latitude = _to_finite_float(match.group("lat"))
    longitude = _to_finite_float(match.group("lon"))
    if latitude is None or longitude is None:
        return None, None, None
    if not (_GPS_LATITUDE_RANGE[0] <= latitude <= _GPS_LATITUDE_RANGE[1]):
        return None, None, None
    if not (_GPS_LONGITUDE_RANGE[0] <= longitude <= _GPS_LONGITUDE_RANGE[1]):
        return None, None, None

    altitude_text = match.group("alt")
    altitude = _to_finite_float(altitude_text) if altitude_text is not None else None

    return latitude, longitude, altitude


def _extract_gps_from_tags(
    tags: dict,
) -> tuple[float | None, float | None, float | None]:
    """tags dict内のGPS候補キーを優先順位順に試し、最初に有効な値を返す。

    高優先度キーが存在しても値が不正(パース失敗・範囲外)であれば
    次の候補キーへフォールバックする。全候補が無効ならNone3つを返す。
    """
    for key in _GPS_TAG_KEYS:
        if key not in tags:
            continue
        latitude, longitude, altitude = _parse_iso6709_location(tags.get(key))
        if latitude is not None and longitude is not None:
            return latitude, longitude, altitude
    return None, None, None


def _extract_gps(
    format_tags: dict, video_stream: dict | None
) -> tuple[float | None, float | None, float | None]:
    """format.tagsを優先し、無効ならprimary video streamのtagsを試す。

    GPS位置情報はコンテナ全体に対する属性として埋め込まれるのが一般的
    (実測でもformat.tagsに現れる)なため、stream.tagsはあくまで
    フォールバックとして扱う。
    """
    latitude, longitude, altitude = _extract_gps_from_tags(format_tags)
    if latitude is not None and longitude is not None:
        return latitude, longitude, altitude

    if video_stream is not None:
        stream_tags = video_stream.get("tags")
        if isinstance(stream_tags, dict):
            return _extract_gps_from_tags(stream_tags)

    return None, None, None


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

    gps_latitude, gps_longitude, gps_altitude = _extract_gps(
        format_tags, video_stream
    )

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
        "gps_latitude": gps_latitude,
        "gps_longitude": gps_longitude,
        "gps_altitude": gps_altitude,
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
    """動画からJPEGサムネイルを1枚生成する。成功したらTrue。

    ffmpegの出力はout_pathと同じディレクトリ内の一時ファイルへ書き込み、
    成功時のみos.replace()でout_pathへatomicに置き換える。これにより、
    生成途中でffmpegが失敗しても既存の有効なthumbnail(再試行対象が
    別ファイルの場合)を壊さず、失敗時に中途半端な出力ファイルが
    out_pathへ残ることもない。一時ファイルは成功・失敗いずれの場合も
    処理後に残さない。
    """
    if not ffmpeg_available():
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 拡張子(.jpg)を末尾に残す。ffmpegは出力ファイル名の拡張子から
    # muxerを推測するため、拡張子が無い一時ファイル名だと出力形式を
    # 決定できずエラーになる。
    tmp_path = out_path.with_name(
        f".{out_path.stem}.tmp-{uuid.uuid4().hex}{out_path.suffix}"
    )
    try:
        # 冒頭すぎる真っ黒フレームを避けて1秒地点を試し、短い動画は先頭で再試行する
        for seek in ("1", "0"):
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", seek,
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=640:-2",
                str(tmp_path),
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
            if (
                proc.returncode == 0
                and tmp_path.exists()
                and tmp_path.stat().st_size > 0
            ):
                os.replace(tmp_path, out_path)
                return True
        logger.warning("サムネイル生成に失敗: %s", video_path.name)
        return False
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
