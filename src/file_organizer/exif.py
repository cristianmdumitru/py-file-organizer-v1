"""Date, camera, and GPS extraction from media files.

Priority order:
  1. EXIF DateTimeOriginal (when the shutter fired)
  2. EXIF DateTime        (last modification recorded by camera)
  3. Pillow               (HEIC fallback when exifread returns nothing)
  4. ffprobe              (creation_time / com.apple.quicktime.model for videos)
  5. File mtime           (filesystem fallback — used for untagged files)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import exifread

logger = logging.getLogger(__name__)

# EXIF date format written by cameras: "YYYY:MM:DD HH:MM:SS"
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"
_EXIF_DATE_TAGS = ("EXIF DateTimeOriginal", "Image DateTime")
_EXIF_MAKE_TAG = "Image Make"
_EXIF_MODEL_TAG = "Image Model"

_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v"})
_HEIC_EXTENSIONS: frozenset[str] = frozenset({".heic", ".heif"})


class Metadata(TypedDict):
    date: datetime
    camera: str | None
    gps: tuple[float, float] | None


def get_metadata(filepath: Path) -> Metadata:
    """Return the best available date, camera, and GPS info for *filepath*."""
    exif_data = _from_exif(filepath)
    if exif_data["date"] is not None:
        return {
            "date": exif_data["date"],
            "camera": exif_data["camera"],
            "gps": exif_data["gps"],
        }

    # For HEIC files with no exifread results, try Pillow as fallback.
    if filepath.suffix.lower() in _HEIC_EXTENSIONS:
        pillow_data = _from_pillow(filepath)
        if pillow_data["date"] is not None:
            return {
                "date": pillow_data["date"],
                "camera": pillow_data["camera"],
                "gps": pillow_data["gps"],
            }

    # For video files, try ffprobe before falling back to mtime.
    if filepath.suffix.lower() in _VIDEO_EXTENSIONS:
        probe = _from_ffprobe(filepath)
        date = probe["date"] or _from_mtime(filepath)
        return {"date": date, "camera": probe["camera"], "gps": probe["gps"]}

    return {"date": _from_mtime(filepath), "camera": None, "gps": None}


def get_date(filepath: Path) -> datetime:
    """Legacy helper: return the best available date for *filepath*."""
    return get_metadata(filepath)["date"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ExifResult = dict[str, datetime | str | tuple[float, float] | None]


def _from_exif(filepath: Path) -> _ExifResult:
    result: _ExifResult = {"date": None, "camera": None, "gps": None}
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
        result["camera"] = _extract_camera(
            str(tags.get(_EXIF_MAKE_TAG, "")).strip(),
            str(tags.get(_EXIF_MODEL_TAG, "")).strip(),
        )

        # GPS extraction
        result["gps"] = _extract_gps_from_exif(tags)

    except Exception:
        pass
    return result


def _from_pillow(filepath: Path) -> _ExifResult:
    """Extract metadata from an image using Pillow (HEIC fallback)."""
    result: _ExifResult = {"date": None, "camera": None, "gps": None}
    try:
        try:
            import pillow_heif  # noqa: F811

            pillow_heif.register_heif_opener()
        except ImportError:
            pass

        from PIL import Image  # noqa: F811
        from PIL.ExifTags import Base as ExifTags

        img = Image.open(filepath)
        exif = img.getexif()
        if not exif:
            return result

        # Date
        for tag_id in (ExifTags.DateTimeOriginal, ExifTags.DateTime):
            raw = exif.get(tag_id)
            if raw:
                date = _parse_exif_date(str(raw))
                if date:
                    result["date"] = date
                    break

        # Camera
        make = str(exif.get(ExifTags.Make, "")).strip()
        model = str(exif.get(ExifTags.Model, "")).strip()
        result["camera"] = _extract_camera(make, model)

        # GPS from Pillow IFD
        gps_ifd = exif.get_ifd(0x8825)
        if gps_ifd:
            result["gps"] = _extract_gps_from_pillow(gps_ifd)

    except Exception:
        logger.debug("Pillow HEIC fallback failed for %s", filepath)
    return result


def _from_ffprobe(filepath: Path) -> _ExifResult:
    """Extract creation date, camera model, and GPS from a video file using ffprobe.

    Returns a dict with None values when ffprobe is unavailable or metadata is absent.
    """
    result: _ExifResult = {"date": None, "camera": None, "gps": None}

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
        result["camera"] = _extract_camera(make, model)

        # GPS — ISO 6709 format (e.g. "+48.8584+002.2945+000.000/")
        for key in ("com.apple.quicktime.location.ISO6709", "location"):
            raw = tags.get(key)
            if raw:
                gps = _parse_iso6709(raw)
                if gps:
                    result["gps"] = gps
                    break

    except Exception:
        pass
    return result


def _extract_camera(make: str, model: str) -> str | None:
    """Build a camera name from make and model, avoiding duplication."""
    if not make and not model:
        return None
    if make.lower() == "apple" and model.lower().startswith("iphone"):
        return model
    if make and model and make.lower() in model.lower():
        return model
    if make and model:
        return f"{make} {model}"
    return model or make


def _extract_gps_from_exif(tags: dict) -> tuple[float, float] | None:
    """Extract GPS coordinates from exifread tags."""
    lat_tag = tags.get("GPS GPSLatitude")
    lat_ref = tags.get("GPS GPSLatitudeRef")
    lon_tag = tags.get("GPS GPSLongitude")
    lon_ref = tags.get("GPS GPSLongitudeRef")

    if not all([lat_tag, lat_ref, lon_tag, lon_ref]):
        return None

    try:
        lat = _dms_to_decimal(lat_tag.values)
        lon = _dms_to_decimal(lon_tag.values)

        if str(lat_ref) == "S":
            lat = -lat
        if str(lon_ref) == "W":
            lon = -lon

        return (lat, lon)
    except Exception:
        return None


def _extract_gps_from_pillow(gps_ifd: dict) -> tuple[float, float] | None:
    """Extract GPS coordinates from a Pillow GPS IFD dict."""
    try:
        lat_ref = gps_ifd.get(1, "N")  # GPSLatitudeRef
        lat_dms = gps_ifd.get(2)  # GPSLatitude
        lon_ref = gps_ifd.get(3, "E")  # GPSLongitudeRef
        lon_dms = gps_ifd.get(4)  # GPSLongitude

        if lat_dms is None or lon_dms is None:
            return None

        lat = _dms_to_decimal(lat_dms)
        lon = _dms_to_decimal(lon_dms)

        if lat_ref == "S":
            lat = -lat
        if lon_ref == "W":
            lon = -lon

        return (lat, lon)
    except Exception:
        return None


def _dms_to_decimal(values: list | tuple) -> float:
    """Convert DMS (degrees, minutes, seconds) values to decimal degrees."""
    d = float(values[0])
    m = float(values[1])
    s = float(values[2])
    return d + m / 60.0 + s / 3600.0


def _parse_iso6709(value: str) -> tuple[float, float] | None:
    """Parse ISO 6709 location string (e.g. '+48.8584+002.2945+000.000/')."""
    match = re.match(r"([+-]\d+\.?\d*)\s*([+-]\d+\.?\d*)", value)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    return None


def _parse_ffprobe_date(value: str) -> datetime | None:
    """Parse an ISO 8601 date string from ffprobe (e.g. '2024-03-15T10:00:00.000000Z')."""
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
