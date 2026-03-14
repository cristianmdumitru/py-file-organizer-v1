# CLAUDE.md

This file provides guidance for AI assistants (and developers) working on this repository.

## Project Overview

**py-file-organizer-v1** copies or moves photos, RAW files, and videos into a `dest/YYYY/YYYY-MM/` folder hierarchy based on EXIF date metadata. By default files are copied; pass `--move` to move them instead.

## Repository Structure

```
py-file-organizer-v1/
├── src/
│   └── file_organizer/
│       ├── __init__.py       # package marker (empty)
│       ├── main.py           # CLI entry point (argparse + interactive fallback)
│       ├── organizer.py      # scan + copy/move logic; SUPPORTED_EXTENSIONS defined here
│       └── exif.py           # date extraction: EXIF DateTimeOriginal > DateTime > mtime
├── tests/
│   ├── __init__.py
│   ├── test_exif.py          # unit tests for date extraction
│   └── test_organizer.py     # integration tests using tmp_path fixtures
├── pyproject.toml            # project metadata, deps, entry point, ruff + pytest config
├── .gitignore
├── README.md
└── CLAUDE.md
```

## Key Design Decisions

1. **`exifread` only** — zero external Python dependencies beyond `exifread`. No external binary (like `exiftool`) is required.
2. **Copy or move** — `shutil.copy2` (copy) or `shutil.move` (move) depending on the `--move` flag. Files that cannot be transferred (identical or superseded at destination) are always left in the source and never deleted.
3. **mtime fallback** — when EXIF is absent or malformed (typical for video files), the file's modification time determines the year/month destination.
4. **Duplicate handling** — identical files (byte-level `filecmp.cmp`) at the destination are silently skipped. Conflicting different files get a `_1`, `_2` … suffix on the stem.
5. **Superseded detection** — photos (`.jpg`/`.jpeg`/`.tiff`/`.tif`) superseded by `{stem}.heic`, RAW files superseded by `{stem}.dng`, and non-HEVC videos superseded by `{stem}_HEVC.mp4` are recorded but never transferred.
6. **Log file** — when `--log FILE` is passed (and `--dry-run` is not active), a plain-text log of all skipped and superseded files (those left in source) is written to FILE.
7. **src layout** — `src/file_organizer/` avoids import ambiguity. All source lives under `src/`.
8. **`argparse` only** — no third-party CLI library. Interactive mode is a simple `input()` fallback when args are missing.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest -v
```

Tests use `tmp_path` fixtures and `unittest.mock.patch` to mock `exifread.process_file` — no real media files are needed.

## Linting and Formatting

```bash
ruff check .
ruff format .
```

## Adding New File Types

Add the lowercase extension to `SUPPORTED_EXTENSIONS` in `src/file_organizer/organizer.py`. No other changes required.

## CLI Usage

```
file-organizer [--source DIR] [--dest DIR] [--event NAME] [--day] [--camera]
               [--move] [--log FILE] [--dry-run]
               [--staging DIR] [--settle SECONDS]
```

Running without arguments triggers interactive prompts.

### Staging Directory

The `--staging DIR` flag enables a two-phase ingest pattern for files arriving via NFS drag-and-drop. Files landing in the staging directory are only promoted to `--source` once their mtime is older than `--settle` seconds (default: 5) and they are non-zero size. This prevents the organizer from processing files that are still being written.

Files arriving via rsync with `--temp-dir=.partial` can write directly to `--source` (the `ready/` directory) since rsync uses atomic rename on completion.

## Python Conventions

- Python 3.10+
- PEP 8 with type hints on all function signatures
- `from __future__ import annotations` in every module (for PEP 604 union syntax on 3.10)
- Imports: stdlib → third-party → local, each group separated by a blank line
