"""Tests for file_organizer.exif — date, camera, and GPS extraction logic."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

from file_organizer.exif import (
    _dms_to_decimal,
    _extract_camera,
    _extract_gps_from_exif,
    _from_ffprobe,
    _from_mtime,
    _parse_exif_date,
    _parse_ffprobe_date,
    _parse_iso6709,
    get_date,
    get_metadata,
)

# ---------------------------------------------------------------------------
# get_metadata
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_extracts_date_and_camera(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {
            "EXIF DateTimeOriginal": _FakeTag("2022:06:01 12:00:00"),
            "Image Make": _FakeTag("Sony"),
            "Image Model": _FakeTag("A7III"),
        }
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_metadata(fake_file)

        assert result["date"] == datetime(2022, 6, 1, 12, 0, 0)
        assert result["camera"] == "Sony A7III"

    def test_handles_missing_camera_info(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {"EXIF DateTimeOriginal": _FakeTag("2022:06:01 12:00:00")}
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_metadata(fake_file)

        assert result["camera"] is None

    def test_avoids_duplicate_make_in_model(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {
            "EXIF DateTimeOriginal": _FakeTag("2022:06:01 12:00:00"),
            "Image Make": _FakeTag("Apple"),
            "Image Model": _FakeTag("iPhone 15 Pro"),
        }
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_metadata(fake_file)

        assert result["camera"] == "iPhone 15 Pro"

    def test_includes_gps_in_metadata(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {
            "EXIF DateTimeOriginal": _FakeTag("2022:06:01 12:00:00"),
            "GPS GPSLatitude": _FakeGpsTag([_FakeRatio(48), _FakeRatio(51), _FakeRatio(24)]),
            "GPS GPSLatitudeRef": _FakeTag("N"),
            "GPS GPSLongitude": _FakeGpsTag([_FakeRatio(2), _FakeRatio(17), _FakeRatio(40)]),
            "GPS GPSLongitudeRef": _FakeTag("E"),
        }
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_metadata(fake_file)

        assert result["gps"] is not None
        lat, lon = result["gps"]
        assert abs(lat - 48.8567) < 0.01
        assert abs(lon - 2.2944) < 0.01

    def test_gps_is_none_when_absent(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {"EXIF DateTimeOriginal": _FakeTag("2022:06:01 12:00:00")}
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_metadata(fake_file)

        assert result["gps"] is None


# ---------------------------------------------------------------------------
# _extract_camera
# ---------------------------------------------------------------------------


class TestExtractCamera:
    def test_make_and_model(self):
        assert _extract_camera("Sony", "A7III") == "Sony A7III"

    def test_apple_iphone(self):
        assert _extract_camera("Apple", "iPhone 15 Pro") == "iPhone 15 Pro"

    def test_make_in_model(self):
        assert _extract_camera("Canon", "Canon EOS R5") == "Canon EOS R5"

    def test_model_only(self):
        assert _extract_camera("", "Pixel 8") == "Pixel 8"

    def test_make_only(self):
        assert _extract_camera("DJI", "") == "DJI"

    def test_empty(self):
        assert _extract_camera("", "") is None


# ---------------------------------------------------------------------------
# GPS extraction
# ---------------------------------------------------------------------------


class TestExtractGpsFromExif:
    def test_north_east(self):
        tags = {
            "GPS GPSLatitude": _FakeGpsTag([_FakeRatio(48), _FakeRatio(0), _FakeRatio(0)]),
            "GPS GPSLatitudeRef": _FakeTag("N"),
            "GPS GPSLongitude": _FakeGpsTag([_FakeRatio(2), _FakeRatio(0), _FakeRatio(0)]),
            "GPS GPSLongitudeRef": _FakeTag("E"),
        }
        result = _extract_gps_from_exif(tags)
        assert result == (48.0, 2.0)

    def test_south_west(self):
        tags = {
            "GPS GPSLatitude": _FakeGpsTag([_FakeRatio(33), _FakeRatio(0), _FakeRatio(0)]),
            "GPS GPSLatitudeRef": _FakeTag("S"),
            "GPS GPSLongitude": _FakeGpsTag([_FakeRatio(70), _FakeRatio(0), _FakeRatio(0)]),
            "GPS GPSLongitudeRef": _FakeTag("W"),
        }
        result = _extract_gps_from_exif(tags)
        assert result == (-33.0, -70.0)

    def test_missing_tags_returns_none(self):
        assert _extract_gps_from_exif({}) is None

    def test_partial_tags_returns_none(self):
        tags = {
            "GPS GPSLatitude": _FakeGpsTag([_FakeRatio(48), _FakeRatio(0), _FakeRatio(0)]),
            "GPS GPSLatitudeRef": _FakeTag("N"),
        }
        assert _extract_gps_from_exif(tags) is None


class TestDmsToDecimal:
    def test_whole_degrees(self):
        assert _dms_to_decimal([48, 0, 0]) == 48.0

    def test_degrees_minutes_seconds(self):
        result = _dms_to_decimal([48, 51, 24])
        assert abs(result - 48.8567) < 0.001


class TestParseIso6709:
    def test_standard_format(self):
        result = _parse_iso6709("+48.8584+002.2945+000.000/")
        assert result is not None
        assert abs(result[0] - 48.8584) < 0.0001
        assert abs(result[1] - 2.2945) < 0.0001

    def test_negative_coords(self):
        result = _parse_iso6709("-33.8688+151.2093/")
        assert result is not None
        assert result[0] < 0
        assert result[1] > 0

    def test_invalid_returns_none(self):
        assert _parse_iso6709("not a location") is None


# ---------------------------------------------------------------------------
# _parse_exif_date
# ---------------------------------------------------------------------------


class TestParseExifDate:
    def test_valid_date(self):
        result = _parse_exif_date("2023:08:15 10:30:00")
        assert result == datetime(2023, 8, 15, 10, 30, 0)

    def test_strips_whitespace(self):
        result = _parse_exif_date("  2024:01:01 00:00:00  ")
        assert result == datetime(2024, 1, 1, 0, 0, 0)

    def test_malformed_returns_none(self):
        assert _parse_exif_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_exif_date("") is None

    def test_partial_date_returns_none(self):
        assert _parse_exif_date("2023:08:15") is None


# ---------------------------------------------------------------------------
# get_date — EXIF path
# ---------------------------------------------------------------------------


class TestGetDateExif:
    def test_uses_datetime_original_when_present(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {"EXIF DateTimeOriginal": _FakeTag("2022:06:01 12:00:00")}
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_date(fake_file)

        assert result == datetime(2022, 6, 1, 12, 0, 0)

    def test_uses_image_datetime_as_fallback_tag(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {"Image DateTime": _FakeTag("2021:03:20 08:00:00")}
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_date(fake_file)

        assert result == datetime(2021, 3, 20, 8, 0, 0)

    def test_falls_back_to_mtime_when_no_exif(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        fake_file.write_bytes(b"\x00")

        with patch("file_organizer.exif.exifread.process_file", return_value={}):
            result = get_date(fake_file)

        expected = datetime.fromtimestamp(fake_file.stat().st_mtime)
        assert abs((result - expected).total_seconds()) < 1

    def test_falls_back_to_mtime_on_exifread_exception(self, tmp_path):
        fake_file = tmp_path / "bad.jpg"
        fake_file.write_bytes(b"\x00")

        with patch("file_organizer.exif.exifread.process_file", side_effect=OSError("boom")):
            result = get_date(fake_file)

        expected = datetime.fromtimestamp(fake_file.stat().st_mtime)
        assert abs((result - expected).total_seconds()) < 1

    def test_falls_back_to_mtime_on_malformed_exif_value(self, tmp_path):
        fake_file = tmp_path / "photo.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff")

        fake_tags = {"EXIF DateTimeOriginal": _FakeTag("garbage")}
        with patch("file_organizer.exif.exifread.process_file", return_value=fake_tags):
            result = get_date(fake_file)

        expected = datetime.fromtimestamp(fake_file.stat().st_mtime)
        assert abs((result - expected).total_seconds()) < 1


# ---------------------------------------------------------------------------
# _from_mtime
# ---------------------------------------------------------------------------


class TestFromMtime:
    def test_returns_datetime(self, tmp_path):
        f = tmp_path / "file.mp4"
        f.write_bytes(b"\x00")
        result = _from_mtime(f)
        assert isinstance(result, datetime)
        assert abs((result - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds()) < 1


# ---------------------------------------------------------------------------
# _parse_ffprobe_date
# ---------------------------------------------------------------------------


class TestParseFfprobeDate:
    def test_iso8601_with_fractional_and_z(self):
        result = _parse_ffprobe_date("2024-03-15T10:00:00.000000Z")
        assert result == datetime(2024, 3, 15, 10, 0, 0)

    def test_iso8601_without_fractional(self):
        result = _parse_ffprobe_date("2024-03-15T10:00:00Z")
        assert result == datetime(2024, 3, 15, 10, 0, 0)

    def test_space_separated(self):
        result = _parse_ffprobe_date("2024-03-15 10:00:00")
        assert result == datetime(2024, 3, 15, 10, 0, 0)

    def test_malformed_returns_none(self):
        assert _parse_ffprobe_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_ffprobe_date("") is None


# ---------------------------------------------------------------------------
# _from_ffprobe
# ---------------------------------------------------------------------------


def _ffprobe_output(tags: dict[str, str]) -> str:
    """Build a JSON string mimicking ffprobe -show_format output."""
    return json.dumps({"format": {"tags": tags}})


class TestFromFfprobe:
    def test_returns_none_when_ffprobe_not_installed(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        with patch("file_organizer.exif.shutil.which", return_value=None):
            result = _from_ffprobe(video)

        assert result["date"] is None
        assert result["camera"] is None
        assert result["gps"] is None

    def test_extracts_creation_time_and_camera(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        stdout = _ffprobe_output({
            "creation_time": "2024-03-15T10:00:00.000000Z",
            "com.apple.quicktime.make": "Apple",
            "com.apple.quicktime.model": "iPhone 15 Pro",
        })

        with (
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = stdout
            result = _from_ffprobe(video)

        assert result["date"] == datetime(2024, 3, 15, 10, 0, 0)
        assert result["camera"] == "iPhone 15 Pro"

    def test_extracts_gps_from_iso6709(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        stdout = _ffprobe_output({
            "creation_time": "2024-03-15T10:00:00.000000Z",
            "com.apple.quicktime.location.ISO6709": "+48.8584+002.2945+000.000/",
        })

        with (
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = stdout
            result = _from_ffprobe(video)

        assert result["gps"] is not None
        assert abs(result["gps"][0] - 48.8584) < 0.001

    def test_extracts_non_apple_camera(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        stdout = _ffprobe_output({
            "creation_time": "2024-01-01T08:00:00.000000Z",
            "com.apple.quicktime.make": "DJI",
            "com.apple.quicktime.model": "Mavic 3",
        })

        with (
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = stdout
            result = _from_ffprobe(video)

        assert result["camera"] == "DJI Mavic 3"

    def test_returns_none_on_ffprobe_failure(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        with (
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            result = _from_ffprobe(video)

        assert result["date"] is None
        assert result["camera"] is None

    def test_returns_none_on_subprocess_exception(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        with (
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run", side_effect=OSError("boom")),
        ):
            result = _from_ffprobe(video)

        assert result["date"] is None
        assert result["camera"] is None

    def test_date_only_no_camera(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        stdout = _ffprobe_output({"creation_time": "2024-06-01T12:00:00.000000Z"})

        with (
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = stdout
            result = _from_ffprobe(video)

        assert result["date"] == datetime(2024, 6, 1, 12, 0, 0)
        assert result["camera"] is None


# ---------------------------------------------------------------------------
# get_metadata — ffprobe integration
# ---------------------------------------------------------------------------


class TestGetMetadataFfprobe:
    def test_video_uses_ffprobe_for_camera(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        stdout = _ffprobe_output({
            "creation_time": "2024-03-15T10:00:00.000000Z",
            "com.apple.quicktime.make": "Apple",
            "com.apple.quicktime.model": "iPhone 15 Pro",
        })

        with (
            patch("file_organizer.exif.exifread.process_file", return_value={}),
            patch("file_organizer.exif.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("file_organizer.exif.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = stdout
            result = get_metadata(video)

        assert result["date"] == datetime(2024, 3, 15, 10, 0, 0)
        assert result["camera"] == "iPhone 15 Pro"

    def test_video_falls_back_to_mtime_when_no_ffprobe(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        with (
            patch("file_organizer.exif.exifread.process_file", return_value={}),
            patch("file_organizer.exif.shutil.which", return_value=None),
        ):
            result = get_metadata(video)

        expected = datetime.fromtimestamp(video.stat().st_mtime)
        assert abs((result["date"] - expected).total_seconds()) < 1
        assert result["camera"] is None

    def test_non_video_does_not_call_ffprobe(self, tmp_path):
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff")

        with (
            patch("file_organizer.exif.exifread.process_file", return_value={}),
            patch("file_organizer.exif.shutil.which") as mock_which,
        ):
            result = get_metadata(photo)

        mock_which.assert_not_called()
        assert result["camera"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeTag:
    """Minimal stand-in for an exifread IfdTag."""

    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:
        return self._value


class _FakeRatio:
    """Minimal stand-in for an exifread Ratio (GPS DMS values)."""

    def __init__(self, value: float) -> None:
        self._value = value

    def __float__(self) -> float:
        return float(self._value)


class _FakeGpsTag:
    """Minimal stand-in for an exifread GPS IfdTag with .values."""

    def __init__(self, values: list[_FakeRatio]) -> None:
        self.values = values
