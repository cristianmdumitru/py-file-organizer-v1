"""CLI entry point for file-organizer."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from file_organizer.organizer import organise

logger = logging.getLogger("file_organizer")

# Config file location.
_CONFIG_PATHS = [
    Path.home() / ".config" / "file-organizer" / "config.toml",
    Path.home() / ".file-organizer.toml",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="file-organizer",
        description="Copy or move photos/videos into dest/YYYY/YYYY-MM[-DD][_event].",
    )
    parser.add_argument("--source", type=Path, metavar="DIR", help="Source directory.")
    parser.add_argument("--dest", type=Path, metavar="DIR", help="Destination root.")
    parser.add_argument("--event", "-e", type=str, help="Optional event name (e.g. 'Ski-Trip').")
    parser.add_argument(
        "--day",
        "-d",
        action="store_true",
        help="Group by day (YYYY-MM-DD) instead of month.",
    )
    parser.add_argument(
        "--camera",
        "-c",
        action="store_true",
        help="Group by camera model within the destination folder.",
    )
    parser.add_argument(
        "--location",
        action="store_true",
        help="Group by GPS location. Install 'reverse_geocoder' for city names.",
    )
    parser.add_argument(
        "--move",
        "-m",
        action="store_true",
        help="Move files instead of copying them.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        metavar="FILE",
        help="Write a log of skipped/superseded files to FILE.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing any files.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="NAME",
        help="Exclude files matching NAME. May be repeated.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output the summary as JSON.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="SHA-256 verify each file after copying.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove empty source directories after --move.",
    )
    parser.add_argument(
        "--rename",
        type=str,
        metavar="PATTERN",
        help="Rename files using pattern. Placeholders: "
        "{date}, {time}, {datetime}, {year}, {month}, {day}, "
        "{camera}, {seq}, {original}.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        metavar="FILE",
        help="Write a JSON manifest of all operations (for undo) to FILE.",
    )
    parser.add_argument(
        "--notify-url",
        type=str,
        metavar="URL",
        help="POST to this URL after a successful batch to notify other services.",
    )
    parser.add_argument(
        "--staging",
        type=Path,
        metavar="DIR",
        help="Staging directory. Files here are moved to --source once stable.",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="Min age (seconds) before a staged file is promoted (default: 5).",
    )
    parser.add_argument(
        "--one-by-one",
        action="store_true",
        help="Process only one file per cycle instead of all files at once.",
    )
    parser.add_argument(
        "--watch",
        type=int,
        nargs="?",
        const=60,
        metavar="SECONDS",
        help="Watch source directory and re-run every SECONDS (default: 60).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="Path to TOML config file (default: ~/.config/file-organizer/config.toml).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug).",
    )
    args = parser.parse_args()

    # Load config file and apply defaults (CLI args take precedence).
    config = _load_config(args.config)
    args = _apply_config(args, config)

    _setup_logging(args.verbose)

    source = args.source or _prompt_path("Source directory")
    dest = args.dest or _prompt_path("Destination directory")
    event = args.event or _prompt_optional("Event name (optional)")
    group_by_day = args.day or (args.day is False and _prompt_bool("Group by day?", default=False))
    group_by_camera = args.camera or (
        args.camera is False and _prompt_bool("Group by camera?", default=False)
    )
    group_by_location = args.location or (
        args.location is False and _prompt_bool("Group by location?", default=False)
    )
    move = args.move or (
        args.move is False and _prompt_bool("Move files instead of copy?", default=False)
    )
    verify = args.verify or (
        args.verify is False and _prompt_bool("Verify files after transfer?", default=False)
    )
    cleanup = args.cleanup or (
        args.cleanup is False and _prompt_bool("Remove empty source dirs after move?", default=False)
    )
    one_by_one = args.one_by_one or (
        args.one_by_one is False and _prompt_bool("Process one file at a time?", default=False)
    )
    log_path = args.log
    dry_run = args.dry_run or _prompt_bool("Dry run?", default=False)

    if not source.is_dir():
        print(f"Error: source directory does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    mode_label = "move" if move else "copy"
    if dry_run:
        print(f"[dry-run] scanning {source} -> {dest}  (mode: {mode_label})\n")

    # Build common kwargs for organise().
    organise_kwargs = dict(
        event=event,
        group_by_day=group_by_day,
        group_by_camera=group_by_camera,
        group_by_location=group_by_location,
        move=move,
        dry_run=dry_run,
        log_path=log_path,
        exclude=args.exclude,
        verify=verify,
        cleanup=cleanup,
        rename_pattern=args.rename,
        manifest_path=args.manifest,
        notify_url=args.notify_url,
        staging=args.staging,
        settle_seconds=args.settle,
        one_by_one=one_by_one,
    )

    if args.watch is not None:
        _watch_loop(
            source, dest, args.watch, args.json_output, move, dry_run, log_path, organise_kwargs
        )
    else:
        _run_once(source, dest, args.json_output, move, dry_run, log_path, organise_kwargs)


def _run_once(
    source: Path,
    dest: Path,
    json_output: bool,
    move: bool,
    dry_run: bool,
    log_path: Path | None,
    organise_kwargs: dict,
) -> None:
    progress_cb = None if json_output else _progress_printer()

    try:
        summary = organise(source, dest, progress=progress_cb, **organise_kwargs)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if json_output:
        _print_json(summary)
    else:
        print("\r\033[K", end="", flush=True)
        _print_summary(summary, move=move, dry_run=dry_run, log_path=log_path)


def _watch_loop(
    source: Path,
    dest: Path,
    interval: int,
    json_output: bool,
    move: bool,
    dry_run: bool,
    log_path: Path | None,
    organise_kwargs: dict,
) -> None:
    logger.info("Watching %s every %ds", source, interval)
    print(f"Watching {source} every {interval}s (Ctrl+C to stop)\n")
    try:
        while True:
            progress_cb = None if json_output else _progress_printer()
            try:
                summary = organise(source, dest, progress=progress_cb, **organise_kwargs)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                time.sleep(interval)
                continue

            logger.info(
                "Cycle complete: %d transferred, %d unstable",
                summary["transferred"],
                summary.get("unstable", 0),
            )

            if summary["transferred"] > 0:
                if json_output:
                    _print_json(summary)
                else:
                    print("\r\033[K", end="", flush=True)
                    _print_summary(summary, move=move, dry_run=dry_run, log_path=log_path)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped watching.")


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------


def _load_config(config_path: Path | None) -> dict:
    """Load a TOML config file. Returns an empty dict if no config is found."""
    try:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redefine]
    except ModuleNotFoundError:
        return {}

    paths = [config_path] if config_path else _CONFIG_PATHS
    for path in paths:
        if path and path.is_file():
            with path.open("rb") as f:
                logger.debug("Loading config from %s", path)
                return tomllib.load(f)
    return {}


def _apply_config(args: argparse.Namespace, config: dict) -> argparse.Namespace:
    """Apply config file defaults to args that weren't explicitly set on the CLI."""
    defaults = config.get("defaults", {})

    # Map config keys to argparse attribute names.
    bool_mappings = {
        "camera": "camera",
        "day": "day",
        "move": "move",
        "dry_run": "dry_run",
        "verify": "verify",
        "cleanup": "cleanup",
        "location": "location",
        "one_by_one": "one_by_one",
    }
    for config_key, attr in bool_mappings.items():
        if config_key in defaults and not getattr(args, attr, False):
            setattr(args, attr, defaults[config_key])

    # Exclude: merge config list with CLI list.
    if "exclude" in defaults:
        config_excludes = defaults["exclude"]
        if isinstance(config_excludes, list):
            args.exclude = list(set(args.exclude + config_excludes))

    # String/path values.
    if "rename" in defaults and not args.rename:
        args.rename = defaults["rename"]

    if "staging" in defaults and not args.staging:
        args.staging = Path(defaults["staging"])

    if "settle" in defaults and args.settle == 5.0:
        args.settle = float(defaults["settle"])

    return args


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)


def _progress_printer() -> callable:
    """Return a callback that prints a progress counter on stderr."""

    def _callback(current: int, total: int, filepath: Path) -> None:
        print(
            f"\r[{current}/{total}] {filepath.name}\033[K",
            end="",
            flush=True,
            file=sys.stderr,
        )

    return _callback


def _prompt_path(label: str) -> Path:
    if not sys.stdin.isatty():
        print(f"Error: {label} is required in non-interactive mode.", file=sys.stderr)
        sys.exit(1)
    value = input(f"{label}: ").strip()
    if not value:
        print("Error: path cannot be empty.", file=sys.stderr)
        sys.exit(1)
    return Path(value)


def _prompt_optional(label: str) -> str | None:
    if not sys.stdin.isatty():
        return None
    value = input(f"{label}: ").strip()
    return value if value else None


def _prompt_bool(label: str, default: bool) -> bool:
    if not sys.stdin.isatty():
        return default
    hint = "[Y/n]" if default else "[y/N]"
    value = input(f"{label} {hint}: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes")


def _print_summary(
    summary: dict,
    *,
    move: bool,
    dry_run: bool,
    log_path: Path | None,
) -> None:
    prefix = "[dry-run] " if dry_run else ""
    action_label = "Moved" if move else "Copied"
    n_skipped = len(summary["skipped"])
    n_superseded = len(summary["superseded"])

    parts = [
        f"{action_label}: {summary['transferred']}",
        f"Skipped: {n_skipped}",
        f"Superseded: {n_superseded}",
        f"Errors: {len(summary['errors'])}",
    ]
    if summary.get("sidecars", 0):
        parts.append(f"Sidecars: {summary['sidecars']}")
    if summary.get("verified", 0):
        parts.append(f"Verified: {summary['verified']}")
    if summary.get("verify_failed"):
        parts.append(f"Verify FAILED: {len(summary['verify_failed'])}")
    if summary.get("unstable", 0):
        parts.append(f"Unstable: {summary['unstable']}")

    print(f"\n{prefix}Done. " + "  |  ".join(parts))

    # Transfer statistics.
    bytes_transferred = summary.get("bytes_transferred", 0)
    elapsed = summary.get("elapsed", 0.0)
    if bytes_transferred > 0 and elapsed > 0:
        size_mb = bytes_transferred / (1024 * 1024)
        throughput = size_mb / elapsed
        print(f"  {size_mb:.1f} MB in {elapsed:.1f}s ({throughput:.1f} MB/s)")

    if n_superseded:
        print(f"\n{prefix}Superseded — transcoded/converted version already exists at destination:")
        for entry in summary["superseded"]:
            print(f"  {entry}")

    if n_skipped and move:
        print(f"\n{prefix}Skipped — identical file already at destination (left in source):")
        for entry in summary["skipped"]:
            print(f"  {entry}")

    if summary.get("verify_failed"):
        print(f"\n{prefix}VERIFICATION FAILURES:")
        for entry in summary["verify_failed"]:
            print(f"  {entry}")

    if log_path and not dry_run:
        print(f"\n{prefix}Log written to: {log_path}")

    for err in summary["errors"]:
        print(f"  ERROR: {err}", file=sys.stderr)


def _print_json(summary: dict) -> None:
    print(json.dumps(summary, indent=2, default=str))
