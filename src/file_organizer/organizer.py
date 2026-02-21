"""Core organise logic: scan source directory and copy files to dest/YYYY/MM/."""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path
from typing import TypedDict

from file_organizer.exif import get_date

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Photos
        ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic",
        # RAW
        ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf",
        # Video
        ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    }
)


class Summary(TypedDict):
    copied: int
    skipped: int
    errors: list[str]


def organise(
    source: Path,
    dest: Path,
    event: str | None = None,
    group_by_day: bool = False,
    dry_run: bool = False,
) -> Summary:
    """Recursively copy supported media files from *source* to *dest/YYYY/subfolder*.

    Subfolder naming:
      - Default: YYYY-MM
      - group_by_day=True: YYYY-MM-DD
      - event provided: <date-part>_event

    Args:
        source:       Directory to scan (recursively).
        dest:         Root destination directory.
        event:        Optional event name to append to the subfolder.
        group_by_day: If True, group files by day (YYYY-MM-DD) instead of month.
        dry_run:      When True, print planned actions without touching the filesystem.

    Returns:
        A summary with counts of copied/skipped files and any error messages.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source}")

    summary: Summary = {"copied": 0, "skipped": 0, "errors": []}

    for filepath in sorted(source.rglob("*")):
        if not filepath.is_file():
            continue
        if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            _process_file(filepath, dest, event, group_by_day, dry_run, summary)
        except Exception as exc:
            summary["errors"].append(f"{filepath}: {exc}")

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _process_file(
    filepath: Path,
    dest: Path,
    event: str | None,
    group_by_day: bool,
    dry_run: bool,
    summary: Summary,
) -> None:
    date = get_date(filepath)

    # Structure: dest / YYYY / YYYY-MM[-DD][_event]
    year_str = f"{date.year:04d}"
    if group_by_day:
        subfolder = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
    else:
        subfolder = f"{date.year:04d}-{date.month:02d}"

    if event:
        subfolder = f"{subfolder}_{event}"

    target_dir = dest / year_str / subfolder
    target = _resolve_target(filepath, target_dir)

    if target is None:
        # Identical file already present — skip
        summary["skipped"] += 1
        if dry_run:
            print(f"[skip]  {filepath}")
        return

    if dry_run:
        print(f"[copy]  {filepath}  ->  {target}")
        summary["copied"] += 1
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(filepath, target)
    summary["copied"] += 1


def _resolve_target(source: Path, target_dir: Path) -> Path | None:
    """Return the destination path for *source*, handling name conflicts.

    Returns None if an identical file already exists at the destination.
    """
    candidate = target_dir / source.name

    if not candidate.exists():
        return candidate

    # Byte-identical file already present → skip
    if filecmp.cmp(source, candidate, shallow=False):
        return None

    # Different file with same name → find a free name
    stem, suffix = source.stem, source.suffix
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
