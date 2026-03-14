"""Tests for file_organizer.organizer — scan + copy logic."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from file_organizer.organizer import (
    SUPPORTED_EXTENSIONS,
    _apply_rename,
    _find_superseding_file,
    _resolve_target,
    _verify_file,
    organise,
)

# Fixed date / metadata returned by mocked get_metadata
_FIXED_DATE = datetime(2024, 3, 15, 10, 0, 0)
_FIXED_META = {"date": _FIXED_DATE, "camera": None, "gps": None}
_FIXED_META_CAM = {"date": _FIXED_DATE, "camera": "iPhone 15", "gps": None}
_FIXED_META_GPS = {"date": _FIXED_DATE, "camera": None, "gps": (48.8584, 2.2945)}
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
        assert summary["transferred"] == 1
        assert summary["skipped"] == []
        assert summary["superseded"] == []
        assert summary["errors"] == []

    def test_skips_unsupported_extension(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "document.pdf")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["transferred"] == 0
        assert not (dest / _YEAR_DIR).exists()

    def test_skips_directories(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        (src / "subdir").mkdir()

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["transferred"] == 0

    def test_recurses_into_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "vacation"
        sub.mkdir(parents=True)
        dest = tmp_path / "dest"
        _make_file(sub, "IMG_001.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "IMG_001.jpg").exists()
        assert summary["transferred"] == 1

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

        assert (dest / "2024" / "2024-03_Ski-Trip" / "photo.jpg").exists()

    def test_groups_by_day_when_requested(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_day=True)

        assert (dest / "2024" / "2024-03-15" / "photo.jpg").exists()

    def test_combines_day_and_event(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, event="Birthday", group_by_day=True)

        assert (dest / "2024" / "2024-03-15_Birthday" / "photo.jpg").exists()

    def test_groups_by_camera_when_requested(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META_CAM):
            organise(src, dest, group_by_camera=True)

        assert (dest / "2024" / "2024-03" / "iPhone 15" / "photo.jpg").exists()

    def test_skips_dot_underscore_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "._photo.jpg")
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["transferred"] == 1
        assert not (dest / _YEAR_DIR / _MONTH_DIR / "._photo.jpg").exists()

    def test_handles_unknown_camera_when_grouped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_camera=True)

        assert (dest / "2024" / "2024-03" / "Unknown Camera" / "photo.jpg").exists()


# ---------------------------------------------------------------------------
# organise — VID fallback for video camera
# ---------------------------------------------------------------------------


class TestOrganiseVideoCamera:
    def test_video_without_camera_uses_vid_directory(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip.mp4")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_camera=True)

        assert (dest / "2024" / "2024-03" / "VID" / "clip.mp4").exists()

    def test_video_with_camera_uses_camera_name(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "clip.mov")

        meta = {"date": _FIXED_DATE, "camera": "iPhone 15 Pro", "gps": None}
        with patch(_PATCH_META, return_value=meta):
            organise(src, dest, group_by_camera=True)

        assert (dest / "2024" / "2024-03" / "iPhone 15 Pro" / "clip.mov").exists()

    @pytest.mark.parametrize("ext", [".mp4", ".mov", ".avi", ".mkv", ".m4v"])
    def test_all_video_extensions_use_vid_fallback(self, tmp_path, ext):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, f"clip{ext}")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_camera=True)

        assert (dest / "2024" / "2024-03" / "VID" / f"clip{ext}").exists()

    def test_photo_without_camera_still_uses_unknown_camera(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_camera=True)

        assert (dest / "2024" / "2024-03" / "Unknown Camera" / "photo.jpg").exists()


# ---------------------------------------------------------------------------
# organise — GPS / location grouping
# ---------------------------------------------------------------------------


class TestOrganiseLocation:
    def test_groups_by_location_with_coords(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META_GPS):
            organise(src, dest, group_by_location=True)

        # Should create a location folder (coords-based fallback).
        dest_month = dest / _YEAR_DIR / _MONTH_DIR
        assert dest_month.exists()
        # Check that a location subfolder was created.
        subfolders = [p.name for p in dest_month.iterdir() if p.is_dir()]
        assert len(subfolders) == 1
        assert "photo.jpg" in [p.name for p in (dest_month / subfolders[0]).iterdir()]

    def test_unknown_location_when_no_gps(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, group_by_location=True)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "Unknown Location" / "photo.jpg").exists()

    def test_location_and_camera_combined(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        meta = {"date": _FIXED_DATE, "camera": "iPhone 15", "gps": (48.8584, 2.2945)}
        with patch(_PATCH_META, return_value=meta):
            organise(src, dest, group_by_location=True, group_by_camera=True)

        dest_month = dest / _YEAR_DIR / _MONTH_DIR
        # Structure: YYYY-MM / location / camera / photo.jpg
        location_dirs = [p for p in dest_month.iterdir() if p.is_dir()]
        assert len(location_dirs) == 1
        camera_dirs = [p for p in location_dirs[0].iterdir() if p.is_dir()]
        assert len(camera_dirs) == 1
        assert camera_dirs[0].name == "iPhone 15"


# ---------------------------------------------------------------------------
# organise — sidecar files
# ---------------------------------------------------------------------------


class TestOrganiseSidecars:
    def test_xmp_sidecar_copied_alongside_photo(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")
        _make_file(src, "photo.xmp", b"<xmp/>")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "photo.xmp").exists()
        assert summary["sidecars"] == 1

    def test_aae_sidecar_copied_alongside_photo(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "IMG_001.heic")
        _make_file(src, "IMG_001.aae", b"<aae/>")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert (dest / _YEAR_DIR / _MONTH_DIR / "IMG_001.aae").exists()
        assert summary["sidecars"] == 1

    def test_sidecar_moved_in_move_mode(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")
        sidecar = _make_file(src, "photo.xmp", b"<xmp/>")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, move=True)

        assert not sidecar.exists()
        assert (dest / _YEAR_DIR / _MONTH_DIR / "photo.xmp").exists()

    def test_no_sidecar_when_absent(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["sidecars"] == 0

    def test_sidecar_not_transferred_for_skipped_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg", b"pixels")
        _make_file(src, "photo.xmp", b"<xmp/>")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        shutil.copy2(source_file, dest_dir / "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["sidecars"] == 0


# ---------------------------------------------------------------------------
# organise — exclude patterns
# ---------------------------------------------------------------------------


class TestOrganiseExclude:
    def test_excludes_files_by_name(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")
        _make_file(src, "bad.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, exclude=["bad.jpg"])

        assert summary["transferred"] == 1
        assert not (dest / _YEAR_DIR / _MONTH_DIR / "bad.jpg").exists()

    def test_exclude_multiple_patterns(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "keep.jpg")
        _make_file(src, "skip1.jpg")
        _make_file(src, "skip2.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, exclude=["skip1.jpg", "skip2.jpg"])

        assert summary["transferred"] == 1


# ---------------------------------------------------------------------------
# organise — progress callback
# ---------------------------------------------------------------------------


class TestOrganiseProgress:
    def test_progress_callback_invoked(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "a.jpg")
        _make_file(src, "b.jpg")

        calls: list[tuple[int, int, Path]] = []

        def recorder(current: int, total: int, filepath: Path) -> None:
            calls.append((current, total, filepath))

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, progress=recorder)

        assert len(calls) == 2
        assert calls[0][:2] == (1, 2)
        assert calls[1][:2] == (2, 2)


# ---------------------------------------------------------------------------
# organise — post-copy verification
# ---------------------------------------------------------------------------


class TestOrganiseVerify:
    def test_verify_succeeds_for_valid_copy(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg", b"important pixels")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, verify=True)

        assert summary["transferred"] == 1
        assert summary["verified"] == 1
        assert summary["verify_failed"] == []

    def test_verify_not_performed_in_move_mode(self, tmp_path):
        """Verification doesn't apply to moves (source is gone)."""
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, move=True, verify=True)

        assert summary["transferred"] == 1
        assert summary["verified"] == 0


class TestVerifyFile:
    def test_identical_files_pass(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"hello world")
        b.write_bytes(b"hello world")
        assert _verify_file(a, b) is True

    def test_different_files_fail(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"hello")
        b.write_bytes(b"world")
        assert _verify_file(a, b) is False


# ---------------------------------------------------------------------------
# organise — rename patterns
# ---------------------------------------------------------------------------


class TestOrganiseRename:
    def test_rename_with_date_pattern(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "IMG_001.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, rename_pattern="{date}_{seq}")

        assert (dest / _YEAR_DIR / _MONTH_DIR / "2024-03-15_001.jpg").exists()
        assert summary["transferred"] == 1

    def test_rename_with_camera_pattern(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        meta = {"date": _FIXED_DATE, "camera": "iPhone 15 Pro", "gps": None}
        with patch(_PATCH_META, return_value=meta):
            organise(src, dest, rename_pattern="{date}_{camera}_{seq}")

        assert (dest / _YEAR_DIR / _MONTH_DIR / "2024-03-15_iPhone_15_Pro_001.jpg").exists()

    def test_rename_preserves_original_stem(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "vacation.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, rename_pattern="{original}_{date}")

        assert (dest / _YEAR_DIR / _MONTH_DIR / "vacation_2024-03-15.jpg").exists()

    def test_rename_seq_increments(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "a.jpg", b"a")
        _make_file(src, "b.jpg", b"b")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, rename_pattern="{date}_{seq}")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        assert (dest_dir / "2024-03-15_001.jpg").exists()
        assert (dest_dir / "2024-03-15_002.jpg").exists()


class TestApplyRename:
    def test_all_placeholders(self):
        meta = {"date": _FIXED_DATE, "camera": "Sony A7", "gps": None}
        filepath = Path("/src/IMG_001.jpg")
        result = _apply_rename(
            "{datetime}_{camera}_{seq}_{original}", meta, filepath, 42,
        )
        assert result == "2024-03-15_10-00-00_Sony_A7_042_IMG_001.jpg"

    def test_unknown_camera(self):
        meta = {"date": _FIXED_DATE, "camera": None, "gps": None}
        filepath = Path("/src/photo.cr2")
        result = _apply_rename("{camera}_{seq}", meta, filepath, 1)
        assert result == "Unknown_001.cr2"


# ---------------------------------------------------------------------------
# organise — disk space check
# ---------------------------------------------------------------------------


class TestDiskSpaceCheck:
    def test_raises_on_insufficient_space(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with (
            patch(_PATCH_META, return_value=_FIXED_META),
            patch("file_organizer.organizer.shutil.disk_usage") as mock_usage,
        ):
            mock_usage.return_value = type("Usage", (), {"free": 0})()
            with pytest.raises(OSError, match="Not enough disk space"):
                organise(src, dest)

    def test_no_error_when_sufficient_space(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["transferred"] == 1


# ---------------------------------------------------------------------------
# organise — empty folder cleanup
# ---------------------------------------------------------------------------


class TestOrganiseCleanup:
    def test_cleanup_removes_empty_dirs_after_move(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "album"
        sub.mkdir(parents=True)
        dest = tmp_path / "dest"
        _make_file(sub, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, move=True, cleanup=True)

        assert not sub.exists()
        assert src.exists()  # root source dir kept

    def test_cleanup_preserves_non_empty_dirs(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "album"
        sub.mkdir(parents=True)
        dest = tmp_path / "dest"
        _make_file(sub, "photo.jpg")
        _make_file(sub, "notes.txt")  # unsupported, left behind

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, move=True, cleanup=True)

        assert sub.exists()  # still has notes.txt

    def test_no_cleanup_without_flag(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "album"
        sub.mkdir(parents=True)
        dest = tmp_path / "dest"
        _make_file(sub, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, move=True, cleanup=False)

        assert sub.exists()  # empty but not cleaned up


# ---------------------------------------------------------------------------
# organise — manifest
# ---------------------------------------------------------------------------


class TestOrganiseManifest:
    def test_manifest_written_with_operations(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        manifest_file = tmp_path / "manifest.json"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, manifest_path=manifest_file)

        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text())
        assert data["mode"] == "copy"
        assert len(data["operations"]) == 1
        assert data["operations"][0]["action"] == "copy"

    def test_manifest_records_skipped_and_superseded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        manifest_file = tmp_path / "manifest.json"

        dup_file = _make_file(src, "dup.jpg", b"dup")
        _make_file(src, "orig.jpg")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        shutil.copy2(dup_file, dest_dir / "dup.jpg")
        (dest_dir / "orig.heic").write_bytes(b"heic")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, manifest_path=manifest_file)

        data = json.loads(manifest_file.read_text())
        actions = {op["action"] for op in data["operations"]}
        assert "skipped" in actions
        assert "superseded" in actions

    def test_manifest_not_written_in_dry_run(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        manifest_file = tmp_path / "manifest.json"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, manifest_path=manifest_file, dry_run=True)

        assert not manifest_file.exists()


# ---------------------------------------------------------------------------
# organise — transfer statistics
# ---------------------------------------------------------------------------


class TestOrganiseStatistics:
    def test_tracks_bytes_transferred(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        content = b"x" * 1024
        _make_file(src, "photo.jpg", content)

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["bytes_transferred"] == 1024

    def test_tracks_elapsed_time(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["elapsed"] >= 0


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
            organise(src, dest)
            target = dest / _YEAR_DIR / _MONTH_DIR / "photo.jpg"
            shutil.copy2(source_file, target)
            summary = organise(src, dest)

        assert len(summary["skipped"]) == 1
        assert summary["transferred"] == 0

    def test_renames_conflicting_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "photo.jpg").write_bytes(b"different content")
        _make_file(src, "photo.jpg", b"original content")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert (dest_dir / "photo_1.jpg").exists()
        assert summary["transferred"] == 1

    def test_increments_suffix_past_existing(self, tmp_path):
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
        assert summary["transferred"] == 1

    def test_dry_run_reports_skip_for_identical_dest(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg", b"px")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        shutil.copy2(source_file, dest_dir / "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, dry_run=True)

        assert len(summary["skipped"]) == 1
        assert summary["transferred"] == 0


# ---------------------------------------------------------------------------
# _find_superseding_file
# ---------------------------------------------------------------------------


class TestFindSupersedingFile:
    def test_photo_superseded_by_heic(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"data")
        (tmp_path / "photo.heic").write_bytes(b"heic")

        assert _find_superseding_file(src, tmp_path) == tmp_path / "photo.heic"

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

        assert _find_superseding_file(src, tmp_path) == tmp_path / "shot.dng"

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

        assert _find_superseding_file(src, tmp_path) == tmp_path / "clip_HEVC.mp4"

    @pytest.mark.parametrize("ext", [".mp4", ".mov", ".avi", ".mkv", ".m4v"])
    def test_all_video_originals_superseded_by_hevc(self, tmp_path, ext):
        src = tmp_path / "src" / f"clip{ext}"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(b"data")
        (tmp_path / "clip_HEVC.mp4").write_bytes(b"hevc")

        assert _find_superseding_file(src, tmp_path) == tmp_path / "clip_HEVC.mp4"

    def test_hevc_file_not_superseded(self, tmp_path):
        src = tmp_path / "src" / "clip_HEVC.mp4"
        src.parent.mkdir()
        src.write_bytes(b"data")
        (tmp_path / "clip_HEVC_HEVC.mp4").write_bytes(b"extra")

        assert _find_superseding_file(src, tmp_path) is None

    def test_heic_not_superseded(self, tmp_path):
        src = tmp_path / "src" / "photo.heic"
        src.parent.mkdir()
        src.write_bytes(b"data")

        assert _find_superseding_file(src, tmp_path) is None

    def test_dng_not_superseded(self, tmp_path):
        src = tmp_path / "src" / "shot.dng"
        src.parent.mkdir()
        src.write_bytes(b"data")

        assert _find_superseding_file(src, tmp_path) is None

    def test_no_superseding_file_returns_none(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"data")

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

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert not (dest_dir / "photo.jpg").exists()
        assert summary["transferred"] == 0
        assert len(summary["superseded"]) == 1

    def test_mixed_run_copied_skipped_superseded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"

        _make_file(src, "new.jpg", b"new")
        _make_file(src, "orig.jpg", b"orig")
        dup_file = _make_file(src, "dup.jpg", b"dup")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "orig.heic").write_bytes(b"heic")
        shutil.copy2(dup_file, dest_dir / "dup.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest)

        assert summary["transferred"] == 1
        assert len(summary["skipped"]) == 1
        assert len(summary["superseded"]) == 1
        assert summary["errors"] == []


# ---------------------------------------------------------------------------
# _resolve_target
# ---------------------------------------------------------------------------


class TestResolveTarget:
    def test_returns_simple_path_when_no_conflict(self, tmp_path):
        assert _resolve_target(Path("photo.jpg"), tmp_path) == tmp_path / "photo.jpg"

    def test_returns_none_for_identical_file(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"data")
        shutil.copy2(src, tmp_path / "photo.jpg")

        assert _resolve_target(src, tmp_path) is None

    def test_returns_suffixed_name_for_different_file(self, tmp_path):
        src = tmp_path / "src" / "photo.jpg"
        src.parent.mkdir()
        src.write_bytes(b"new")
        (tmp_path / "photo.jpg").write_bytes(b"old")

        assert _resolve_target(src, tmp_path) == tmp_path / "photo_1.jpg"


# ---------------------------------------------------------------------------
# SUPPORTED_EXTENSIONS sanity check
# ---------------------------------------------------------------------------


class TestSupportedExtensions:
    @pytest.mark.parametrize(
        "ext",
        [".jpg", ".jpeg", ".tiff", ".tif", ".heic",
         ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf",
         ".mp4", ".mov", ".avi", ".mkv", ".m4v"],
    )
    def test_expected_extensions_present(self, ext):
        assert ext in SUPPORTED_EXTENSIONS

    @pytest.mark.parametrize("ext", [".pdf", ".txt", ".png", ".webp"])
    def test_not_supported(self, ext):
        assert ext not in SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# organise — move mode
# ---------------------------------------------------------------------------


class TestOrganiseMoveMode:
    def test_move_removes_file_from_source(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, move=True)

        assert not source_file.exists()
        assert (dest / _YEAR_DIR / _MONTH_DIR / "photo.jpg").exists()
        assert summary["transferred"] == 1

    def test_move_leaves_skipped_file_in_source(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg", b"pixels")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        shutil.copy2(source_file, dest_dir / "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, move=True)

        assert source_file.exists()
        assert len(summary["skipped"]) == 1

    def test_move_leaves_superseded_file_in_source(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg")

        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        (dest_dir / "photo.heic").write_bytes(b"heic")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, move=True)

        assert source_file.exists()
        assert len(summary["superseded"]) == 1

    def test_move_dry_run_does_not_move_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            summary = organise(src, dest, move=True, dry_run=True)

        assert source_file.exists()
        assert not dest.exists()
        assert summary["transferred"] == 1

    def test_copy_mode_leaves_source_intact(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        source_file = _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, move=False)

        assert source_file.exists()


# ---------------------------------------------------------------------------
# organise — log file
# ---------------------------------------------------------------------------


class TestWriteLog:
    def test_log_written_with_skipped_and_superseded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        log_file = tmp_path / "run.log"

        dup_file = _make_file(src, "dup.jpg", b"dup")
        dest_dir = dest / _YEAR_DIR / _MONTH_DIR
        dest_dir.mkdir(parents=True)
        shutil.copy2(dup_file, dest_dir / "dup.jpg")

        _make_file(src, "orig.jpg")
        (dest_dir / "orig.heic").write_bytes(b"heic")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, log_path=log_file)

        content = log_file.read_text()
        assert "Skipped" in content
        assert "dup.jpg" in content
        assert "Superseded" in content
        assert "orig.jpg" in content

    def test_log_not_written_in_dry_run(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        log_file = tmp_path / "run.log"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, log_path=log_file, dry_run=True)

        assert not log_file.exists()

    def test_log_contains_mode_and_paths(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        log_file = tmp_path / "run.log"
        _make_file(src, "photo.jpg")

        with patch(_PATCH_META, return_value=_FIXED_META):
            organise(src, dest, move=True, log_path=log_file)

        content = log_file.read_text()
        assert "move" in content
        assert str(src) in content
        assert str(dest) in content
