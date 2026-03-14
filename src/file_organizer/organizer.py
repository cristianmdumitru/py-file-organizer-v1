"""Core organise logic: scan source directory and copy/move files to dest/YYYY/subfolder."""

from __future__ import annotations

import filecmp
import shutil
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from file_organizer.exif import get_metadata

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Photos
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".heic",
        # RAW
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".dng",
        ".orf",
        ".rw2",
        ".raf",
        # Video
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".m4v",
    }
)

# Extensions whose originals may have been superseded by a converted/transcoded format.
# .heic and .dng are the *target* converted formats — they are never themselves superseded.
_PHOTO_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".tiff", ".tif"})
_RAW_EXTENSIONS: frozenset[str] = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf"}
)
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v"})

# Suffix appended to the stem of HEVC-transcoded videos: {NAME}_HEVC.mp4
_HEVC_SUFFIX = "_HEVC"


class Summary(TypedDict):
    transferred: int  # files successfully copied or moved
    skipped: list[str]  # "source  ->  identical at  dest" — file left in source
    superseded: list[str]  # "source  ->  superseded by  dest" — file left in source
    errors: list[str]


def organise(
    source: Path,
    dest: Path,
    event: str | None = None,
    group_by_day: bool = False,
    group_by_camera: bool = False,
    move: bool = False,
    dry_run: bool = False,
    log_path: Path | None = None,
) -> Summary:
    """Recursively copy or move supported media files from *source* to *dest/YYYY/subfolder*.

    Subfolder naming:
      - Default: YYYY-MM
      - group_by_day=True: YYYY-MM-DD
      - event provided: <date-part>_event
      - group_by_camera=True: <subfolder>/<camera_model>

    Files that cannot be transferred because an identical or converted/transcoded version
    already exists at the destination are recorded in ``summary["skipped"]`` and
    ``summary["superseded"]`` respectively, and are never deleted from the source.

    Args:
        source:          Directory to scan (recursively).
        dest:            Root destination directory.
        event:           Optional event name to append to the subfolder.
        group_by_day:    If True, group files by day (YYYY-MM-DD) instead of month.
        group_by_camera: If True, group files by camera model within the subfolder.
        move:            If True, move files instead of copying them. Files that cannot
                         be transferred (skipped/superseded) are left in the source.
        dry_run:         When True, print planned actions without touching the filesystem.
        log_path:        If provided, write a log of all skipped and superseded files
                         (those left behind in the source) to this path.

    Returns:
        A summary with counts of transferred files, skipped/superseded file details,
        and any error messages.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source}")

    summary: Summary = {"transferred": 0, "skipped": [], "superseded": [], "errors": []}

    for filepath in sorted(source.rglob("*")):
        if not filepath.is_file():
            continue
        if filepath.name.startswith("._"):
            continue
        if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            _process_file(
                filepath, dest, event, group_by_day, group_by_camera, move, dry_run, summary
            )
        except Exception as exc:
            summary["errors"].append(f"{filepath}: {exc}")

    if log_path is not None and not dry_run:
        _write_log(log_path, summary, source, dest, move)

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _process_file(
    filepath: Path,
    dest: Path,
    event: str | None,
    group_by_day: bool,
    group_by_camera: bool,
    move: bool,
    dry_run: bool,
    summary: Summary,
) -> None:
    meta = get_metadata(filepath)
    date = meta["date"]

    # Structure: dest / YYYY / YYYY-MM[-DD][_event]
    year_str = f"{date.year:04d}"
    if group_by_day:
        subfolder = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
    else:
        subfolder = f"{date.year:04d}-{date.month:02d}"

    if event:
        subfolder = f"{subfolder}_{event}"

    target_dir = dest / year_str / subfolder

    if group_by_camera:
        camera = meta["camera"] or "Unknown Camera"
        target_dir = target_dir / camera

    # Check whether a transcoded/converted version already exists at the destination.
    # If so, mark as superseded and leave in source — do NOT copy/move.
    superseding = _find_superseding_file(filepath, target_dir)
    if superseding is not None:
        summary["superseded"].append(f"{filepath}  ->  superseded by  {superseding}")
        if dry_run:
            print(f"[superseded]  {filepath}  (already converted as  {superseding.name})")
        return

    target = _resolve_target(filepath, target_dir)

    if target is None:
        # Byte-identical file already present — leave in source.
        dest_path = target_dir / filepath.name
        summary["skipped"].append(f"{filepath}  ->  identical at  {dest_path}")
        if dry_run:
            print(f"[skip]  {filepath}")
        return

    action = "move" if move else "copy"
    if dry_run:
        print(f"[{action}]  {filepath}  ->  {target}")
        summary["transferred"] += 1
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(filepath, target)
    else:
        shutil.copy2(filepath, target)
    summary["transferred"] += 1


def _write_log(log_path: Path, summary: Summary, source: Path, dest: Path, move: bool) -> None:
    """Write a log of all files left behind (skipped + superseded + errors) to *log_path*."""
    mode_label = "move" if move else "copy"
    lines = [
        f"File Organizer Log — {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Mode: {mode_label}",
        f"Source: {source}",
        f"Dest:   {dest}",
        "",
    ]

    skipped = summary["skipped"]
    lines.append(f"Skipped — identical file already at destination ({len(skipped)}):")
    lines.extend(f"  {e}" for e in skipped) if skipped else lines.append("  (none)")
    lines.append("")

    superseded = summary["superseded"]
    lines.append(f"Superseded — converted/transcoded version at destination ({len(superseded)}):")
    lines.extend(f"  {e}" for e in superseded) if superseded else lines.append("  (none)")
    lines.append("")

    errors = summary["errors"]
    lines.append(f"Errors ({len(errors)}):")
    lines.extend(f"  {e}" for e in errors) if errors else lines.append("  (none)")
    lines.append("")

    log_path.write_text("\n".join(lines), encoding="utf-8")


def _find_superseding_file(source: Path, target_dir: Path) -> Path | None:
    """Return the path of a converted/transcoded file that supersedes *source* at *target_dir*.

    Checks three scenarios:
    - Photo (.jpg/.jpeg/.tiff/.tif) → superseded by ``{stem}.heic``
    - RAW  (.cr2/.cr3/.nef/.arw/.orf/.rw2/.raf) → superseded by ``{stem}.dng``
    - Video (.mp4/.mov/.avi/.mkv/.m4v, not already ``_HEVC``) → superseded by
      ``{stem}_HEVC.mp4``

    Returns None if no superseding file is found.
    """
    stem = source.stem
    ext = source.suffix.lower()

    if ext in _PHOTO_EXTENSIONS:
        candidate = target_dir / f"{stem}.heic"
        if candidate.exists():
            return candidate

    if ext in _RAW_EXTENSIONS:
        candidate = target_dir / f"{stem}.dng"
        if candidate.exists():
            return candidate

    if ext in _VIDEO_EXTENSIONS and not stem.endswith(_HEVC_SUFFIX):
        candidate = target_dir / f"{stem}{_HEVC_SUFFIX}.mp4"
        if candidate.exists():
            return candidate

    return None


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
