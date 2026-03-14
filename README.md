# py-file-organizer-v1

A minimal Python CLI that organises photos, RAW files, and videos into a `dest/YYYY/YYYY-MM/` folder hierarchy based on EXIF date metadata. Files can be **copied** (default) or **moved**.

## Supported formats

| Category | Extensions |
|----------|-----------|
| Photos   | `.jpg` `.jpeg` `.tiff` `.tif` `.heic` |
| RAW      | `.cr2` `.cr3` `.nef` `.arw` `.dng` `.orf` `.rw2` `.raf` |
| Video    | `.mp4` `.mov` `.avi` `.mkv` `.m4v` |

**Date source priority:** EXIF `DateTimeOriginal` → EXIF `DateTime` → file modification time (used for videos and files with no EXIF).

## Superseded file detection

Files are skipped (never overwritten or deleted) if a converted/transcoded version already exists at the destination:

| Source format | Superseded by |
|---------------|--------------|
| `.jpg` / `.jpeg` / `.tiff` / `.tif` | `{stem}.heic` |
| `.cr2` / `.cr3` / `.nef` / `.arw` / `.orf` / `.rw2` / `.raf` | `{stem}.dng` |
| any video (non-HEVC) | `{stem}_HEVC.mp4` |

Superseded files are reported in the summary and can be written to a log with `--log`.

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

### Move instead of copy

```bash
file-organizer --source ~/Pictures --dest ~/Organised --move
```

Files that cannot be transferred (identical or superseded at destination) are **left in the source** and reported.

### Log files left behind

```bash
file-organizer --source ~/Pictures --dest ~/Organised --move --log leftover.log
```

### Dry run (preview only, no files written)

```bash
file-organizer --source ~/Pictures --dest ~/Organised --dry-run
```

### Group by day / event / camera

```bash
# Day-level folders instead of month
file-organizer --source ~/Pictures --dest ~/Organised --day

# Append an event name to the folder
file-organizer --source ~/Pictures --dest ~/Organised --event "Ski-Trip"

# Sub-folder per camera model
file-organizer --source ~/Pictures --dest ~/Organised --camera
```

### Interactive mode (run without arguments)

```bash
file-organizer
# Source directory: /home/user/Pictures
# Destination directory: /home/user/Organised
# Event name (optional):
# Group by day? [y/N]: n
# Group by camera? [y/N]: n
# Dry run? [y/N]: n
```

## Output structure

```
Organised/
├── 2023/
│   └── 2023-08/
│       └── IMG_0001.jpg
└── 2024/
    ├── 2024-01/
    │   └── VID_20240112.mp4
    └── 2024-06_Ski-Trip/
        └── IMG_0042.CR2
```

## Development

```bash
pip install -e ".[dev]"
pytest -v
```
