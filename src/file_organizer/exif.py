"""Date extraction from media files.

Priority order:
  1. EXIF DateTimeOriginal (when the shutter fired)
  2. EXIF DateTime        (last modification recorded by camera)
  3. File mtime           (filesystem fallback — used for video, untagged files)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TypedDict

import exifread

# EXIF date format written by cameras: "YYYY:MM:DD HH:MM:SS"
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"
_EXIF_DATE_TAGS = ("EXIF DateTimeOriginal", "Image DateTime")
_EXIF_MAKE_TAG = "Image Make"
_EXIF_MODEL_TAG = "Image Model"


class Metadata(TypedDict):
    date: datetime
    camera: str | None


def get_metadata(filepath: Path) -> Metadata:
    """Return the best available date and camera info for *filepath*."""
    exif_data = _from_exif(filepath)
    if exif_data["date"] is not None:
        return {"date": exif_data["date"], "camera": exif_data["camera"]}

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


def _parse_exif_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), _EXIF_DATE_FMT)
    except ValueError:
        return None


def _from_mtime(filepath: Path) -> datetime:
    return datetime.fromtimestamp(filepath.stat().st_mtime)
