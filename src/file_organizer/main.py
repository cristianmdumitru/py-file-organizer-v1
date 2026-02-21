"""CLI entry point for file-organizer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from file_organizer.organizer import organise


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="file-organizer",
        description="Copy photos/videos into dest/YYYY/YYYY-MM[-DD][_event] using EXIF dates.",
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
        "--dry-run",
        action="store_true",
        help="Print planned copies without writing any files.",
    )
    args = parser.parse_args()

    source = args.source or _prompt_path("Source directory")
    dest = args.dest or _prompt_path("Destination directory")
    event = args.event or _prompt_optional("Event name (optional)")
    group_by_day = args.day or (args.day is False and _prompt_bool("Group by day?", default=False))
    dry_run = args.dry_run or _prompt_bool("Dry run?", default=False)

    if not source.is_dir():
        print(f"Error: source directory does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(f"[dry-run] scanning {source} -> {dest}\n")

    try:
        summary = organise(
            source,
            dest,
            event=event,
            group_by_day=group_by_day,
            dry_run=dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_summary(summary, dry_run)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _print_summary(summary: dict, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    print(
        f"\n{prefix}Done. "
        f"Copied: {summary['copied']}  |  "
        f"Skipped: {summary['skipped']}  |  "
        f"Errors: {len(summary['errors'])}"
    )
    for err in summary["errors"]:
        print(f"  ERROR: {err}", file=sys.stderr)
