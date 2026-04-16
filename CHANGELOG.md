# Changelog

All notable changes to pico-sync are documented here.

## [0.2.0] — 2026-04-03

### Added

- **Bidirectional copy** — new `pull` CLI command to copy files and folders FROM the Pico to your PC.
- **Recursive folder copy in both directions** — select a folder in the GUI and copy it entirely to/from the Pico.
- **Recursive directory removal** — `rm -r` in CLI; GUI Remove button handles directories with contents.
- **Transfer panel in GUI** — dedicated Send/Receive section with browsable file and folder paths.
- **"Copy to Local" button** in the Pico file browser — one-click download of files or entire folders.
- **`ls_remote()` helper** — programmatic directory listing for Pico-to-local operations.
- **`cmd_cp_file_from_pico()`** — copy a single file from Pico to PC.
- **`cmd_cp_dir_from_pico()`** — recursively copy a directory from Pico to PC (with fallback for older mpremote).
- **CHANGELOG.md** — this file.
- **Comprehensive README** with full CLI reference, GUI guide, and troubleshooting.
- **`.gitignore`** for Python projects.

### Fixed

- **Folders could not be selected for copy/deploy in GUI** — single-click now selects a folder; double-click navigates into it. Previously, clicking a folder only navigated into it.
- **Remove button failed on directories** — now detects directories and uses `rmdir` (or recursive removal for non-empty dirs) instead of `rm`.
- **Copy from Pico failed for directories** — now uses a proper recursive walk-and-copy fallback when `cp -r` doesn't work.
- **Transfer Receive crashed on root path** — stripping `/` produced an empty string. Now validates input and shows a clear error.
- **Open in Editor on a directory** — now shows a warning instead of crashing.
- **`--check` flag compatibility** — gracefully falls back when older mpremote versions don't support `--check`.
- **`cmd_rm` on empty directories** — now correctly uses `rmdir` instead of `rm`.

## [0.1.0] — 2026-03-01

### Added

- Initial release with CLI and GUI.
- File listing, copy (PC → Pico), deploy, reset, run, exec, repl, mount, hash.
- Dark-themed CustomTkinter GUI with code editor and terminal output.
