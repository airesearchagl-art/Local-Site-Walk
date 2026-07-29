import math

from app.media import (
    _extract_gps,
    _extract_gps_from_tags,
    _parse_ffprobe_json,
    _parse_iso6709_location,
)

# --- parser: valid values -----------------------------------------------------------


def test_parse_iso6709_positive_lat_lon() -> None:
    assert _parse_iso6709_location("+35.6812+139.7671/") == (35.6812, 139.7671, None)


def test_parse_iso6709_negative_lat_lon() -> None:
    assert _parse_iso6709_location("-33.8688-070.6693/") == (
        -33.8688,
        -70.6693,
        None,
    )


def test_parse_iso6709_with_altitude() -> None:
    result = _parse_iso6709_location("+35.6812+139.7671+44.0/")
    assert result == (35.6812, 139.7671, 44.0)


def test_parse_iso6709_negative_altitude() -> None:
    result = _parse_iso6709_location("-33.8688+151.2093-12.5/")
    assert result == (-33.8688, 151.2093, -12.5)


def test_parse_iso6709_without_altitude() -> None:
    result = _parse_iso6709_location("+35.6812+139.7671/")
    assert result[2] is None


def test_parse_iso6709_trailing_slash_required() -> None:
    # 末尾"/"は必須と決定しているため、省略された文字列は無効(全体None)。
    assert _parse_iso6709_location("+35.6812+139.7671") == (None, None, None)


def test_parse_iso6709_equator_and_prime_meridian() -> None:
    assert _parse_iso6709_location("+0.0000+0.0000/") == (0.0, 0.0, None)


def test_parse_iso6709_latitude_boundary_values() -> None:
    assert _parse_iso6709_location("+90.0+0.0/") == (90.0, 0.0, None)
    assert _parse_iso6709_location("-90.0+0.0/") == (-90.0, 0.0, None)


def test_parse_iso6709_longitude_boundary_values() -> None:
    assert _parse_iso6709_location("+0.0+180.0/") == (0.0, 180.0, None)
    assert _parse_iso6709_location("+0.0-180.0/") == (0.0, -180.0, None)


# --- parser: invalid values → (None, None, None) ------------------------------------


def test_parse_iso6709_latitude_out_of_range() -> None:
    assert _parse_iso6709_location("+90.1+0.0/") == (None, None, None)
    assert _parse_iso6709_location("-90.1+0.0/") == (None, None, None)


def test_parse_iso6709_longitude_out_of_range() -> None:
    assert _parse_iso6709_location("+0.0+180.1/") == (None, None, None)
    assert _parse_iso6709_location("+0.0-180.1/") == (None, None, None)


def test_parse_iso6709_out_of_range_lat_does_not_leak_altitude() -> None:
    # 緯度が範囲外ならaltitudeが有効値でも全体をNoneにする(片方だけ残さない)。
    assert _parse_iso6709_location("+95.0+139.7671+44.0/") == (None, None, None)


def test_parse_iso6709_empty_string_is_none() -> None:
    assert _parse_iso6709_location("") == (None, None, None)


def test_parse_iso6709_none_is_none() -> None:
    assert _parse_iso6709_location(None) == (None, None, None)


def test_parse_iso6709_malformed_string_is_none() -> None:
    assert _parse_iso6709_location("not-a-location") == (None, None, None)


def test_parse_iso6709_missing_number_is_none() -> None:
    # 緯度のみ(経度が欠落)。
    assert _parse_iso6709_location("+35.6812/") == (None, None, None)


def test_parse_iso6709_altitude_only_is_none() -> None:
    # 数値が1つしかない文字列は緯度・経度どちらも成立しないためNone。
    assert _parse_iso6709_location("+44.0/") == (None, None, None)


def test_parse_iso6709_too_many_numbers_is_none() -> None:
    assert _parse_iso6709_location("+35.6812+139.7671+44.0+99.0/") == (
        None,
        None,
        None,
    )


def test_parse_iso6709_nan_is_none() -> None:
    assert _parse_iso6709_location("+nan+139.7671/") == (None, None, None)


def test_parse_iso6709_infinity_is_none() -> None:
    assert _parse_iso6709_location("+inf+139.7671/") == (None, None, None)


def test_parse_iso6709_missing_sign_is_none() -> None:
    assert _parse_iso6709_location("35.6812+139.7671/") == (None, None, None)
    assert _parse_iso6709_location("+35.6812139.7671/") == (None, None, None)


def test_parse_iso6709_locale_comma_decimal_is_rejected() -> None:
    assert _parse_iso6709_location("+35,6812+139,7671/") == (None, None, None)


def test_parse_iso6709_extra_characters_rejected() -> None:
    assert _parse_iso6709_location("GPS+35.6812+139.7671/") == (None, None, None)
    assert _parse_iso6709_location("+35.6812+139.7671/extra") == (None, None, None)


def test_parse_iso6709_does_not_raise_on_unexpected_types() -> None:
    for value in (12345, 3.14, {"a": 1}, [1, 2], b"+35.6812+139.7671/"):
        assert _parse_iso6709_location(value) == (None, None, None)


def test_parse_iso6709_never_returns_nan_or_inf() -> None:
    for value in ("+nan+139/", "+35+inf/", "-inf-inf/"):
        lat, lon, alt = _parse_iso6709_location(value)
        for component in (lat, lon, alt):
            assert component is None or (
                not math.isnan(component) and not math.isinf(component)
            )


# --- _extract_gps_from_tags: candidate keys & priority ------------------------------


def test_extract_gps_from_tags_location_key() -> None:
    result = _extract_gps_from_tags({"location": "+35.6812+139.7671+44.0/"})
    assert result == (35.6812, 139.7671, 44.0)


def test_extract_gps_from_tags_apple_quicktime_key() -> None:
    result = _extract_gps_from_tags(
        {"com.apple.quicktime.location.ISO6709": "+35.6812+139.7671+44.0/"}
    )
    assert result == (35.6812, 139.7671, 44.0)


def test_extract_gps_from_tags_location_eng_key() -> None:
    result = _extract_gps_from_tags({"location-eng": "+35.6812+139.7671+44.0/"})
    assert result == (35.6812, 139.7671, 44.0)


def test_extract_gps_from_tags_location_takes_priority_over_others() -> None:
    tags = {
        "location": "+1.0+2.0/",
        "com.apple.quicktime.location.ISO6709": "+3.0+4.0/",
        "location-eng": "+5.0+6.0/",
    }
    assert _extract_gps_from_tags(tags) == (1.0, 2.0, None)


def test_extract_gps_from_tags_apple_key_priority_over_location_eng() -> None:
    tags = {
        "com.apple.quicktime.location.ISO6709": "+3.0+4.0/",
        "location-eng": "+5.0+6.0/",
    }
    assert _extract_gps_from_tags(tags) == (3.0, 4.0, None)


def test_extract_gps_from_tags_falls_back_when_higher_priority_is_malformed() -> None:
    """高優先度キーが不正でも、低優先度キーが有効ならそちらを採用する。"""
    tags = {
        "location": "not-a-valid-location",
        "location-eng": "+5.0+6.0/",
    }
    assert _extract_gps_from_tags(tags) == (5.0, 6.0, None)


def test_extract_gps_from_tags_no_gps_tags_is_none() -> None:
    assert _extract_gps_from_tags({"encoder": "Lavf60"}) == (None, None, None)


def test_extract_gps_from_tags_all_candidates_malformed_is_none() -> None:
    tags = {"location": "bad", "location-eng": "also-bad"}
    assert _extract_gps_from_tags(tags) == (None, None, None)


# --- _extract_gps: format vs stream priority -----------------------------------------


def test_extract_gps_prefers_format_over_stream() -> None:
    format_tags = {"location": "+1.0+2.0/"}
    video_stream = {"tags": {"location": "+3.0+4.0/"}}
    assert _extract_gps(format_tags, video_stream) == (1.0, 2.0, None)


def test_extract_gps_falls_back_to_stream_when_format_has_no_gps() -> None:
    format_tags = {"encoder": "Lavf60"}
    video_stream = {"tags": {"location": "+3.0+4.0/"}}
    assert _extract_gps(format_tags, video_stream) == (3.0, 4.0, None)


def test_extract_gps_falls_back_to_stream_when_format_gps_malformed() -> None:
    format_tags = {"location": "not-valid"}
    video_stream = {"tags": {"location": "+3.0+4.0/"}}
    assert _extract_gps(format_tags, video_stream) == (3.0, 4.0, None)


def test_extract_gps_no_video_stream_uses_format_only() -> None:
    format_tags = {"location": "+1.0+2.0/"}
    assert _extract_gps(format_tags, None) == (1.0, 2.0, None)


def test_extract_gps_stream_without_tags_key() -> None:
    format_tags = {}
    video_stream = {}
    assert _extract_gps(format_tags, video_stream) == (None, None, None)


def test_extract_gps_stream_tags_non_dict_is_ignored() -> None:
    format_tags = {}
    video_stream = {"tags": "not-a-dict"}
    assert _extract_gps(format_tags, video_stream) == (None, None, None)


# --- _parse_ffprobe_json integration --------------------------------------------------


def test_parse_ffprobe_json_extracts_gps_from_format_tags() -> None:
    data = {
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
        "format": {
            "tags": {"location": "+35.6812+139.7671+44.0/"},
        },
    }
    result = _parse_ffprobe_json(data)
    assert result["gps_latitude"] == 35.6812
    assert result["gps_longitude"] == 139.7671
    assert result["gps_altitude"] == 44.0


def test_parse_ffprobe_json_no_gps_tags_is_none() -> None:
    data = {
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
        "format": {"tags": {}},
    }
    result = _parse_ffprobe_json(data)
    assert result["gps_latitude"] is None
    assert result["gps_longitude"] is None
    assert result["gps_altitude"] is None


def test_parse_ffprobe_json_no_format_or_streams_does_not_raise() -> None:
    assert _parse_ffprobe_json({})["gps_latitude"] is None
    assert _parse_ffprobe_json({"format": {}})["gps_latitude"] is None
    assert _parse_ffprobe_json({"streams": []})["gps_latitude"] is None


def test_parse_ffprobe_json_malformed_gps_does_not_break_other_metadata() -> None:
    """GPSタグが不正でも、codec等の既存metadata取得は継続する。"""
    data = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
            }
        ],
        "format": {
            "duration": "12.5",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "tags": {"location": "totally-invalid-gps-string"},
        },
    }
    result = _parse_ffprobe_json(data)
    assert result["gps_latitude"] is None
    assert result["codec"] == "h264"
    assert result["width"] == 1920
    assert result["duration_seconds"] == 12.5
    assert result["container_format"] == "mov,mp4,m4a,3gp,3g2,mj2"


def test_parse_ffprobe_json_gps_does_not_affect_other_fields_when_valid() -> None:
    """有効なGPS抽出が、他のmetadataフィールドの値を変えないことを確認する。"""
    data = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 480,
            }
        ],
        "format": {
            "duration": "5.0",
            "tags": {"location": "+35.6812+139.7671/"},
        },
    }
    result = _parse_ffprobe_json(data)
    assert result["gps_latitude"] == 35.6812
    assert result["width"] == 640
    assert result["height"] == 480
    assert result["duration_seconds"] == 5.0
