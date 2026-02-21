# CLAUDE.md

This file provides guidance for AI assistants (and developers) working on this repository.

## Project Overview

**py-file-organizer-v1** is a Python-based file organization tool. The project automatically organizes files in a given directory by sorting them into subdirectories based on configurable rules (e.g., file extension, date modified, file size).

**Status:** Early development — the repository was just initialized and does not yet contain source code, tests, or build infrastructure.

## Repository Structure

```
py-file-organizer-v1/
├── CLAUDE.md          # This file — AI assistant guidance
├── README.md          # Project documentation
└── (source code TBD)
```

### Planned structure (follow this layout as the project grows)

```
py-file-organizer-v1/
├── src/
│   └── file_organizer/
│       ├── __init__.py
│       ├── main.py          # CLI entry point
│       ├── organizer.py     # Core organization logic
│       ├── rules.py         # File classification rules
│       └── utils.py         # Shared utilities
├── tests/
│   ├── __init__.py
│   ├── test_organizer.py
│   ├── test_rules.py
│   └── test_utils.py
├── pyproject.toml           # Project metadata, dependencies, tool config
├── requirements.txt         # Pinned dependencies (for pip users)
├── .gitignore
├── README.md
└── CLAUDE.md
```

## Development Conventions

### Python

- **Version:** Python 3.10+
- **Style:** Follow PEP 8. Use type hints for function signatures.
- **Imports:** Group in order: stdlib, third-party, local. Use absolute imports.
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.

### Project setup (once infrastructure exists)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running tests

```bash
pytest tests/
```

### Linting and formatting

```bash
ruff check .
ruff format .
```

## Git Workflow

- **Default branch:** `main`
- Write clear, concise commit messages describing *why* a change was made.
- Keep commits atomic — one logical change per commit.

## Key Design Decisions

1. **src layout** — Use `src/file_organizer/` to avoid import ambiguity and follow modern Python packaging conventions.
2. **pyproject.toml** — Use `pyproject.toml` as the single source for project metadata, dependencies, and tool configuration (ruff, pytest, etc.). Do not use `setup.py` or `setup.cfg`.
3. **CLI interface** — Use `argparse` from the standard library for the CLI. Only introduce `click` or `typer` if complexity warrants it.
4. **No over-engineering** — Start simple. Avoid premature abstractions, plugin systems, or config file formats until the core functionality works.

## Guidelines for AI Assistants

- Read existing code before making changes. Do not guess at file contents.
- Keep changes minimal and focused on the task at hand.
- Add tests for new functionality. Run existing tests before and after changes.
- Do not add dependencies without clear justification.
- Do not create documentation files beyond README.md and CLAUDE.md unless asked.
- When creating new Python files, always include the `src/file_organizer/` package path.
- Prefer standard library solutions over third-party packages when reasonable.
