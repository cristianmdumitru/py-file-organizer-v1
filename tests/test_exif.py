"""Tests for file_organizer.exif — date extraction logic."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from file_organizer.exif import _from_mtime, _parse_exif_date, get_date, get_metadata


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
        fake_file.write_bytes(b"\xff\xd8\xff")  # minimal JPEG header

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
# Helpers
# ---------------------------------------------------------------------------

class _FakeTag:
    """Minimal stand-in for an exifread IfdTag."""
    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:
        return self._value
