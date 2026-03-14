"""Date and camera extraction from media files.

Priority order:
  1. EXIF DateTimeOriginal (when the shutter fired)
  2. EXIF DateTime        (last modification recorded by camera)
  3. ffprobe              (creation_time / com.apple.quicktime.model for videos)
  4. File mtime           (filesystem fallback — used for untagged files)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import exifread

# EXIF date format written by cameras: "YYYY:MM:DD HH:MM:SS"
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"
_EXIF_DATE_TAGS = ("EXIF DateTimeOriginal", "Image DateTime")
_EXIF_MAKE_TAG = "Image Make"
_EXIF_MODEL_TAG = "Image Model"


_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v"})


class Metadata(TypedDict):
    date: datetime
    camera: str | None


def get_metadata(filepath: Path) -> Metadata:
    """Return the best available date and camera info for *filepath*."""
    exif_data = _from_exif(filepath)
    if exif_data["date"] is not None:
        return {"date": exif_data["date"], "camera": exif_data["camera"]}

    # For video files, try ffprobe before falling back to mtime.
    if filepath.suffix.lower() in _VIDEO_EXTENSIONS:
        probe = _from_ffprobe(filepath)
        date = probe["date"] or _from_mtime(filepath)
        return {"date": date, "camera": probe["camera"]}

    return {"date": _from_mtime(filepath), "camera": None}


def get_date(filepath: Path) -> datetime:
    """Legacy helper: return the best available date for *filepath*."""
    return get_metadata(filepath)["date"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _from_exif(filepath: Path) -> dict[str, datetime | str | None]:
    result: dict[str, datetime | str | None] = {"date": None, "camera": None}
    try:
        with filepath.open("rb") as fh:
            tags = exifread.process_file(fh, details=False)

        # Date extraction
        for tag in _EXIF_DATE_TAGS:
            if tag in tags:
                date = _parse_exif_date(str(tags[tag]))
                if date:
                    result["date"] = date
                    break

        # Camera extraction (Make + Model)
        make = str(tags.get(_EXIF_MAKE_TAG, "")).strip()
        model = str(tags.get(_EXIF_MODEL_TAG, "")).strip()

        if make or model:
            # Avoid repeating make if model already contains it
            # Special case: Apple + iPhone
            if make.lower() == "apple" and model.lower().startswith("iphone"):
                result["camera"] = model
            elif make and model and make.lower() in model.lower():
                result["camera"] = model
            elif make and model:
                result["camera"] = f"{make} {model}"
            else:
                result["camera"] = model or make

    except Exception:
        pass
    return result


def _from_ffprobe(filepath: Path) -> dict[str, datetime | str | None]:
    """Extract creation date and camera model from a video file using ffprobe.

    Returns ``{"date": ..., "camera": ...}`` with None values when ffprobe is
    unavailable or the metadata is absent.
    """
    result: dict[str, datetime | str | None] = {"date": None, "camera": None}

    if not shutil.which("ffprobe"):
        return result

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return result

        data = json.loads(proc.stdout)
        tags = data.get("format", {}).get("tags", {})

        # Creation date — ffprobe uses ISO 8601 (e.g. "2024-03-15T10:00:00.000000Z")
        for key in ("creation_time", "com.apple.quicktime.creationdate"):
            raw = tags.get(key)
            if raw:
                date = _parse_ffprobe_date(raw)
                if date:
                    result["date"] = date
                    break

        # Camera model — Apple QuickTime stores make/model in tags
        make = tags.get("com.apple.quicktime.make", "").strip()
        model = tags.get("com.apple.quicktime.model", "").strip()

        if make or model:
            if make.lower() == "apple" and model.lower().startswith("iphone"):
                result["camera"] = model
            elif make and model and make.lower() in model.lower():
                result["camera"] = model
            elif make and model:
                result["camera"] = f"{make} {model}"
            else:
                result["camera"] = model or make

    except Exception:
        pass
    return result


def _parse_ffprobe_date(value: str) -> datetime | None:
    """Parse an ISO 8601 date string from ffprobe (e.g. '2024-03-15T10:00:00.000000Z')."""
    # Strip trailing timezone indicator and fractional seconds for simplicity
    cleaned = value.strip().rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _parse_exif_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), _EXIF_DATE_FMT)
    except ValueError:
        return None


def _from_mtime(filepath: Path) -> datetime:
    return datetime.fromtimestamp(filepath.stat().st_mtime)
