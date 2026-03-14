"""CLI entry point for file-organizer."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from file_organizer.organizer import organise

logger = logging.getLogger("file_organizer")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="file-organizer",
        description="Copy or move photos/videos into dest/YYYY/YYYY-MM[-DD][_event].",
    )
    parser.add_argument("--source", type=Path, metavar="DIR", help="Source directory.")
    parser.add_argument("--dest", type=Path, metavar="DIR", help="Destination root.")
    parser.add_argument(
        "--event", "-e", type=str, help="Optional event name (e.g. 'Ski-Trip')."
    )
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
        "--move",
        "-m",
        action="store_true",
        help="Move files instead of copying them. Files that cannot be transferred "
        "(identical or superseded at destination) are left in the source.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        metavar="FILE",
        help="Write a log of skipped and superseded files (those left in source) to FILE.",
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
        help="Exclude files matching NAME (e.g. '.DS_Store'). May be repeated.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output the summary as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug).",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    source = args.source or _prompt_path("Source directory")
    dest = args.dest or _prompt_path("Destination directory")
    event = args.event or _prompt_optional("Event name (optional)")
    group_by_day = args.day or (
        args.day is False and _prompt_bool("Group by day?", default=False)
    )
    group_by_camera = args.camera or (
        args.camera is False and _prompt_bool("Group by camera?", default=False)
    )
    move = args.move or (
        args.move is False
        and _prompt_bool("Move files instead of copy?", default=False)
    )
    log_path = args.log
    dry_run = args.dry_run or _prompt_bool("Dry run?", default=False)

    if not source.is_dir():
        print(f"Error: source directory does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    mode_label = "move" if move else "copy"
    if dry_run:
        print(f"[dry-run] scanning {source} -> {dest}  (mode: {mode_label})\n")

    # Progress callback — print a counter unless JSON output is requested.
    progress_cb = None if args.json_output else _progress_printer()

    try:
        summary = organise(
            source,
            dest,
            event=event,
            group_by_day=group_by_day,
            group_by_camera=group_by_camera,
            move=move,
            dry_run=dry_run,
            log_path=log_path,
            exclude=args.exclude,
            progress=progress_cb,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json_output:
        _print_json(summary)
    else:
        # Clear the progress line before printing the summary.
        print("\r\033[K", end="", flush=True)
        _print_summary(summary, move=move, dry_run=dry_run, log_path=log_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


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
    value = input(f"{label}: ").strip()
    if not value:
        print("Error: path cannot be empty.", file=sys.stderr)
        sys.exit(1)
    return Path(value)


def _prompt_optional(label: str) -> str | None:
    value = input(f"{label}: ").strip()
    return value if value else None


def _prompt_bool(label: str, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    value = input(f"{label} {hint}: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes")


def _print_summary(summary: dict, *, move: bool, dry_run: bool, log_path: Path | None) -> None:
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

    print(f"\n{prefix}Done. " + "  |  ".join(parts))

    if n_superseded:
        print(f"\n{prefix}Superseded — transcoded/converted version already exists at destination:")
        for entry in summary["superseded"]:
            print(f"  {entry}")

    if n_skipped and move:
        print(f"\n{prefix}Skipped — identical file already at destination (left in source):")
        for entry in summary["skipped"]:
            print(f"  {entry}")

    if log_path and not dry_run:
        print(f"\n{prefix}Log written to: {log_path}")

    for err in summary["errors"]:
        print(f"  ERROR: {err}", file=sys.stderr)


def _print_json(summary: dict) -> None:
    print(json.dumps(summary, indent=2, default=str))
