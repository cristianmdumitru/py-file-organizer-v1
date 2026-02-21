# py-file-organizer-v1

A minimal Python CLI that organises photos, RAW files, and videos into a `dest/YYYY/MM/` folder hierarchy based on EXIF date metadata. Files are **copied**, leaving originals untouched.

## Supported formats

| Category | Extensions |
|----------|-----------|
| Photos   | `.jpg` `.jpeg` `.png` `.tiff` `.tif` `.webp` `.heic` |
| RAW      | `.cr2` `.cr3` `.nef` `.arw` `.dng` `.orf` `.rw2` `.raf` |
| Video    | `.mp4` `.mov` `.avi` `.mkv` `.m4v` |

**Date source priority:** EXIF `DateTimeOriginal` → EXIF `DateTime` → file modification time (used for videos and files with no EXIF).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

### With arguments

```bash
file-organizer --source ~/Pictures --dest ~/Organised
```

### Dry run (preview only, no files written)

```bash
file-organizer --source ~/Pictures --dest ~/Organised --dry-run
```

### Interactive mode (run without arguments)

```bash
file-organizer
# Source directory: /home/user/Pictures
# Destination directory: /home/user/Organised
# Dry run? [y/N]: n
```

## Output structure

```
Organised/
├── 2023/
│   └── 08/
│       └── IMG_0001.jpg
└── 2024/
    ├── 01/
    │   └── VID_20240112.mp4
    └── 06/
        └── IMG_0042.CR2
```

## Development

```bash
pip install -e ".[dev]"
pytest -v
```
