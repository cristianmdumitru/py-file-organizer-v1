"""Core organise logic: scan source directory and copy/move files to dest/YYYY/subfolder."""

from __future__ import annotations

import filecmp
import hashlib
import json
import logging
import os
import shutil
import time
import urllib.request
from collections import defaultdict
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
_PHOTO_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".tiff", ".tif"})
_RAW_EXTENSIONS: frozenset[str] = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf"}
)
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v"})

_HEVC_SUFFIX = "_HEVC"

# Default patterns to exclude (in addition to ._ prefix).
DEFAULT_EXCLUDES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db"})

# Progress callback type: (current_index, total_count, filepath)
ProgressCallback = Callable[[int, int, Path], None]


class Summary(TypedDict):
    transferred: int
    skipped: list[str]
    superseded: list[str]
    errors: list[str]
    sidecars: int
    bytes_transferred: int
    verified: int
    verify_failed: list[str]
    unstable: int
    elapsed: float


def organise(
    source: Path,
    dest: Path,
    event: str | None = None,
    group_by_day: bool = False,
    group_by_camera: bool = False,
    group_by_location: bool = False,
    move: bool = False,
    dry_run: bool = False,
    log_path: Path | None = None,
    exclude: list[str] | None = None,
    progress: ProgressCallback | None = None,
    verify: bool = False,
    cleanup: bool = False,
    rename_pattern: str | None = None,
    manifest_path: Path | None = None,
    staging: Path | None = None,
    settle_seconds: float = 5.0,
    one_by_one: bool = False,
    notify_url: str | None = None,
) -> Summary:
    """Recursively copy or move supported media files from *source* to *dest/YYYY/subfolder*.

    Args:
        source:            Directory to scan (recursively).
        dest:              Root destination directory.
        event:             Optional event name to append to the subfolder.
        group_by_day:      Group by day (YYYY-MM-DD) instead of month.
        group_by_camera:   Group by camera model within the subfolder.
        group_by_location: Group by GPS location within the subfolder.
        move:              Move files instead of copying them.
        dry_run:           Print planned actions without touching the filesystem.
        log_path:          Write a log of skipped/superseded files to this path.
        exclude:           Additional filename patterns to exclude.
        progress:          Callback invoked for each file: (index, total, filepath).
        verify:            SHA-256 verify each copy after transfer.
        cleanup:           Remove empty source directories after move.
        rename_pattern:    Rename files using pattern (e.g. '{date}_{camera}_{seq}').
        manifest_path:     Write a JSON manifest of all operations to this path.
        staging:           Staging directory. Files here are moved to *source* once stable.
        settle_seconds:    Min age (seconds) before a staged file is promoted (default: 5).
        one_by_one:        Skip bulk disk space pre-check and metadata prefetch; read
                           and move each file individually so each move frees space
                           before the next.
        notify_url:        Optional URL to POST to after a successful batch.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source}")

    summary: Summary = {
        "transferred": 0,
        "skipped": [],
        "superseded": [],
        "errors": [],
        "sidecars": 0,
        "bytes_transferred": 0,
        "verified": 0,
        "verify_failed": [],
        "unstable": 0,
        "elapsed": 0.0,
    }

    # Promote stable files from staging to source before scanning.
    if staging is not None:
        n_promoted = _promote_stable_files(staging, source, settle_seconds, summary)
        if n_promoted:
            logger.info("Promoted %d file(s) from staging", n_promoted)

    # Manifest collects all operations for the undo file.
    manifest_ops: list[dict[str, str]] = []
    # Sequence counters per target directory for rename patterns.
    seq_counters: dict[Path, int] = defaultdict(int)

    exclude_names = DEFAULT_EXCLUDES | frozenset(exclude or [])

    files = _collect_files(source, exclude_names)
    total = len(files)
    logger.info("Found %d supported file(s) in %s", total, source)

    # In one-by-one mode, skip the bulk disk space pre-check and metadata
    # prefetch — each file is read and moved individually so each move frees
    # space before the next file is processed.
    if not dry_run and files and not one_by_one:
        _check_disk_space(files, dest)

    metadata_map = _prefetch_metadata(files) if not one_by_one else {}

    t0 = time.monotonic()

    # Group files by their computed target_dir so we can amortize the
    # per-dir listdir + mkdir across all files heading into the same
    # folder. On a spinning-rust destination this turns N files × ~5
    # stat() calls into one listdir per target_dir — big thrash win for
    # SD-card-sized batches that all land in the same YYYY-MM/Camera/
    # subtree.
    grouped: dict[Path, list[tuple[Path, Metadata]]] = defaultdict(list)
    for filepath in files:
        meta = metadata_map.get(filepath)
        if meta is None:
            meta = get_metadata(filepath)
        target_dir = _compute_target_dir(
            filepath,
            dest,
            event,
            group_by_day,
            group_by_camera,
            group_by_location,
            meta,
        )
        grouped[target_dir].append((filepath, meta))

    processed = 0
    for target_dir in sorted(grouped):
        # Prepare the dir once and snapshot its contents for cheap
        # superseding / collision lookups. Kept as a lowercase set so
        # later files in the batch see writes from earlier ones.
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
        try:
            existing: set[str] | None = {name.lower() for name in os.listdir(target_dir)}
        except FileNotFoundError:
            existing = set()

        for filepath, meta in grouped[target_dir]:
            processed += 1
            if progress:
                progress(processed, total, filepath)

            try:
                _process_file(
                    filepath,
                    target_dir,
                    move,
                    dry_run,
                    summary,
                    meta,
                    verify,
                    rename_pattern,
                    seq_counters,
                    manifest_ops,
                    existing,
                )
            except Exception as exc:
                summary["errors"].append(f"{filepath}: {exc}")

    summary["elapsed"] = time.monotonic() - t0

    if log_path is not None and not dry_run:
        _write_log(log_path, summary, source, dest, move)

    if manifest_path is not None:
        _write_manifest(manifest_path, manifest_ops, source, dest, move)

    if cleanup and move and not dry_run:
        _cleanup_empty_dirs(source)

    if notify_url and summary["transferred"] > 0 and not dry_run:
        _send_notification(notify_url, summary)

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _send_notification(url: str, summary: Summary) -> None:
    """Send a POST request to notify other services of a successful batch."""
    try:
        data = json.dumps({"type": "refresh", "summary": summary}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                logger.warning("Notification failed with status %d", response.status)
    except Exception as exc:
        logger.warning("Failed to send notification to %s: %s", url, exc)


def _collect_files(source: Path, exclude_names: frozenset[str]) -> list[Path]:
    """Return sorted list of supported media files, filtering out excluded names."""
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(
        source, onerror=lambda e: logger.warning("Skipping inaccessible path: %s", e)
    ):
        for name in filenames:
            if name.startswith("._"):
                continue
            if name in exclude_names:
                continue
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            files.append(Path(dirpath) / name)
    files.sort()
    return files


def _promote_stable_files(
    staging: Path,
    source: Path,
    settle_seconds: float,
    summary: Summary,
) -> int:
    """Move files from staging to source once they've stopped being written."""
    promoted = 0
    now = time.time()
    for filepath in staging.rglob("*"):
        if not filepath.is_file():
            continue
        if filepath.name.startswith("._") or filepath.name in DEFAULT_EXCLUDES:
            continue
        if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS | SIDECAR_EXTENSIONS:
            continue
        try:
            stat = filepath.stat()
            age = now - stat.st_mtime
        except OSError:
            continue
        if stat.st_size == 0:
            summary["unstable"] += 1
            continue
        if age >= settle_seconds:
            rel = filepath.relative_to(staging)
            dest = source / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(filepath, dest)
            except PermissionError:
                logger.warning("[staged]  permission denied promoting %s", filepath.name)
                summary["errors"].append(f"{filepath}: permission denied during promotion")
                continue
            promoted += 1
            logger.info("[staged]  %s  (age %.0fs)", filepath.name, age)
        else:
            summary["unstable"] += 1
    # Clean up empty directories left behind after promotion.
    if promoted:
        _cleanup_empty_dirs(staging)
    return promoted


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


def _check_disk_space(files: list[Path], dest: Path) -> None:
    """Raise an error if the destination doesn't have enough free space."""
    total_size = sum(f.stat().st_size for f in files)
    # Ensure dest (or its closest existing parent) can be checked.
    check_path = dest
    while not check_path.exists():
        check_path = check_path.parent
    usage = shutil.disk_usage(check_path)
    if total_size > usage.free:
        total_mb = total_size / (1024 * 1024)
        free_mb = usage.free / (1024 * 1024)
        raise OSError(
            f"Not enough disk space: need {total_mb:.1f} MB but only {free_mb:.1f} MB free "
            f"at {check_path}"
        )


def _compute_target_dir(
    filepath: Path,
    dest: Path,
    event: str | None,
    group_by_day: bool,
    group_by_camera: bool,
    group_by_location: bool,
    meta: Metadata,
) -> Path:
    """Compute the destination directory for *filepath* based on its metadata.

    Extracted from the main loop so we can group files by target_dir and
    amortize per-dir filesystem work (mkdir, listdir) across a batch.
    """
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

    # Location grouping (before camera, so structure is .../Location/Camera/...)
    if group_by_location:
        gps = meta.get("gps")
        if gps:
            location = _coords_to_location(gps[0], gps[1])
        else:
            location = "Unknown Location"
        target_dir = target_dir / location

    if group_by_camera:
        if meta["camera"]:
            camera = meta["camera"]
        elif filepath.suffix.lower() in _VIDEO_EXTENSIONS:
            camera = "VID"
        else:
            camera = "Unknown Camera"
        target_dir = target_dir / camera

    return target_dir


def _process_file(
    filepath: Path,
    target_dir: Path,
    move: bool,
    dry_run: bool,
    summary: Summary,
    meta: Metadata,
    verify: bool,
    rename_pattern: str | None,
    seq_counters: dict[Path, int],
    manifest_ops: list[dict[str, str]],
    existing: set[str] | None,
) -> None:
    # Check whether a transcoded/converted version already exists at the destination.
    superseding = _find_superseding_file(filepath, target_dir, existing)
    if superseding is not None:
        summary["superseded"].append(f"{filepath}  ->  superseded by  {superseding}")
        manifest_ops.append(
            {
                "src": str(filepath),
                "dest": str(superseding),
                "action": "superseded",
            }
        )
        logger.info("[superseded]  %s  (already converted as  %s)", filepath, superseding.name)
        return

    # Apply rename pattern if provided.
    if rename_pattern:
        seq_counters[target_dir] += 1
        renamed = _apply_rename(rename_pattern, meta, filepath, seq_counters[target_dir])
        # Use the renamed filename for target resolution.
        renamed_path = filepath.parent / renamed
    else:
        renamed_path = filepath

    resolve_source = renamed_path if rename_pattern else filepath
    target = _resolve_target(resolve_source, target_dir, existing)

    if target is None:
        dest_path = target_dir / resolve_source.name
        summary["skipped"].append(f"{filepath}  ->  identical at  {dest_path}")
        manifest_ops.append({"src": str(filepath), "dest": str(dest_path), "action": "skipped"})
        logger.info("[skip]  %s", filepath)
        return

    action = "move" if move else "copy"
    if dry_run:
        logger.info("[%s]  %s  ->  %s", action, filepath, target)
        summary["transferred"] += 1
        manifest_ops.append({"src": str(filepath), "dest": str(target), "action": action})
        if existing is not None:
            existing.add(target.name.lower())
        return

    file_size = filepath.stat().st_size

    # Compute hash before transfer so we can verify even after a move.
    src_hash = _sha256(filepath) if verify else None

    if move:
        shutil.move(filepath, target)
    else:
        shutil.copy2(filepath, target)
    summary["transferred"] += 1
    summary["bytes_transferred"] += file_size
    manifest_ops.append({"src": str(filepath), "dest": str(target), "action": action})
    if existing is not None:
        existing.add(target.name.lower())
    logger.debug("[%s]  %s  ->  %s", action, filepath, target)

    # Post-transfer verification.
    if verify:
        if _sha256(target) == src_hash:
            summary["verified"] += 1
        else:
            summary["verify_failed"].append(f"{filepath}  ->  {target}")
            logger.warning("[VERIFY FAILED]  %s  ->  %s", filepath, target)

    # Transfer sidecar files (.xmp, .aae) alongside the main file.
    _transfer_sidecars(filepath, target, move, summary)


def _apply_rename(
    pattern: str,
    meta: Metadata,
    filepath: Path,
    seq: int,
) -> str:
    """Apply a rename pattern and return the new filename (with extension)."""
    date = meta["date"]
    camera = meta["camera"] or "Unknown"
    camera_safe = camera.replace(" ", "_").replace("/", "_")

    replacements = {
        "{date}": f"{date:%Y-%m-%d}",
        "{time}": f"{date:%H-%M-%S}",
        "{datetime}": f"{date:%Y-%m-%d_%H-%M-%S}",
        "{year}": f"{date:%Y}",
        "{month}": f"{date:%m}",
        "{day}": f"{date:%d}",
        "{camera}": camera_safe,
        "{seq}": f"{seq:03d}",
        "{original}": filepath.stem,
    }

    name = pattern
    for key, value in replacements.items():
        name = name.replace(key, value)

    return f"{name}{filepath.suffix}"


def _verify_file(source: Path, target: Path) -> bool:
    """Return True if source and target have identical SHA-256 hashes."""
    return _sha256(source) == _sha256(target)


def _sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _coords_to_location(lat: float, lon: float) -> str:
    """Convert GPS coordinates to a location folder name.

    Uses ``reverse_geocoder`` for city names when available, otherwise
    falls back to a coarse coordinate grid (e.g. '48.9N_2.3E').
    """
    try:
        import reverse_geocoder as rg

        results = rg.search([(lat, lon)], verbose=False)
        if results:
            city = results[0]["name"]
            country = results[0]["cc"]
            return f"{city}_{country}"
    except ImportError:
        pass

    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"
    return f"{abs(lat):.1f}{lat_dir}_{abs(lon):.1f}{lon_dir}"


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


def _cleanup_empty_dirs(source: Path) -> None:
    """Remove empty directories under *source* (bottom-up)."""
    for dirpath, dirnames, filenames in os.walk(str(source), topdown=False):
        path = Path(dirpath)
        if path == source:
            continue
        try:
            if not any(path.iterdir()):
                path.rmdir()
                logger.debug("[cleanup]  removed empty directory  %s", path)
        except OSError:
            pass


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

    if summary["verify_failed"]:
        lines.append(f"Verification failures ({len(summary['verify_failed'])}):")
        lines.extend(f"  {e}" for e in summary["verify_failed"])
        lines.append("")

    log_path.write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(
    manifest_path: Path,
    operations: list[dict[str, str]],
    source: Path,
    dest: Path,
    move: bool,
) -> None:
    """Write a JSON manifest of all operations for undo/audit purposes."""
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "mode": "move" if move else "copy",
        "source": str(source),
        "dest": str(dest),
        "operations": operations,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Manifest written to %s", manifest_path)


def _find_superseding_file(
    source: Path,
    target_dir: Path,
    existing: set[str] | None = None,
) -> Path | None:
    """Return the path of a converted/transcoded file that supersedes *source* at *target_dir*.

    If *existing* is provided, it's the case-insensitive set of filenames already
    in *target_dir*; the presence check becomes a set lookup. Otherwise we fall
    back to an ``exists()`` stat — useful for standalone callers/tests.
    """
    stem = source.stem
    ext = source.suffix.lower()

    def _has(name: str) -> bool:
        if existing is not None:
            return name.lower() in existing
        return (target_dir / name).exists()

    if ext in _PHOTO_EXTENSIONS:
        name = f"{stem}.heic"
        if _has(name):
            return target_dir / name

    if ext in _RAW_EXTENSIONS:
        name = f"{stem}.dng"
        if _has(name):
            return target_dir / name

    if ext in _VIDEO_EXTENSIONS and not stem.endswith(_HEVC_SUFFIX):
        name = f"{stem}{_HEVC_SUFFIX}.mp4"
        if _has(name):
            return target_dir / name

    return None


def _resolve_target(
    source: Path,
    target_dir: Path,
    existing: set[str] | None = None,
) -> Path | None:
    """Return the destination path for *source*, handling name conflicts.

    Same *existing* semantics as ``_find_superseding_file``. When a name
    collision is detected we still have to read the candidate for
    ``filecmp.cmp`` — that's unavoidable — but all the exists()-style
    probing for free slots is served from the set.
    """

    def _has(name: str) -> bool:
        if existing is not None:
            return name.lower() in existing
        return (target_dir / name).exists()

    name = source.name
    if not _has(name):
        return target_dir / name

    candidate = target_dir / name
    if filecmp.cmp(source, candidate, shallow=False):
        return None

    stem, suffix = source.stem, source.suffix
    counter = 1
    while True:
        attempt = f"{stem}_{counter}{suffix}"
        if not _has(attempt):
            return target_dir / attempt
        counter += 1
