"""CLI entry point for file-organizer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from file_organizer.organizer import organise


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="file-organizer",
        description="Copy photos, RAW files, and videos into dest/YYYY/MM/ using EXIF dates.",
    )
    parser.add_argument("--source", type=Path, metavar="DIR", help="Source directory to scan.")
    parser.add_argument("--dest", type=Path, metavar="DIR", help="Destination root directory.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned copies without writing any files.",
    )
    args = parser.parse_args()

    source = args.source or _prompt_path("Source directory")
    dest = args.dest or _prompt_path("Destination directory")
    dry_run = args.dry_run or _prompt_bool("Dry run?", default=False)

    if not source.is_dir():
        print(f"Error: source directory does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(f"[dry-run] scanning {source} -> {dest}\n")

    try:
        summary = organise(source, dest, dry_run=dry_run)
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
