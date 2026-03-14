"""Core organise logic: scan source directory and copy/move files to dest/YYYY/subfolder."""

from __future__ import annotations

import filecmp
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, TypedDict

from file_organizer.exif import Metadata, get_metadata

logger = logging.getLogger(__name__)

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

# Sidecar files that should follow their parent media file.
SIDECAR_EXTENSIONS: frozenset[str] = frozenset({".xmp", ".aae"})

# Extensions whose originals may have been superseded by a converted/transcoded format.
# .heic and .dng are the *target* converted formats — they are never themselves superseded.
_PHOTO_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".tiff", ".tif"})
_RAW_EXTENSIONS: frozenset[str] = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf"}
)
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v"})

# Suffix appended to the stem of HEVC-transcoded videos: {NAME}_HEVC.mp4
_HEVC_SUFFIX = "_HEVC"

# Default patterns to exclude (in addition to ._ prefix).
DEFAULT_EXCLUDES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db"})

# Progress callback type: (current_index, total_count, filepath)
ProgressCallback = Callable[[int, int, Path], None]


class Summary(TypedDict):
    transferred: int  # files successfully copied or moved
    skipped: list[str]  # "source  ->  identical at  dest" — file left in source
    superseded: list[str]  # "source  ->  superseded by  dest" — file left in source
    errors: list[str]
    sidecars: int  # sidecar files transferred alongside their parent


def organise(
    source: Path,
    dest: Path,
    event: str | None = None,
    group_by_day: bool = False,
    group_by_camera: bool = False,
    move: bool = False,
    dry_run: bool = False,
    log_path: Path | None = None,
    exclude: list[str] | None = None,
    progress: ProgressCallback | None = None,
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
        exclude:         Additional filename patterns to exclude (matched against filename).
        progress:        Optional callback invoked for each file: (index, total, filepath).

    Returns:
        A summary with counts of transferred files, skipped/superseded file details,
        and any error messages.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source}")

    summary: Summary = {
        "transferred": 0,
        "skipped": [],
        "superseded": [],
        "errors": [],
        "sidecars": 0,
    }

    exclude_names = DEFAULT_EXCLUDES | frozenset(exclude or [])

    # Collect eligible files.
    files = _collect_files(source, exclude_names)
    total = len(files)
    logger.info("Found %d supported file(s) in %s", total, source)

    # Pre-fetch metadata concurrently for I/O-bound EXIF / ffprobe reads.
    metadata_map = _prefetch_metadata(files)

    for i, filepath in enumerate(files, 1):
        if progress:
            progress(i, total, filepath)

        try:
            meta = metadata_map.get(filepath)
            if meta is None:
                meta = get_metadata(filepath)
            _process_file(
                filepath, dest, event, group_by_day, group_by_camera, move, dry_run,
                summary, meta,
            )
        except Exception as exc:
            summary["errors"].append(f"{filepath}: {exc}")

    if log_path is not None and not dry_run:
        _write_log(log_path, summary, source, dest, move)

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_files(source: Path, exclude_names: frozenset[str]) -> list[Path]:
    """Return sorted list of supported media files, filtering out excluded names."""
    files: list[Path] = []
    for filepath in source.rglob("*"):
        if not filepath.is_file():
            continue
        if filepath.name.startswith("._"):
            continue
        if filepath.name in exclude_names:
            continue
        if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        files.append(filepath)
    files.sort()
    return files


def _prefetch_metadata(files: list[Path]) -> dict[Path, Metadata]:
    """Read metadata for all files concurrently using a thread pool."""
    metadata_map: dict[Path, Metadata] = {}
    if not files:
        return metadata_map

    with ThreadPoolExecutor() as pool:
        future_to_path = {pool.submit(get_metadata, f): f for f in files}
        for future in as_completed(future_to_path):
            filepath = future_to_path[future]
            try:
                metadata_map[filepath] = future.result()
            except Exception:
                logger.debug("Metadata prefetch failed for %s, will retry inline", filepath)
    return metadata_map


def _process_file(
    filepath: Path,
    dest: Path,
    event: str | None,
    group_by_day: bool,
    group_by_camera: bool,
    move: bool,
    dry_run: bool,
    summary: Summary,
    meta: Metadata,
) -> None:
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
        if meta["camera"]:
            camera = meta["camera"]
        elif filepath.suffix.lower() in _VIDEO_EXTENSIONS:
            camera = "VID"
        else:
            camera = "Unknown Camera"
        target_dir = target_dir / camera

    # Check whether a transcoded/converted version already exists at the destination.
    # If so, mark as superseded and leave in source — do NOT copy/move.
    superseding = _find_superseding_file(filepath, target_dir)
    if superseding is not None:
        summary["superseded"].append(f"{filepath}  ->  superseded by  {superseding}")
        logger.info("[superseded]  %s  (already converted as  %s)", filepath, superseding.name)
        return

    target = _resolve_target(filepath, target_dir)

    if target is None:
        # Byte-identical file already present — leave in source.
        dest_path = target_dir / filepath.name
        summary["skipped"].append(f"{filepath}  ->  identical at  {dest_path}")
        logger.info("[skip]  %s", filepath)
        return

    action = "move" if move else "copy"
    if dry_run:
        logger.info("[%s]  %s  ->  %s", action, filepath, target)
        summary["transferred"] += 1
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(filepath, target)
    else:
        shutil.copy2(filepath, target)
    summary["transferred"] += 1
    logger.debug("[%s]  %s  ->  %s", action, filepath, target)

    # Transfer sidecar files (.xmp, .aae) alongside the main file.
    _transfer_sidecars(filepath, target, move, summary)


def _transfer_sidecars(
    source: Path,
    target: Path,
    move: bool,
    summary: Summary,
) -> None:
    """Copy or move sidecar files that share the same stem as *source*."""
    for ext in SIDECAR_EXTENSIONS:
        sidecar = source.with_suffix(ext)
        if not sidecar.is_file():
            continue
        sidecar_dest = target.with_suffix(ext)
        if move:
            shutil.move(sidecar, sidecar_dest)
        else:
            shutil.copy2(sidecar, sidecar_dest)
        summary["sidecars"] += 1
        logger.debug("[sidecar]  %s  ->  %s", sidecar, sidecar_dest)


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
