# CLAUDE.md

This file provides guidance for AI assistants (and developers) working on this repository.

## Project Overview

**py-file-organizer-v1** copies photos, RAW files, and videos into a `dest/YYYY/MM/` folder hierarchy based on EXIF date metadata. Originals are never moved or deleted.

## Repository Structure

```
py-file-organizer-v1/
├── src/
│   └── file_organizer/
│       ├── __init__.py       # package marker (empty)
│       ├── main.py           # CLI entry point (argparse + interactive fallback)
│       ├── organizer.py      # scan + copy logic; SUPPORTED_EXTENSIONS defined here
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
2. **Copy, never move** — `shutil.copy2` is used everywhere. Source files are never touched.
3. **mtime fallback** — when EXIF is absent or malformed (typical for video files), the file's modification time determines the year/month destination.
4. **Duplicate handling** — identical files (same size + mtime) at the destination are silently skipped. Conflicting different files get a `_1`, `_2` … suffix on the stem.
5. **src layout** — `src/file_organizer/` avoids import ambiguity. All source lives under `src/`.
6. **`argparse` only** — no third-party CLI library. Interactive mode is a simple `input()` fallback when args are missing.

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
file-organizer [--source DIR] [--dest DIR] [--dry-run]
```

Running without arguments triggers interactive prompts.

## Python Conventions

- Python 3.10+
- PEP 8 with type hints on all function signatures
- `from __future__ import annotations` in every module (for PEP 604 union syntax on 3.10)
- Imports: stdlib → third-party → local, each group separated by a blank line
