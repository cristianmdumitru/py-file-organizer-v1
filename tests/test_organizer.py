"""Tests for file_organizer.organizer — scan + copy logic."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from file_organizer.organizer import SUPPORTED_EXTENSIONS, _resolve_target, organise


# Fixed date returned by mocked get_date
_FIXED_DATE = datetime(2024, 3, 15, 10, 0, 0)
_YEAR_DIR = "2024"
_MONTH_DIR = "2024-03"


def _make_file(directory: Path, name: str, content: bytes = b"data") -> Path:
    path = directory / name
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# organise — happy path
# ---------------------------------------------------------------------------

class TestOrganise:
    def test_copies_supported_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest)

        expected = dest / _YEAR_DIR / _MONTH_DIR / "photo.jpg"
        assert expected.exists()
        assert summary["copied"] == 1
        assert summary["skipped"] == 0
        assert summary["errors"] == []

    def test_skips_unsupported_extension(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "document.pdf")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest)

        assert summary["copied"] == 0
        assert summary["skipped"] == 0
        assert not (dest / _YEAR_DIR).exists()

    def test_skips_directories(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        (src / "subdir").mkdir()

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest)

        assert summary["copied"] == 0

    def test_recurses_into_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "vacation"
        sub.mkdir(parents=True)
        dest = tmp_path / "dest"
        _make_file(sub, "IMG_001.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "IMG_001.jpg").exists()
        assert summary["copied"] == 1

    def test_creates_dest_year_month_dirs(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip.mp4")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR).is_dir()

    def test_raises_when_source_not_directory(self, tmp_path):
        fake_source = tmp_path / "not_a_dir"
        with pytest.raises(NotADirectoryError):
            organise(fake_source, tmp_path / "dest")

    def test_uses_event_name_in_subfolder(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            organise(src, dest, event="Ski-Trip")

        expected = dest / "2024" / "2024-03_Ski-Trip" / "photo.jpg"
        assert expected.exists()

    def test_groups_by_day_when_requested(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            organise(src, dest, group_by_day=True)

        expected = dest / "2024" / "2024-03-15" / "photo.jpg"
        assert expected.exists()

    def test_combines_day_and_event(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            organise(src, dest, event="Birthday", group_by_day=True)

        expected = dest / "2024" / "2024-03-15_Birthday" / "photo.jpg"
        assert expected.exists()

    def test_groups_by_camera_when_requested(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": "iPhone 15"}):
            organise(src, dest, group_by_camera=True)

        expected = dest / "2024" / "2024-03" / "iPhone 15" / "photo.jpg"
        assert expected.exists()

    def test_handles_unknown_camera_when_grouped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            organise(src, dest, group_by_camera=True)

        expected = dest / "2024" / "2024-03" / "Unknown Camera" / "photo.jpg"
        assert expected.exists()


# ---------------------------------------------------------------------------
# organise — duplicate handling
# ---------------------------------------------------------------------------

class TestOrganiseDuplicates:
    def test_skips_identical_file_already_at_dest(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg", b"pixels")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            # First copy
            organise(src, dest)
            # Sync mtime so identity check passes
            target = dest / _YEAR_DIR / _MONTH_DIR / "photo.jpg"
            shutil.copy2(source_file, target)  # copy2 preserves mtime

            # Second copy
            summary = organise(src, dest)

        assert summary["skipped"] == 1
        assert summary["copied"] == 0

    def test_renames_conflicting_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"

        # Pre-place a *different* file at the destination with the same name
        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "photo.jpg").write_bytes(b"different content")

        _make_file(src, "photo.jpg", b"original content")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest)

        assert (dest_dir / "photo_1.jpg").exists()
        assert summary["copied"] == 1

    def test_increments_suffix_past_existing_renamed_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "photo.jpg").write_bytes(b"v0")
        (dest_dir / "photo_1.jpg").write_bytes(b"v1")

        _make_file(src, "photo.jpg", b"v2")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            organise(src, dest)

        assert (dest_dir / "photo_2.jpg").exists()


# ---------------------------------------------------------------------------
# organise — dry run
# ---------------------------------------------------------------------------

class TestOrganiseDryRun:
    def test_dry_run_does_not_create_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest, dry_run=True)

        assert not dest.exists()
        assert summary["copied"] == 1  # counted but not written

    def test_dry_run_reports_skip_for_identical_dest(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg", b"px")

        # Place identical file at destination first (real copy to preserve mtime)
        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        shutil.copy2(source_file, dest_dir / "photo.jpg")

        with patch("file_organizer.organizer.get_metadata", return_value={"date": _FIXED_DATE, "camera": None}):
            summary = organise(src, dest, dry_run=True)

        assert summary["skipped"] == 1
        assert summary["copied"] == 0


# ---------------------------------------------------------------------------
# _resolve_target
# ---------------------------------------------------------------------------

class TestResolveTarget:
    def test_returns_simple_path_when_no_conflict(self, tmp_path):
        result = _resolve_target(Path("photo.jpg"), tmp_path)
        assert result == tmp_path / "photo.jpg"

    def test_returns_none_for_identical_file(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"data")

        dest_file = tmp_path / "photo.jpg"
        shutil.copy2(src, dest_file)  # identical size + mtime

        assert _resolve_target(src, tmp_path) is None

    def test_returns_suffixed_name_for_different_file(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"new")

        (tmp_path / "photo.jpg").write_bytes(b"old")

        result = _resolve_target(src, tmp_path)
        assert result == tmp_path / "photo_1.jpg"


# ---------------------------------------------------------------------------
# SUPPORTED_EXTENSIONS sanity check
# ---------------------------------------------------------------------------

class TestSupportedExtensions:
    @pytest.mark.parametrize("ext", [
        ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic",
        ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf",
        ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    ])
    def test_expected_extensions_present(self, ext):
        assert ext in SUPPORTED_EXTENSIONS

    def test_pdf_not_supported(self):
        assert ".pdf" not in SUPPORTED_EXTENSIONS

    def test_txt_not_supported(self):
        assert ".txt" not in SUPPORTED_EXTENSIONS
