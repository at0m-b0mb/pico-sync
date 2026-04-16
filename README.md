# 🔄 pico-sync

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](CHANGELOG.md)
[![MicroPython](https://img.shields.io/badge/MicroPython-compatible-orange?logo=micropython)](https://micropython.org/)

**A full-featured CLI and GUI tool for managing files on a Raspberry Pi Pico — or any MicroPython board — over a serial connection.**

[Features](#-features) · [Installation](#-installation) · [Quick Start](#-quick-start) · [CLI Reference](#-cli-reference) · [GUI Guide](#-gui-guide) · [Troubleshooting](#-troubleshooting)

</div>

---

## 🌟 Why pico-sync?

Working with a Raspberry Pi Pico means constantly copying files back and forth over a serial connection. The official `mpremote` tool is powerful but low-level — every operation requires you to remember exact flags and syntax.

**pico-sync** wraps `mpremote` into a friendly, high-level interface:

- 🖥️ **Two interfaces in one** — a scriptable CLI for automation and a visual GUI for interactive development
- 🔁 **Bidirectional sync** — copy files and entire folder trees from PC → Pico *or* Pico → PC with one command
- 🔍 **Smart skip** — unchanged files are skipped by default, so only what changed gets transferred
- ⚡ **Auto-detect** — no need to remember serial port names; pico-sync finds your device automatically
- 🧑‍💻 **Built-in editor** — edit, deploy, and run `.py` files directly from the GUI without switching tools
- 🔒 **Hash verification** — compare MD5/SHA-256 checksums between local and remote files to confirm transfers

---

## ✨ Features

| Feature | CLI | GUI |
|---------|:---:|:---:|
| Auto-detect connected Pico devices | ✅ | ✅ |
| List files on the Pico | ✅ | ✅ |
| Copy file / folder **PC → Pico** (recursive) | ✅ | ✅ |
| Copy file / folder **Pico → PC** (recursive) | ✅ | ✅ |
| Remove files / directories (recursive) | ✅ | ✅ |
| Create directories on the Pico | ✅ | ✅ |
| Deploy with skip-unchanged / force overwrite | ✅ | ✅ |
| Soft-reset the Pico | ✅ | ✅ |
| Run a Python script on the Pico | ✅ | ✅ |
| Execute arbitrary code snippets | ✅ | ✅ |
| Open interactive REPL | ✅ | ✅ |
| Compare file hashes (local ↔ Pico) | ✅ | ✅ |
| Mount a local directory on the Pico | ✅ | — |
| Built-in code editor with syntax-highlighted output | — | ✅ |
| Deploy + Run in one click | — | ✅ |
| Transfer panel (browse files/folders, send/receive) | — | ✅ |

---

## 📋 Requirements

| Requirement | Details |
|-------------|---------|
| **Python** | 3.8 or newer |
| **mpremote** | Official MicroPython remote tool — `pip install mpremote` |
| **customtkinter** | Modern Tkinter UI library (GUI only) — `pip install customtkinter` |
| **Hardware** | Raspberry Pi Pico or any MicroPython-compatible board connected via USB |

---

## 📦 Installation

### From source (recommended)

Clone the repository and install in editable mode so you always run the latest code:

```bash
git clone https://github.com/at0m-b0mb/pico-sync.git
cd pico-sync
pip install -e .
```

### Quick install (without cloning)

Install dependencies only (useful if you just want to run the scripts directly):

```bash
pip install -r requirements.txt
```

### Verify the installation

```bash
pico-sync --version   # prints the installed version
pico-sync devices     # lists any connected Pico devices
```

---

## 🚀 Quick Start

> **Tip:** All commands auto-detect your Pico's serial port. Plug in your device first.

### 1. Detect connected devices

```bash
pico-sync devices
```

### 2. List files on the Pico

```bash
pico-sync ls /
```

### 3. Copy a single file to the Pico

```bash
pico-sync copy main.py :main.py
```

### 4. Copy an entire folder to the Pico

```bash
pico-sync copy ./lib :/lib/
```

### 5. Pull files back from the Pico to your PC

```bash
pico-sync pull /main.py ./backup/main.py   # single file
pico-sync pull /lib ./backup/lib           # entire folder
```

### 6. Deploy and auto-reset

```bash
pico-sync deploy ./project :/app/ --reset
```

### 7. Launch the GUI

```bash
pico-sync-gui
# or equivalently
python -m pico_sync
```

---

## 🛠️ CLI Reference

All commands share a common `--port` / `-p` option to override the auto-detected serial port.

```
pico-sync [--port PORT] COMMAND [ARGS...]
```

---

### `devices` — list connected MicroPython boards

```bash
pico-sync devices
```

Scans all serial ports and lists any device running MicroPython.

---

### `ls [PATH]` — list files on the Pico

```bash
pico-sync ls /          # list root directory
pico-sync ls /lib       # list a subdirectory
```

`PATH` defaults to `/` if omitted.

---

### `copy SRC DEST` — upload a file or folder

Copy a local file or folder **to** the Pico. Folders are copied recursively.

```bash
pico-sync copy main.py :main.py                  # copy a file
pico-sync copy ./project :/project/              # copy a folder recursively
pico-sync copy --force main.py :main.py          # delete remote first, then copy
pico-sync copy --no-skip ./lib :/lib/            # copy all files, skip nothing
```

| Option | Description |
|--------|-------------|
| `--force` | Delete the remote file/folder first, then copy |
| `--no-skip` | Copy all files even if they haven't changed (by default unchanged files are skipped) |
| `-p PORT` | Override the serial port |

---

### `pull REMOTE_PATH LOCAL_DEST` — download a file or folder

Copy a file or folder **from** the Pico to your local machine. Folders are copied recursively.

```bash
pico-sync pull /main.py ./main.py          # download a single file
pico-sync pull /lib ./backup/lib           # download an entire folder
pico-sync pull -p COM9 /data ./data        # specify port explicitly
```

---

### `deploy SRC [DEST]` — deploy and optionally reset

Deploy a local file or folder to the Pico. Identical to `copy` but adds a `--reset` flag to soft-reset after the transfer completes.

```bash
pico-sync deploy ./project                     # deploy to Pico root
pico-sync deploy ./project :/app/ --reset      # deploy and reset afterwards
pico-sync deploy --force --reset main.py       # force overwrite, then reset
```

| Option | Description |
|--------|-------------|
| `--reset` | Soft-reset the Pico after deployment |
| `--force` | Delete existing remote file/folder before copying |
| `--no-skip` | Don't skip unchanged files |

---

### `mkdir PATH` — create a directory

```bash
pico-sync mkdir /lib
pico-sync mkdir /data/logs
```

---

### `rm PATH` — remove a file or directory

```bash
pico-sync rm /old_file.py         # remove a file
pico-sync rm -r /lib              # recursively remove a directory
```

| Option | Description |
|--------|-------------|
| `-r`, `--recursive` | Remove directory and all of its contents |

---

### `run FILE` — run a local script on the Pico

Copies and executes a local `.py` file on the Pico, streaming output live to your terminal.

```bash
pico-sync run blink.py
```

---

### `exec CODE` — execute a code snippet

Run an arbitrary Python expression or statement directly on the Pico without creating a file.

```bash
pico-sync exec "import machine; print(machine.freq())"
pico-sync exec "import os; print(os.listdir('/'))"
```

---

### `repl` — open an interactive REPL

Drop into a live MicroPython REPL session on the Pico. Press `Ctrl-X` to exit.

```bash
pico-sync repl
```

---

### `reset` — soft-reset the Pico

```bash
pico-sync reset
```

---

### `mount LOCAL_DIR` — mount a local directory

Mount a local directory on the Pico for live development. While mounted, the Pico reads files directly from your PC over the serial connection — no upload required.

```bash
pico-sync mount ./src
```

---

### `hash LOCAL_PATH [REMOTE_PATH]` — verify file integrity

Print the hash of a local file. When a `REMOTE_PATH` is also provided, the Pico file is hashed too and a **MATCH / DIFFER** verdict is printed — useful to confirm a transfer completed correctly.

```bash
pico-sync hash main.py                      # local hash only
pico-sync hash main.py /main.py             # compare local ↔ Pico
pico-sync hash -a sha256 main.py /main.py   # use SHA-256 instead of MD5
```

| Option | Description |
|--------|-------------|
| `-a ALGO` | Hash algorithm: `md5` (default) or `sha256` |

---

## 🖼️ GUI Guide

### Launching

```bash
pico-sync-gui
# or
python -m pico_sync
```

### Window Layout

The GUI window is split into four areas:

```
┌──────────────────────────────────────────────────────┐
│  Top bar   │  Device selector · Detect · Connect     │
├───────────────────────────┬──────────────────────────┤
│  Left panel               │  Right panel             │
│  ┌─────────────────────┐  │  ┌────────────────────┐  │
│  │  Local file browser │  │  │  Output terminal   │  │
│  └─────────────────────┘  │  └────────────────────┘  │
│  ┌─────────────────────┐  │  ┌────────────────────┐  │
│  │  Pico file browser  │  │  │  Exec input box    │  │
│  └─────────────────────┘  │  └────────────────────┘  │
│  ┌─────────────────────┐  │                           │
│  │  Transfer panel     │  │                           │
│  └─────────────────────┘  │                           │
├───────────────────────────┴──────────────────────────┤
│  Bottom panel  │  Code editor · Run · Deploy · Reset  │
└──────────────────────────────────────────────────────┘
```

### Connecting to a Device

1. Click **Detect** — pico-sync scans all serial ports for MicroPython boards
2. Select your device from the dropdown
3. Click **Connect** — the Pico file browser refreshes automatically

### File Operations (Left Panel)

**Local Files (top half):**

| Action | How |
|--------|-----|
| Select a file | Single-click |
| Select a folder | Single-click (highlighted in blue) |
| Navigate into a folder | Double-click |
| Go up one level | **Up** button |
| Pick a different root | **Browse** button |
| Upload to Pico | **Copy to Pico** or **Deploy** |
| Hash a file | **Hash** button |

**Pico Files (bottom half):**

| Action | How |
|--------|-----|
| Select a file or folder | Single-click |
| Download to local directory | **Copy to Local** |
| Open in built-in editor | **Open in Editor** |
| Delete (with confirmation) | **Remove** |
| Create a new directory | **MkDir** |
| Hash a file | **Hash** button |

### Transfer Panel

The **Transfer** panel gives you full path control over send and receive operations:

| Control | Description |
|---------|-------------|
| **Local path** | Browse or type the local file/folder path |
| **Remote path** | Pico destination path (e.g. `/` or `/lib/`) |
| **Send to Pico →** | Upload local file/folder to the Pico |
| **← Receive from Pico** | Download remote file/folder locally |
| **Compare Hashes** | Compare MD5 checksums of the local and remote files |

### Code Editor (Bottom Panel)

The built-in editor lets you write, edit, and run MicroPython code without leaving pico-sync:

| Button | What it does |
|--------|-------------|
| **Open** | Load a local `.py` file into the editor |
| **Save** | Save editor contents to disk |
| **Run on Pico** | Save the file, then execute it on the Pico (output streams live) |
| **Exec Snippet** | Execute only the selected text on the Pico |
| **Deploy+Run** | Copy the file to the Pico, then run it immediately |
| **Reset Pico** | Soft-reset the Pico |
| **Open REPL** | Open an interactive MicroPython REPL in a new terminal window |

### Output Terminal (Right Panel)

The terminal displays all command output with color-coded lines:
- 🔵 **Blue** — command being run
- 🟢 **Green** — successful output
- 🔴 **Red** — errors or warnings

Additional controls:

| Control | Description |
|---------|-------------|
| **Exec input box** | Type a Python one-liner and press Enter to run it immediately |
| **Copy Log** | Copy all terminal output to the clipboard |
| **Save Log** | Save terminal output to a `.txt` file |
| **Stop** | Terminate the currently running command |

---

## 📁 Project Structure

```
pico-sync/
├── pico_sync/
│   ├── __init__.py        # Package metadata and version
│   ├── __main__.py        # python -m pico_sync entry point (launches GUI)
│   ├── cli.py             # Click-based CLI commands
│   ├── commands.py        # mpremote command wrappers (core logic)
│   ├── device.py          # Serial device auto-detection
│   └── gui.py             # CustomTkinter GUI application
├── pyproject.toml         # Build config, dependencies, and entry points
├── requirements.txt       # Runtime dependencies
├── CHANGELOG.md           # Version history
├── LICENSE                # MIT License
├── .gitignore             # Git ignore rules
└── README.md              # This file
```

---

## 🔧 Troubleshooting

### `mpremote not found`

```bash
pip install mpremote
```

### No devices found

- Ensure your Pico is plugged in via USB and running MicroPython
- **Linux:** Add your user to the `dialout` group, then log out and back in:
  ```bash
  sudo usermod -a -G dialout $USER
  ```
- **macOS:** The device appears as `/dev/tty.usbmodem*` or `/dev/cu.usbmodem*`
- **Windows:** Check **Device Manager → Ports (COM & LPT)** for the assigned COM port

### Permission denied on serial port (Linux)

Grant temporary access:
```bash
sudo chmod 666 /dev/ttyACM0
```

Or grant permanent access (requires re-login):
```bash
sudo usermod -a -G dialout $USER
```

### GUI doesn't launch

Ensure both GUI dependencies are installed:

```bash
pip install customtkinter
```

`tkinter` is bundled with most Python distributions. If it's missing on Debian/Ubuntu:

```bash
sudo apt install python3-tk
```

### File transfer seems slow

By default, files that haven't changed are skipped. If you need to force a full re-transfer, use `--force` or `--no-skip`:

```bash
pico-sync copy --no-skip ./project :/project/
```

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repository and create a feature branch
2. Install the development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
3. Make your changes and run the linter:
   ```bash
   ruff check .
   ```
4. Open a pull request with a clear description of what changed and why

Please keep pull requests focused — one feature or fix per PR makes review much easier.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
Made with ❤️ for the MicroPython community
</div>
