import math

from app.media import (
    _normalize_bit_rate,
    _normalize_captured_at,
    _normalize_frame_rate,
    _normalize_rotation,
    _parse_ffprobe_json,
)


def _sample_ffprobe_json(**overrides) -> dict:
    data = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
        "format": {
            "duration": "12.5",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "bit_rate": "1234567",
            "tags": {"creation_time": "2026-01-02T03:04:05.000000Z"},
        },
    }
    data.update(overrides)
    return data


# --- _parse_ffprobe_json: normal cases -----------------------------------------


def test_parse_ffprobe_json_extracts_all_adopted_fields() -> None:
    result = _parse_ffprobe_json(_sample_ffprobe_json())

    assert result["duration_seconds"] == 12.5
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["codec"] == "h264"
    assert result["container_format"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert result["audio_codec"] == "aac"
    assert result["frame_rate"] == 30000 / 1001
    assert result["bit_rate"] == 1234567
    assert result["captured_at"] == "2026-01-02T03:04:05+00:00"


def test_parse_ffprobe_json_selects_first_video_stream_deterministically() -> None:
    data = _sample_ffprobe_json(
        streams=[
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
            },
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
            },
        ]
    )
    result = _parse_ffprobe_json(data)
    assert result["codec"] == "h264"
    assert result["width"] == 1920


def test_parse_ffprobe_json_audio_codec_none_without_audio_stream() -> None:
    data = _sample_ffprobe_json(
        streams=[
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}
        ]
    )
    result = _parse_ffprobe_json(data)
    assert result["audio_codec"] is None


# --- missing / malformed structures do not raise -------------------------------


def test_parse_ffprobe_json_handles_missing_format() -> None:
    result = _parse_ffprobe_json({"streams": []})
    assert result["duration_seconds"] is None
    assert result["container_format"] is None
    assert result["bit_rate"] is None
    assert result["captured_at"] is None


def test_parse_ffprobe_json_handles_missing_streams() -> None:
    result = _parse_ffprobe_json({"format": {}})
    assert result["width"] is None
    assert result["codec"] is None
    assert result["audio_codec"] is None
    assert result["frame_rate"] is None
    assert result["rotation"] is None


def test_parse_ffprobe_json_handles_completely_empty_dict() -> None:
    result = _parse_ffprobe_json({})
    assert result == {
        "duration_seconds": None,
        "width": None,
        "codec": None,
        "height": None,
        "container_format": None,
        "audio_codec": None,
        "frame_rate": None,
        "bit_rate": None,
        "rotation": None,
        "captured_at": None,
    }


def test_parse_ffprobe_json_handles_non_list_streams_and_non_dict_format() -> None:
    result = _parse_ffprobe_json({"streams": "not-a-list", "format": "not-a-dict"})
    assert result["width"] is None
    assert result["container_format"] is None


def test_parse_ffprobe_json_handles_missing_keys_in_stream_and_format() -> None:
    data = {"streams": [{"codec_type": "video"}], "format": {}}
    result = _parse_ffprobe_json(data)
    assert result["width"] is None
    assert result["codec"] is None
    assert result["duration_seconds"] is None


# --- N/A, empty string, invalid values -> None ---------------------------------


def test_parse_ffprobe_json_treats_na_and_empty_string_as_none() -> None:
    data = _sample_ffprobe_json(
        format={
            "duration": "12.5",
            "format_name": "N/A",
            "bit_rate": "",
            "tags": {"creation_time": ""},
        }
    )
    result = _parse_ffprobe_json(data)
    assert result["container_format"] is None
    assert result["bit_rate"] is None
    assert result["captured_at"] is None


def test_parse_ffprobe_json_treats_invalid_duration_as_none() -> None:
    data = _sample_ffprobe_json(format={"duration": "not-a-number"})
    result = _parse_ffprobe_json(data)
    assert result["duration_seconds"] is None


# --- frame_rate normalization ----------------------------------------------------


def test_normalize_frame_rate_parses_fraction() -> None:
    assert _normalize_frame_rate("30000/1001") == 30000 / 1001
    assert _normalize_frame_rate("25/1") == 25.0


def test_normalize_frame_rate_zero_denominator_is_none() -> None:
    assert _normalize_frame_rate("0/0") is None
    assert _normalize_frame_rate("30/0") is None


def test_normalize_frame_rate_na_and_empty_are_none() -> None:
    assert _normalize_frame_rate("N/A") is None
    assert _normalize_frame_rate("") is None
    assert _normalize_frame_rate(None) is None


def test_normalize_frame_rate_rejects_nan_and_infinity() -> None:
    assert _normalize_frame_rate("nan") is None
    assert _normalize_frame_rate("inf") is None
    assert _normalize_frame_rate("nan/1") is None
    assert _normalize_frame_rate("1/nan") is None


def test_normalize_frame_rate_rejects_negative() -> None:
    assert _normalize_frame_rate("-30/1") is None


def test_normalize_frame_rate_accepts_plain_numeric_string() -> None:
    assert _normalize_frame_rate("29.97") == 29.97


# --- bit_rate normalization -------------------------------------------------------


def test_normalize_bit_rate_parses_valid_string() -> None:
    assert _normalize_bit_rate("1234567") == 1234567


def test_normalize_bit_rate_rejects_negative_and_invalid() -> None:
    assert _normalize_bit_rate("-100") is None
    assert _normalize_bit_rate("not-a-number") is None
    assert _normalize_bit_rate("N/A") is None
    assert _normalize_bit_rate("") is None
    assert _normalize_bit_rate(None) is None


def test_normalize_bit_rate_rejects_nan_and_infinity() -> None:
    assert _normalize_bit_rate("nan") is None
    assert _normalize_bit_rate("inf") is None


# --- rotation normalization --------------------------------------------------------


def test_normalize_rotation_from_side_data_list() -> None:
    video_stream = {
        "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]
    }
    assert _normalize_rotation(video_stream) == 270


def test_normalize_rotation_from_tags_rotate_fallback() -> None:
    video_stream = {"tags": {"rotate": "180"}}
    assert _normalize_rotation(video_stream) == 180


def test_normalize_rotation_side_data_list_takes_priority_over_tags() -> None:
    video_stream = {
        "side_data_list": [{"rotation": 90}],
        "tags": {"rotate": "180"},
    }
    assert _normalize_rotation(video_stream) == 90


def test_normalize_rotation_missing_is_none() -> None:
    assert _normalize_rotation({}) is None


def test_normalize_rotation_non_integer_is_none() -> None:
    video_stream = {"tags": {"rotate": "12.5"}}
    assert _normalize_rotation(video_stream) is None
    video_stream = {"tags": {"rotate": "not-a-number"}}
    assert _normalize_rotation(video_stream) is None


# --- captured_at -------------------------------------------------------------------


def test_normalize_captured_at_accepts_zulu_suffix() -> None:
    result = _normalize_captured_at({"creation_time": "2026-01-02T03:04:05.000000Z"})
    assert result == "2026-01-02T03:04:05+00:00"


def test_normalize_captured_at_accepts_explicit_offset() -> None:
    result = _normalize_captured_at({"creation_time": "2026-01-02T12:04:05+09:00"})
    assert result == "2026-01-02T03:04:05+00:00"


def test_normalize_captured_at_rejects_value_without_timezone() -> None:
    # タイムゾーン不明の値をUTCと断定しない。
    result = _normalize_captured_at({"creation_time": "2026-01-02T03:04:05"})
    assert result is None


def test_normalize_captured_at_rejects_unparseable_and_missing() -> None:
    assert _normalize_captured_at({"creation_time": "not-a-date"}) is None
    assert _normalize_captured_at({}) is None
    assert _normalize_captured_at({"creation_time": "N/A"}) is None
    assert _normalize_captured_at({"creation_time": ""}) is None


def test_normalize_captured_at_does_not_use_other_tags() -> None:
    # GPS等の他タグや代用元は一切見ない。
    result = _normalize_captured_at({"gps_latitude": "35.0", "date": "2026-01-02"})
    assert result is None


def test_frame_rate_never_returns_nan_or_inf() -> None:
    for value in ("nan/1", "1/0", "inf/1", "-1/1"):
        result = _normalize_frame_rate(value)
        assert result is None or (not math.isnan(result) and not math.isinf(result))
