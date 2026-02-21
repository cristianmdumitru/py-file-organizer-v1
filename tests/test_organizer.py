"""Tests for file_organizer.organizer — scan + copy logic."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from file_organizer.organizer import (
    SUPPORTED_EXTENSIONS,
    _find_superseding_file,
    _resolve_target,
    organise,
)

# Fixed date / metadata returned by mocked get_metadata
_FIXED_DATE = datetime(2024, 3, 15, 10, 0, 0)
_FIXED_META = {"date": _FIXED_DATE, "camera": None}
_YEAR_DIR = "2024"
_MONTH_DIR = "2024-03"
_PATCH_META = "file_organizer.organizer.get_metadata"


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

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        expected = dest / _YEAR_DIR / _MONTH_DIR / "photo.jpg"
        assert expected.exists()
        assert summary["copied"] == 1
        assert summary["skipped"] == 0
        assert summary["superseded"] == []
        assert summary["errors"] == []

    def test_skips_unsupported_extension(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "document.pdf")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["copied"] == 0
        assert summary["skipped"] == 0
        assert not (dest / _YEAR_DIR).exists()

    def test_skips_directories(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        (src / "subdir").mkdir()

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["copied"] == 0

    def test_recurses_into_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "vacation"
        sub.mkdir(parents=True)
        dest = tmp_path / "dest"
        _make_file(sub, "IMG_001.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "IMG_001.jpg").exists()
        assert summary["copied"] == 1

    def test_creates_dest_year_month_dirs(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip.mp4")

        with patch(_PATCH_META, return_value=_FIXED_META):
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

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, event="Ski-Trip")

        expected = dest / "2024" / "2024-03_Ski-Trip" / "photo.jpg"
        assert expected.exists()

    def test_groups_by_day_when_requested(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_day=True)

        expected = dest / "2024" / "2024-03-15" / "photo.jpg"
        assert expected.exists()

    def test_combines_day_and_event(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, event="Birthday", group_by_day=True)

        expected = dest / "2024" / "2024-03-15_Birthday" / "photo.jpg"
        assert expected.exists()

    def test_groups_by_camera_when_requested(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value={"date": _FIXED_DATE, "camera": "iPhone 15"}):
            organise(src, dest, group_by_camera=True)

        expected = dest / "2024" / "2024-03" / "iPhone 15" / "photo.jpg"
        assert expected.exists()

    def test_handles_unknown_camera_when_grouped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
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

        with patch(_PATCH_META, return_value=_FIXED_META):
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

        with patch(_PATCH_META, return_value=_FIXED_META):
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

        with patch(_PATCH_META, return_value=_FIXED_META):
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

        with patch(_PATCH_META, return_value=_FIXED_META):
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

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, dry_run=True)

        assert summary["skipped"] == 1
        assert summary["copied"] == 0


# ---------------------------------------------------------------------------
# _find_superseding_file
# ---------------------------------------------------------------------------


class TestFindSupersedingFile:
    def test_photo_superseded_by_heic(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"data")
        (tmp_path / "photo.heic").write_bytes(b"heic")

        result = _find_superseding_file(src, tmp_path)
        assert result == tmp_path / "photo.heic"

    @pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".tiff", ".tif"])
    def test_all_photo_originals_superseded_by_heic(self, tmp_path, ext):
        src = tmp_path / "src" / f"photo{ext}"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(b"data")
        (tmp_path / "photo.heic").write_bytes(b"heic")

        assert _find_superseding_file(src, tmp_path) == tmp_path / "photo.heic"

    def test_raw_superseded_by_dng(self, tmp_path):
        src = tmp_path / "src" / "shot.cr2"
        src.parent.mkdir()
        src.write_bytes(b"data")
        (tmp_path / "shot.dng").write_bytes(b"dng")

        result = _find_superseding_file(src, tmp_path)
        assert result == tmp_path / "shot.dng"

    @pytest.mark.parametrize("ext", [".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf"])
    def test_all_raw_originals_superseded_by_dng(self, tmp_path, ext):
        src = tmp_path / "src" / f"shot{ext}"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(b"data")
        (tmp_path / "shot.dng").write_bytes(b"dng")

        assert _find_superseding_file(src, tmp_path) == tmp_path / "shot.dng"

    def test_video_superseded_by_hevc_mp4(self, tmp_path):
        src = tmp_path / "src" / "clip.mp4"
        src.parent.mkdir()
        src.write_bytes(b"data")
        (tmp_path / "clip_HEVC.mp4").write_bytes(b"hevc")

        result = _find_superseding_file(src, tmp_path)
        assert result == tmp_path / "clip_HEVC.mp4"

    @pytest.mark.parametrize("ext", [".mp4", ".mov", ".avi", ".mkv", ".m4v"])
    def test_all_video_originals_superseded_by_hevc(self, tmp_path, ext):
        src = tmp_path / "src" / f"clip{ext}"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(b"data")
        (tmp_path / "clip_HEVC.mp4").write_bytes(b"hevc")

        assert _find_superseding_file(src, tmp_path) == tmp_path / "clip_HEVC.mp4"

    def test_hevc_file_not_superseded(self, tmp_path):
        """A file already named {stem}_HEVC.mp4 is the transcoded version — copy it normally."""
        src = tmp_path / "src" / "clip_HEVC.mp4"
        src.parent.mkdir()
        src.write_bytes(b"data")
        # Even if a _HEVC file of the same name exists, it won't self-match
        (tmp_path / "clip_HEVC_HEVC.mp4").write_bytes(b"extra")  # unrelated

        result = _find_superseding_file(src, tmp_path)
        assert result is None

    def test_heic_not_superseded(self, tmp_path):
        """.heic is the converted target format — it is never itself superseded."""
        src = tmp_path / "src" / "photo.heic"
        src.parent.mkdir()
        src.write_bytes(b"data")

        result = _find_superseding_file(src, tmp_path)
        assert result is None

    def test_dng_not_superseded(self, tmp_path):
        """.dng is the converted target format — it is never itself superseded."""
        src = tmp_path / "src" / "shot.dng"
        src.parent.mkdir()
        src.write_bytes(b"data")

        result = _find_superseding_file(src, tmp_path)
        assert result is None

    def test_no_superseding_file_at_dest_returns_none(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"data")
        # No .heic placed at tmp_path

        assert _find_superseding_file(src, tmp_path) is None

    def test_superseding_file_absent_from_dest_returns_none(self, tmp_path):
        """Superseding file listed in source but not yet at destination — copy normally."""
        src = tmp_path / "src" / "clip.mov"
        src.parent.mkdir()
        src.write_bytes(b"data")
        # clip_HEVC.mp4 is NOT at tmp_path

        assert _find_superseding_file(src, tmp_path) is None


# ---------------------------------------------------------------------------
# organise — superseded handling (integration)
# ---------------------------------------------------------------------------


class TestOrganiseSuperseded:
    def test_photo_superseded_by_heic_is_not_copied(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "photo.heic").write_bytes(b"heic")

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest)

        assert not (dest_dir / "photo.jpg").exists()
        assert summary["copied"] == 0
        assert summary["skipped"] == 0
        assert len(summary["superseded"]) == 1

    def test_raw_superseded_by_dng_is_not_copied(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "shot.cr2")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "shot.dng").write_bytes(b"dng")

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest)

        assert not (dest_dir / "shot.cr2").exists()
        assert summary["copied"] == 0
        assert len(summary["superseded"]) == 1

    def test_video_superseded_by_hevc_is_not_copied(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip.mp4")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "clip_HEVC.mp4").write_bytes(b"hevc")

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest)

        assert not (dest_dir / "clip.mp4").exists()
        assert summary["copied"] == 0
        assert len(summary["superseded"]) == 1

    def test_hevc_file_itself_is_copied_normally(self, tmp_path):
        """The _HEVC.mp4 file is the transcoded version and must always be copied."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip_HEVC.mp4")

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "clip_HEVC.mp4").exists()
        assert summary["copied"] == 1
        assert summary["superseded"] == []

    def test_superseded_entry_contains_source_and_superseding_paths(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        heic_file = dest_dir / "photo.heic"
        heic_file.write_bytes(b"heic")

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest)

        assert len(summary["superseded"]) == 1
        entry = summary["superseded"][0]
        assert str(source_file) in entry
        assert str(heic_file) in entry

    def test_mixed_run_copied_skipped_superseded(self, tmp_path):
        """All three outcomes appear correctly in a single run."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"

        _make_file(src, "new.jpg", b"new")  # will be copied
        _make_file(src, "orig.jpg", b"orig")  # will be superseded (HEIC exists)
        dup_file = _make_file(src, "dup.png", b"dup")  # will be skipped (identical)

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "orig.heic").write_bytes(b"heic")  # supersedes orig.jpg
        shutil.copy2(dup_file, dest_dir / "dup.png")  # identical copy already present

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest)

        assert summary["copied"] == 1
        assert summary["skipped"] == 1
        assert len(summary["superseded"]) == 1
        assert summary["errors"] == []

    def test_superseded_in_dry_run_does_not_copy(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip.mov")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "clip_HEVC.mp4").write_bytes(b"hevc")

        with patch(
            "file_organizer.organizer.get_metadata",
            return_value={"date": _FIXED_DATE, "camera": None},
        ):
            summary = organise(src, dest, dry_run=True)

        assert not (dest_dir / "clip.mov").exists()
        assert len(summary["superseded"]) == 1


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
    @pytest.mark.parametrize(
        "ext",
        [
            ".jpg",
            ".jpeg",
            ".png",
            ".tiff",
            ".tif",
            ".webp",
            ".heic",
            ".cr2",
            ".cr3",
            ".nef",
            ".arw",
            ".dng",
            ".orf",
            ".rw2",
            ".raf",
            ".mp4",
            ".mov",
            ".avi",
            ".mkv",
            ".m4v",
        ],
    )
    def test_expected_extensions_present(self, ext):
        assert ext in SUPPORTED_EXTENSIONS

    def test_pdf_not_supported(self):
        assert ".pdf" not in SUPPORTED_EXTENSIONS

    def test_txt_not_supported(self):
        assert ".txt" not in SUPPORTED_EXTENSIONS
