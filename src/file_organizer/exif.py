"""Date extraction from media files.

Priority order:
  1. EXIF DateTimeOriginal (when the shutter fired)
  2. EXIF DateTime        (last modification recorded by camera)
  3. File mtime           (filesystem fallback — used for video, untagged files)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import exifread

# EXIF date format written by cameras: "YYYY:MM:DD HH:MM:SS"
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"
_EXIF_TAGS = ("EXIF DateTimeOriginal", "Image DateTime")


def get_date(filepath: Path) -> datetime:
    """Return the best available date for *filepath*."""
    date = _from_exif(filepath)
    if date is not None:
        return date
    return _from_mtime(filepath)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _from_exif(filepath: Path) -> datetime | None:
    try:
        with filepath.open("rb") as fh:
            tags = exifread.process_file(fh, stop_tag="DateTimeOriginal", details=False)
        for tag in _EXIF_TAGS:
            if tag in tags:
                return _parse_exif_date(str(tags[tag]))
    except Exception:
        pass
    return None


def _parse_exif_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), _EXIF_DATE_FMT)
    except ValueError:
        return None


def _from_mtime(filepath: Path) -> datetime:
    return datetime.fromtimestamp(filepath.stat().st_mtime)
