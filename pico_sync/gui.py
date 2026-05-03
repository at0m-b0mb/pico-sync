"""Graphical user interface for pico-sync using CustomTkinter.

Launch with ``pico-sync-gui`` or ``python -m pico_sync``.

Layout
------
- **Top bar** — device selector, detect, connect
- **Middle pane** — file browsers (local + Pico) on the left, terminal on the right
- **Bottom pane** — code editor with run / deploy / reset controls
- **Status bar** — current status + connection info
"""

from __future__ import annotations

import os
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from typing import List, Optional

# Support running this file directly: ``python pico_sync/gui.py``
if __name__ == "__main__" and __package__ is None:
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    __package__ = "pico_sync"

import customtkinter as ctk

from .device import list_devices, find_device
from . import commands

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MONO_FONT = ("Consolas", 12) if sys.platform == "win32" else ("Courier New", 12)
MONO_FONT_SMALL = ("Consolas", 11) if sys.platform == "win32" else ("Courier New", 11)

_SELECTED_BG = "#1e3a5f"
_NORMAL_BG = "transparent"

# Terminal colour tags
_TAG_CMD = "#58a6ff"       # blue   — command lines ($ …)
_TAG_ERROR = "#f85149"     # red    — [ERROR]
_TAG_SUCCESS = "#3fb950"   # green  — [exit 0]
_TAG_WARN = "#d29922"      # amber  — [exit N>0]
_TAG_DOT_OFF = "#555555"   # grey   — disconnected dot
_TAG_DOT_ON = "#43a047"    # green  — connected dot


# ===================================================================
# Main application
# ===================================================================

class PicoSyncApp(ctk.CTk):
    """Main pico-sync GUI window."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()
        self.title("pico-sync")
        self.geometry("1150x820")
        self.minsize(900, 650)

        # State
        self._port: Optional[str] = None
        self._output_queue: queue.Queue[str] = queue.Queue()
        self._local_dir: str = os.getcwd()
        self._local_selected: Optional[str] = None
        self._local_selected_is_dir: bool = False
        self._pico_dir: str = "/"          # current Pico browse directory
        self._pico_selected: Optional[str] = None
        self._editor_file: Optional[str] = None
        self._pico_editor_path: Optional[str] = None  # Pico path when file opened from Pico
        self._local_btn_map: dict = {}
        self._pico_btn_map: dict = {}
        self._running_proc: Optional[subprocess.Popen] = None
        self._tmp_files: List[str] = []  # temp files to clean up on exit
        self._pico_is_dir: dict = {}

        self._build_ui()
        self._poll_output_queue()
        self._refresh_devices()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        """Clean up temp files and close the window."""
        for tmp in self._tmp_files:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        self.destroy()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=2)  # editor pane gets more vertical space
        self.grid_columnconfigure(0, weight=1)

        self._build_top_bar()
        self._build_middle_pane()
        self._build_editor_pane()
        self._build_status_bar()

    # -- Top bar --------------------------------------------------------

    def _build_top_bar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0, height=54)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(
            bar, text="🔌 pico-sync", font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, padx=16, pady=10)

        self._dot_label = ctk.CTkLabel(
            bar, text="●", font=("Segoe UI", 18), text_color=_TAG_DOT_OFF,
        )
        self._dot_label.grid(row=0, column=1, padx=(12, 2))

        ctk.CTkLabel(bar, text="Device:", font=("Segoe UI", 12)).grid(
            row=0, column=2, padx=(0, 4))

        self._device_var = ctk.StringVar(value="(none)")
        self._device_combo = ctk.CTkComboBox(
            bar, variable=self._device_var, values=["(none)"], width=220,
            command=self._on_device_selected, font=("Segoe UI", 12),
        )
        self._device_combo.grid(row=0, column=3, padx=4)

        ctk.CTkButton(
            bar, text="🔍 Detect", width=95, font=("Segoe UI", 12),
            command=self._refresh_devices,
        ).grid(row=0, column=4, padx=4)

        self._connect_btn = ctk.CTkButton(
            bar, text="Connect", width=110, font=("Segoe UI", 12, "bold"),
            fg_color="#2e7d32", hover_color="#1b5e20",
            command=self._toggle_connect,
        )
        self._connect_btn.grid(row=0, column=5, padx=(4, 16), sticky="e")

    # -- Middle pane (file browser + terminal) --------------------------

    def _build_middle_pane(self) -> None:
        pane = ctk.CTkFrame(self, corner_radius=6)
        pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 2))
        pane.grid_rowconfigure(0, weight=1)
        pane.grid_columnconfigure(0, weight=1)
        pane.grid_columnconfigure(1, weight=2)

        self._build_file_browser(pane)
        self._build_terminal(pane)

    def _build_file_browser(self, parent: ctk.CTkFrame) -> None:
        fb = ctk.CTkFrame(parent, corner_radius=6)
        fb.grid(row=0, column=0, sticky="nsew", padx=(6, 3), pady=6)
        fb.grid_rowconfigure(2, weight=1)
        fb.grid_rowconfigure(7, weight=1)  # pico scrollable frame row
        fb.grid_columnconfigure(0, weight=1)

        # --- Local files header ---
        local_hdr = ctk.CTkFrame(fb, fg_color="transparent")
        local_hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        local_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            local_hdr, text="📁 Local Files", font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            local_hdr, text="⬆ Up", width=55, height=26,
            font=("Segoe UI", 11), command=self._navigate_up_local,
        ).grid(row=0, column=1, padx=(4, 0))

        # Path bar + browse
        local_top = ctk.CTkFrame(fb, fg_color="transparent")
        local_top.grid(row=1, column=0, sticky="ew", padx=6)
        local_top.grid_columnconfigure(0, weight=1)
        self._local_dir_var = ctk.StringVar(value=self._local_dir)
        ctk.CTkEntry(
            local_top, textvariable=self._local_dir_var,
            state="readonly", font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            local_top, text="Browse", width=70, font=("Segoe UI", 11),
            command=self._browse_local,
        ).grid(row=0, column=1)

        # Scrollable file list
        local_frame = ctk.CTkScrollableFrame(fb, height=140)
        local_frame.grid(row=2, column=0, sticky="nsew", padx=6, pady=(2, 0))
        local_frame.grid_columnconfigure(0, weight=1)
        self._local_frame = local_frame
        self._refresh_local_files()

        # Local action buttons — row A
        btn_row1 = ctk.CTkFrame(fb, fg_color="transparent")
        btn_row1.grid(row=3, column=0, sticky="ew", padx=6, pady=(4, 1))
        ctk.CTkButton(
            btn_row1, text="📝 Open in Editor", font=("Segoe UI", 11),
            command=self._open_local_file,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btn_row1, text="📤 Copy to Pico", fg_color="#1565c0",
            hover_color="#0d47a1", font=("Segoe UI", 11),
            command=self._copy_to_pico,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btn_row1, text="📤 Copy All to Pico", fg_color="#0d47a1",
            hover_color="#1a237e", font=("Segoe UI", 11),
            command=self._copy_all_to_pico,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btn_row1, text="🔄 Refresh", width=90, font=("Segoe UI", 11),
            command=self._refresh_local_files,
        ).pack(side="right", padx=2)

        # Local action buttons — row B
        btn_row1b = ctk.CTkFrame(fb, fg_color="transparent")
        btn_row1b.grid(row=4, column=0, sticky="ew", padx=6, pady=(1, 4))
        ctk.CTkButton(
            btn_row1b, text="🚀 Deploy", fg_color="#2e7d32",
            hover_color="#1b5e20", font=("Segoe UI", 11),
            command=self._deploy,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btn_row1b, text="🔍 Hash", width=70, font=("Segoe UI", 11),
            command=self._hash_local_file,
        ).pack(side="left", padx=2)

        # --- Pico files header ---
        pico_hdr = ctk.CTkFrame(fb, fg_color="transparent")
        pico_hdr.grid(row=5, column=0, sticky="ew", padx=8, pady=(8, 2))
        pico_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            pico_hdr, text="🤖 Pico Files", font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            pico_hdr, text="⬆ Up", width=55, height=26,
            font=("Segoe UI", 11), command=self._navigate_up_pico,
        ).grid(row=0, column=1, padx=(4, 0))

        # Pico path bar
        pico_top = ctk.CTkFrame(fb, fg_color="transparent")
        pico_top.grid(row=6, column=0, sticky="ew", padx=6)
        pico_top.grid_columnconfigure(0, weight=1)
        self._pico_dir_var = ctk.StringVar(value="/")
        ctk.CTkEntry(
            pico_top, textvariable=self._pico_dir_var,
            state="readonly", font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="ew")

        pico_frame = ctk.CTkScrollableFrame(fb, height=140)
        pico_frame.grid(row=7, column=0, sticky="nsew", padx=6, pady=(2, 0))
        pico_frame.grid_columnconfigure(0, weight=1)
        self._pico_frame = pico_frame

        # Pico action buttons — row A (primary)
        pico_a = ctk.CTkFrame(fb, fg_color="transparent")
        pico_a.grid(row=8, column=0, sticky="ew", padx=6, pady=(4, 1))
        ctk.CTkButton(
            pico_a, text="📝 Open in Editor", font=("Segoe UI", 11),
            command=self._open_pico_file,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            pico_a, text="⬇ Copy to Local", font=("Segoe UI", 11),
            command=self._copy_from_pico,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            pico_a, text="🔍 Hash", width=70, font=("Segoe UI", 11),
            command=self._hash_pico_file,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            pico_a, text="🔄 Refresh", font=("Segoe UI", 11),
            command=self._refresh_pico_files,
        ).pack(side="right", padx=2)

        # Pico action buttons — row B (destructive / mkdir)
        pico_b = ctk.CTkFrame(fb, fg_color="transparent")
        pico_b.grid(row=9, column=0, sticky="ew", padx=6, pady=(1, 4))
        ctk.CTkButton(
            pico_b, text="🗑 Remove", fg_color="#c62828",
            hover_color="#b71c1c", font=("Segoe UI", 11),
            command=self._remove_pico_file,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            pico_b, text="🗑 Delete All", fg_color="#7b1fa2",
            hover_color="#6a1b9a", font=("Segoe UI", 11),
            command=self._delete_all_pico,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            pico_b, text="📂 MkDir", font=("Segoe UI", 11),
            command=self._mkdir_pico,
        ).pack(side="left", padx=2)

    def _build_terminal(self, parent: ctk.CTkFrame) -> None:
        term = ctk.CTkFrame(parent, corner_radius=6)
        term.grid(row=0, column=1, sticky="nsew", padx=(3, 6), pady=6)
        term.grid_rowconfigure(1, weight=1)
        term.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(term, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="nw", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            hdr, text="💻 Output Terminal", font=("Segoe UI", 13, "bold"),
        ).pack(side="left")
        ctk.CTkButton(
            hdr, text="Clear", width=60, font=("Segoe UI", 11),
            command=self._terminal_clear,
        ).pack(side="left", padx=8)
        self._stop_btn = ctk.CTkButton(
            hdr, text="⏹ Stop", width=75, font=("Segoe UI", 11),
            fg_color="#c62828", hover_color="#b71c1c",
            command=self._stop_running, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=2)
        ctk.CTkButton(
            hdr, text="📋 Copy Log", width=90, font=("Segoe UI", 11),
            command=self._copy_log,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            hdr, text="💾 Save Log", width=85, font=("Segoe UI", 11),
            command=self._save_log,
        ).pack(side="left", padx=2)

        self._terminal = ctk.CTkTextbox(
            term, font=MONO_FONT, wrap="word",
            fg_color="#0d1117", text_color="#c9d1d9",
            scrollbar_button_color="#30363d",
        )
        self._terminal.grid(row=1, column=0, sticky="nsew", padx=6, pady=(2, 2))

        # Syntax-highlight tags
        tw = self._terminal._textbox
        tw.tag_configure("cmd", foreground=_TAG_CMD)
        tw.tag_configure("error", foreground=_TAG_ERROR)
        tw.tag_configure("success", foreground=_TAG_SUCCESS)
        tw.tag_configure("warn", foreground=_TAG_WARN)

        # Exec input
        inp = ctk.CTkFrame(term, fg_color="transparent")
        inp.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
        inp.grid_columnconfigure(0, weight=1)
        self._exec_entry = ctk.CTkEntry(
            inp, placeholder_text=">>> exec snippet on Pico…",
            font=MONO_FONT_SMALL,
        )
        self._exec_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._exec_entry.bind("<Return>", lambda _: self._exec_snippet())
        ctk.CTkButton(
            inp, text="Send", width=70, font=("Segoe UI", 11),
            command=self._exec_snippet,
        ).grid(row=0, column=1)

    # -- Editor pane ----------------------------------------------------

    def _build_editor_pane(self) -> None:
        ed = ctk.CTkFrame(self, corner_radius=6)
        ed.grid(row=2, column=0, sticky="nsew", padx=8, pady=(2, 4))
        ed.grid_rowconfigure(1, weight=1)
        ed.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(ed, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top, text="📝 Code Editor", font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, padx=(0, 12))
        self._editor_file_var = ctk.StringVar(value="(no file)")
        ctk.CTkEntry(
            top, textvariable=self._editor_file_var, state="readonly",
        ).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(top, text="Open", width=60, command=self._open_file).grid(
            row=0, column=2, padx=2)
        ctk.CTkButton(top, text="Save to PC", width=85, command=self._save_file).grid(
            row=0, column=3, padx=2)
        ctk.CTkButton(
            top, text="💾 Save to Pico", width=110,
            fg_color="#1565c0", hover_color="#0d47a1",
            command=self._save_to_pico,
        ).grid(row=0, column=4, padx=2)

        self._editor = ctk.CTkTextbox(
            ed, font=MONO_FONT, wrap="none",
            fg_color="#0d1117", text_color="#c9d1d9",
        )
        self._editor.grid(row=1, column=0, sticky="nsew", padx=6, pady=2)

        actions = ctk.CTkFrame(ed, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 6))
        for text, fg, hv, cmd in [
            ("▶ Run on Pico",  "#2e7d32", "#1b5e20", self._run_on_pico),
            ("⚡ Exec Snippet", "#e65100", "#bf360c", self._exec_editor_code),
            ("🔁 Reset Pico",  "#6a1b9a", "#4a148c", self._reset_pico),
            ("🚀 Deploy+Run",  "#1565c0", "#0d47a1", self._deploy_and_run),
            ("🔌 Open REPL",   "#37474f", "#263238", self._open_repl),
        ]:
            ctk.CTkButton(
                actions, text=text, fg_color=fg, hover_color=hv,
                command=cmd,
            ).pack(side="left", padx=4)

    # -- Status bar -----------------------------------------------------

    def _build_status_bar(self) -> None:
        self._status_var = ctk.StringVar(value="Ready")
        bar = ctk.CTkFrame(self, corner_radius=0, height=28)
        bar.grid(row=3, column=0, sticky="ew")
        ctk.CTkLabel(
            bar, textvariable=self._status_var, anchor="w",
            font=("Segoe UI", 11),
        ).pack(side="left", padx=12)
        self._port_label_var = ctk.StringVar(value="Not connected")
        ctk.CTkLabel(
            bar, textvariable=self._port_label_var, anchor="e",
            font=("Segoe UI", 11),
        ).pack(side="right", padx=12)

    # ==================================================================
    # Terminal helpers
    # ==================================================================

    def _poll_output_queue(self) -> None:
        """Drain the queue into the terminal widget every 100 ms."""
        lines: List[str] = []
        try:
            while True:
                lines.append(self._output_queue.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self._terminal_append("".join(lines))
        self.after(100, self._poll_output_queue)

    def _terminal_append(self, text: str) -> None:
        self._terminal.configure(state="normal")
        tw = self._terminal._textbox
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            if stripped.startswith("$ "):
                tw.insert("end", line, "cmd")
            elif stripped.startswith("[ERROR]"):
                tw.insert("end", line, "error")
            elif stripped.startswith("[exit 0]"):
                tw.insert("end", line, "success")
            elif stripped.startswith("[exit "):
                tw.insert("end", line, "warn")
            else:
                tw.insert("end", line)
        tw.see("end")
        self._terminal.configure(state="disabled")

    def _terminal_clear(self) -> None:
        self._terminal.configure(state="normal")
        self._terminal.delete("1.0", "end")
        self._terminal.configure(state="disabled")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    # ==================================================================
    # Background workers
    # ==================================================================

    def _run_cmd_bg(
        self, args: List[str], label: str = "", on_done=None,
    ) -> None:
        """Run *args* in a background thread, streaming output to terminal."""
        self._set_status(f"Running: {label or ' '.join(args[:3])}")
        self._output_queue.put(f"$ {' '.join(args)}\n")
        self.after(0, lambda: self._stop_btn.configure(state="normal"))

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                self._running_proc = proc
                for line in proc.stdout:
                    self._output_queue.put(line)
                proc.wait()
                rc = proc.returncode
                self._running_proc = None
                tag = "[exit 0]" if rc == 0 else f"[exit {rc}]"
                self._output_queue.put(f"{tag}\n\n")
                self.after(0, lambda: self._stop_btn.configure(state="disabled"))
                self.after(0, lambda: self._set_status(
                    f"✔ Done ({label})" if rc == 0
                    else f"✖ Failed ({label}, exit {rc})"))
                if rc == 0 and on_done:
                    self.after(0, on_done)
            except FileNotFoundError:
                self._running_proc = None
                self._output_queue.put(
                    "[ERROR] mpremote not found. Install: pip install mpremote\n")
                self.after(0, lambda: self._stop_btn.configure(state="disabled"))
                self.after(0, lambda: self._set_status("Error: mpremote not found"))
            except Exception as exc:
                self._running_proc = None
                self._output_queue.put(f"[ERROR] {exc}\n")
                self.after(0, lambda: self._stop_btn.configure(state="disabled"))
                self.after(0, lambda: self._set_status(f"Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _run_callable_bg(self, func, label: str = "", on_done=None) -> None:
        """Run a zero-arg callable in a background thread.

        The callable should return an ``int`` exit code.  This is used for
        operations that go through the ``commands`` module instead of raw
        subprocess invocations.
        """
        self._set_status(f"Running: {label}")
        self.after(0, lambda: self._stop_btn.configure(state="normal"))

        def worker() -> None:
            try:
                rc = func()
                tag = "[exit 0]" if rc == 0 else f"[exit {rc}]"
                self._output_queue.put(f"{tag}\n\n")
                self.after(0, lambda: self._stop_btn.configure(state="disabled"))
                self.after(0, lambda: self._set_status(
                    f"✔ Done ({label})" if rc == 0
                    else f"✖ Failed ({label}, exit {rc})"))
                if rc == 0 and on_done:
                    self.after(0, on_done)
            except Exception as exc:
                self._output_queue.put(f"[ERROR] {exc}\n")
                self.after(0, lambda: self._stop_btn.configure(state="disabled"))
                self.after(0, lambda: self._set_status(f"Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    # ==================================================================
    # Device management
    # ==================================================================

    def _refresh_devices(self) -> None:
        self._set_status("Detecting devices…")

        def worker() -> None:
            try:
                devs = list_devices()
            except Exception:
                devs = []

            def update() -> None:
                if devs:
                    values = [f"{p}  —  {d}" for p, d in devs]
                    self._device_combo.configure(values=values)
                    self._device_combo.set(values[0])
                    self._set_status(f"Found {len(devs)} device(s)")
                else:
                    self._device_combo.configure(values=["(none)"])
                    self._device_combo.set("(none)")
                    self._set_status("No MicroPython devices found")

            self.after(0, update)

        threading.Thread(target=worker, daemon=True).start()

    def _on_device_selected(self, value: str) -> None:
        port = value.split()[0] if value and value != "(none)" else None
        self._port = port

    def _get_port(self) -> Optional[str]:
        val = self._device_var.get()
        if val and val != "(none)":
            return val.split()[0]
        return self._port

    def _toggle_connect(self) -> None:
        port = self._get_port()
        if not port or port == "(none)":
            messagebox.showwarning("No Device", "Select a device first.")
            return
        self._port = port
        self._port_label_var.set(f"● Connected: {port}")
        self._connect_btn.configure(text="Connected ✔", fg_color="#1b5e20")
        self._dot_label.configure(text_color=_TAG_DOT_ON)
        self._set_status(f"Connected to {port}")
        self._refresh_pico_files()

    def _require_port(self) -> Optional[str]:
        port = self._get_port()
        if not port:
            messagebox.showwarning("Not Connected", "Connect to a device first.")
            return None
        return port

    # ==================================================================
    # Local file browser
    # ==================================================================

    def _browse_local(self) -> None:
        d = filedialog.askdirectory(initialdir=self._local_dir)
        if d:
            self._local_dir = d
            self._local_dir_var.set(d)
            self._refresh_local_files()

    def _navigate_up_local(self) -> None:
        parent = os.path.dirname(self._local_dir)
        if parent != self._local_dir:
            self._local_dir = parent
            self._local_dir_var.set(parent)
            self._refresh_local_files()

    def _refresh_local_files(self) -> None:
        for w in self._local_frame.winfo_children():
            w.destroy()
        self._local_btn_map = {}
        self._local_selected = None
        self._local_selected_is_dir = False

        try:
            raw = os.listdir(self._local_dir)
        except OSError:
            raw = []

        dirs = sorted(
            [n for n in raw if os.path.isdir(os.path.join(self._local_dir, n))],
            key=str.lower,
        )
        files = sorted(
            [n for n in raw if not os.path.isdir(os.path.join(self._local_dir, n))],
            key=str.lower,
        )

        # Folders: single-click selects, double-click navigates in
        for name in dirs:
            btn = ctk.CTkButton(
                self._local_frame, text=f"📁 {name}", anchor="w",
                fg_color=_NORMAL_BG, hover_color="#21262d", font=MONO_FONT_SMALL,
                command=lambda n=name: self._select_local(n, is_dir=True),
            )
            btn.grid(sticky="ew", padx=2, pady=1)
            btn.bind(
                "<Double-Button-1>",
                lambda _, n=name: self._enter_local_dir(n),
            )
            self._local_btn_map[name] = btn

        # Files
        for name in files:
            full = os.path.join(self._local_dir, name)
            try:
                size = os.path.getsize(full)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
            except OSError:
                size_str = "?"
            btn = ctk.CTkButton(
                self._local_frame,
                text=f"📄 {name}  ({size_str})",
                anchor="w",
                fg_color=_NORMAL_BG, hover_color="#21262d", font=MONO_FONT_SMALL,
                command=lambda n=name: self._select_local(n, is_dir=False),
            )
            btn.grid(sticky="ew", padx=2, pady=1)
            self._local_btn_map[name] = btn

    def _enter_local_dir(self, name: str) -> None:
        new_dir = os.path.join(self._local_dir, name)
        if os.path.isdir(new_dir):
            self._local_dir = new_dir
            self._local_dir_var.set(new_dir)
            self._refresh_local_files()

    def _select_local(self, name: str, is_dir: bool = False) -> None:
        if self._local_selected and self._local_selected in self._local_btn_map:
            self._local_btn_map[self._local_selected].configure(fg_color=_NORMAL_BG)
        self._local_selected = name
        self._local_selected_is_dir = is_dir
        if name in self._local_btn_map:
            self._local_btn_map[name].configure(fg_color=_SELECTED_BG)
        kind = "folder" if is_dir else "file"
        self._set_status(f"Selected local {kind}: {name}")

    # ==================================================================
    # Pico file browser
    # ==================================================================

    def _refresh_pico_files(self) -> None:
        port = self._get_port()
        if not port:
            return
        for w in self._pico_frame.winfo_children():
            w.destroy()
        self._pico_btn_map = {}
        self._pico_selected = None

        ctk.CTkLabel(
            self._pico_frame, text="⏳ Refreshing…",
            font=("Segoe UI", 11), text_color="#888888",
        ).grid(sticky="w", padx=8, pady=4)
        self._set_status("Listing Pico files…")
        ls_path = ":" + self._pico_dir
        self._output_queue.put(f"$ mpremote ls {ls_path}\n")

        def worker() -> None:
            result = subprocess.run(
                ["mpremote", "connect", port, "ls", ls_path],
                capture_output=True, text=True,
            )
            output = result.stdout + result.stderr
            # Only keep lines whose first token is a number (file size),
            # filtering out any header lines like "ls /:".
            file_lines = []
            for ln in output.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                parts = ln.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    file_lines.append(ln)

            def update() -> None:
                for w in self._pico_frame.winfo_children():
                    w.destroy()
                self._pico_btn_map = {}
                self._pico_is_dir = {}

                if not file_lines:
                    ctk.CTkLabel(
                        self._pico_frame, text="(empty)",
                        font=("Segoe UI", 11), text_color="#666666",
                    ).grid(sticky="w", padx=8, pady=4)

                for line in file_lines:
                    parts = line.split(None, 1)
                    name = parts[1]
                    is_dir = name.endswith("/")
                    icon = "📁" if is_dir else "📄"
                    key = name.rstrip("/")
                    btn = ctk.CTkButton(
                        self._pico_frame, text=f"{icon} {name}", anchor="w",
                        fg_color=_NORMAL_BG, hover_color="#21262d",
                        font=MONO_FONT_SMALL,
                        command=lambda k=key: self._select_pico(k),
                    )
                    btn.grid(sticky="ew", padx=2, pady=1)
                    if is_dir:
                        btn.bind(
                            "<Double-Button-1>",
                            lambda _, k=key: self._enter_pico_dir(k),
                        )
                    self._pico_btn_map[key] = btn
                    self._pico_is_dir[key] = is_dir

                self._set_status(f"Pico files refreshed ({self._pico_dir})")
                self._output_queue.put(output + "\n")

            self.after(0, update)

        threading.Thread(target=worker, daemon=True).start()

    def _select_pico(self, name: str) -> None:
        if self._pico_selected and self._pico_selected in self._pico_btn_map:
            self._pico_btn_map[self._pico_selected].configure(fg_color=_NORMAL_BG)
        self._pico_selected = name.rstrip("/")
        if self._pico_selected in self._pico_btn_map:
            self._pico_btn_map[self._pico_selected].configure(fg_color=_SELECTED_BG)
        kind = "folder" if self._pico_is_dir.get(self._pico_selected) else "file"
        self._set_status(f"Selected Pico {kind}: {self._pico_dir}{name}")

    def _enter_pico_dir(self, name: str) -> None:
        """Navigate into a Pico subdirectory (double-click on folder)."""
        self._pico_dir = self._pico_dir.rstrip("/") + "/" + name + "/"
        self._pico_dir_var.set(self._pico_dir)
        self._refresh_pico_files()

    def _navigate_up_pico(self) -> None:
        """Go up one directory level in the Pico browser."""
        if self._pico_dir == "/":
            return
        parts = self._pico_dir.rstrip("/").split("/")
        parent = "/".join(parts[:-1]) or "/"
        if not parent.endswith("/"):
            parent += "/"
        self._pico_dir = parent
        self._pico_dir_var.set(self._pico_dir)
        self._refresh_pico_files()

    def _pico_full_path(self) -> str:
        """Return the full Pico path for the currently selected item."""
        base = self._pico_dir.rstrip("/")
        return f"{base}/{self._pico_selected}"

    # ==================================================================
    # File operations — PC → Pico
    # ==================================================================

    def _copy_folder_to_pico(
        self, port: str, src: str, name: str, label: str
    ) -> None:
        """Copy a local folder to the Pico under the current pico directory."""
        pico_dir = self._pico_dir  # capture before background thread runs
        src_path = src.rstrip("/")
        dest = ":" + pico_dir
        self._output_queue.put(
            f"$ mpremote connect {port} cp -r {src_path} {dest}\n"
        )

        def do_copy() -> int:
            result = subprocess.run(
                ["mpremote", "connect", port, "cp", "-r", src_path, dest],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if result.stdout:
                self._output_queue.put(result.stdout)
            return result.returncode

        self._run_callable_bg(do_copy, label, on_done=self._refresh_pico_files)

    def _copy_to_pico(self) -> None:
        """Copy selected local file or folder entirely to the Pico."""
        port = self._require_port()
        if not port:
            return
        name = self._local_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a local file or folder first.")
            return
        src = os.path.join(self._local_dir, name)
        if os.path.isdir(src):
            self._copy_folder_to_pico(port, src, name, f"copy {name}/ → Pico")
        else:
            dest = ":" + self._pico_dir.rstrip("/") + "/" + name
            args = ["mpremote", "connect", port, "cp", src, dest]
            self._run_cmd_bg(args, f"copy {name} → Pico", on_done=self._refresh_pico_files)

    def _copy_all_to_pico(self) -> None:
        """Copy all files and folders in the current local directory to the Pico."""
        port = self._require_port()
        if not port:
            return
        try:
            entries = os.listdir(self._local_dir)
        except OSError:
            messagebox.showerror("Error", f"Could not read folder: {self._local_dir}")
            return
        if not entries:
            messagebox.showinfo("Empty Folder", "The local folder is empty.")
            return
        if not messagebox.askyesno(
            "Copy All to Pico",
            f"Copy all files/folders from:\n{self._local_dir}\nto Pico:{self._pico_dir}?\n\n"
            f"({len(entries)} items)"
        ):
            return
        pico_dir = self._pico_dir
        port_snap = port
        entries_snap = list(entries)

        def do_copy_all() -> int:
            rc = 0
            for name in sorted(entries_snap):
                src = os.path.join(self._local_dir, name)
                if os.path.isdir(src):
                    dest = ":" + pico_dir
                    result = subprocess.run(
                        ["mpremote", "connect", port_snap, "cp", "-r", src.rstrip("/"), dest],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    )
                    if result.stdout:
                        self._output_queue.put(result.stdout)
                    if result.returncode != 0:
                        rc = result.returncode
                else:
                    dest = ":" + pico_dir.rstrip("/") + "/" + name
                    result = subprocess.run(
                        ["mpremote", "connect", port_snap, "cp", src, dest],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    )
                    if result.stdout:
                        self._output_queue.put(result.stdout)
                    if result.returncode != 0:
                        rc = result.returncode
            return rc

        self._output_queue.put(f"$ copy all from {self._local_dir} → Pico:{pico_dir}\n")
        self._run_callable_bg(do_copy_all, "copy all → Pico", on_done=self._refresh_pico_files)

    def _deploy(self) -> None:
        """Deploy selected local file or folder to the Pico."""
        port = self._require_port()
        if not port:
            return
        name = self._local_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a local file or folder first.")
            return
        src = os.path.join(self._local_dir, name)
        if os.path.isdir(src):
            self._copy_folder_to_pico(port, src, name, f"deploy {name}/")
        else:
            dest = ":" + self._pico_dir.rstrip("/") + "/" + name
            args = ["mpremote", "connect", port, "cp", src, dest]
            self._run_cmd_bg(args, f"deploy {name}", on_done=self._refresh_pico_files)

    # ==================================================================
    # File operations — Pico → PC
    # ==================================================================

    def _copy_from_pico(self) -> None:
        """Copy selected Pico file or folder into the current local dir."""
        port = self._require_port()
        if not port:
            return
        name = self._pico_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a Pico file from the list first.")
            return
        full_path = self._pico_full_path()
        dest_base = os.path.join(self._local_dir, os.path.basename(name))
        is_dir = self._pico_is_dir.get(name, False)

        if is_dir:
            self._output_queue.put(f"$ pull :{full_path}/ → {dest_base}/\n")
            self._run_callable_bg(
                lambda: commands.cmd_cp_dir_from_pico(port, full_path, dest_base),
                label=f"pull {name}/ → local",
                on_done=self._refresh_local_files,
            )
        else:
            args = ["mpremote", "connect", port, "cp", f":{full_path}", dest_base]
            self._run_cmd_bg(
                args, f"copy {name} → local", on_done=self._refresh_local_files)

    # ==================================================================
    # File operations — remove / mkdir / open
    # ==================================================================

    def _remove_pico_file(self) -> None:
        """Remove selected Pico file or directory (recursive for dirs)."""
        port = self._require_port()
        if not port:
            return
        name = self._pico_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a Pico file first.")
            return
        full_path = self._pico_full_path()
        is_dir = self._pico_is_dir.get(name, False)
        kind = "folder" if is_dir else "file"
        msg = f"Remove {full_path} ({kind}) from Pico?"
        if is_dir:
            msg += "\n\nThis will remove all contents recursively."
        if not messagebox.askyesno("Confirm Remove", msg):
            return

        if is_dir:
            self._output_queue.put(f"$ rm -r :{full_path}\n")
            self._run_callable_bg(
                lambda: commands._rm_recursive(port, full_path),
                label=f"rm -r {name}",
                on_done=self._refresh_pico_files,
            )
        else:
            args = ["mpremote", "connect", port, "rm", f":{full_path}"]
            self._run_cmd_bg(args, f"rm {name}", on_done=self._refresh_pico_files)

    def _mkdir_pico(self) -> None:
        port = self._require_port()
        if not port:
            return
        d = ctk.CTkInputDialog(text="Directory name:", title="Create Directory")
        name = d.get_input()
        if name:
            new_dir = self._pico_dir.rstrip("/") + "/" + name
            args = ["mpremote", "connect", port, "mkdir", f":{new_dir}"]
            self._run_cmd_bg(args, f"mkdir {name}", on_done=self._refresh_pico_files)

    def _delete_all_pico(self) -> None:
        """Recursively delete all files and folders in the current Pico directory."""
        port = self._require_port()
        if not port:
            return
        if not self._pico_btn_map:
            messagebox.showinfo("Empty", "No files on Pico to delete.")
            return
        entries = list(self._pico_btn_map.keys())
        if not messagebox.askyesno(
            "Delete All from Pico",
            f"PERMANENTLY delete all {len(entries)} items in Pico:{self._pico_dir}?\n\n"
            "This cannot be undone.",
        ):
            return
        pico_dir = self._pico_dir
        port_snap = port
        entries_snap = list(entries)

        def do_delete_all() -> int:
            rc = 0
            for name in entries_snap:
                full_path = pico_dir.rstrip("/") + "/" + name
                self._output_queue.put(f"$ rm -r :{full_path}\n")
                res = commands._rm_recursive(port_snap, full_path)
                if res != 0:
                    rc = res
            return rc

        self._run_callable_bg(do_delete_all, "delete all from Pico", on_done=self._refresh_pico_files)

    def _open_pico_file(self) -> None:
        """Download a Pico file and open it in the code editor."""
        port = self._require_port()
        if not port:
            return
        name = self._pico_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a Pico file from the list first.")
            return
        if self._pico_is_dir.get(name):
            messagebox.showwarning(
                "Not a File", "Cannot open a directory in the editor.\n"
                "Select a file instead.")
            return

        full_path = self._pico_full_path()
        safe_basename = os.path.basename(full_path)
        if not safe_basename or safe_basename in (".", ".."):
            messagebox.showerror("Invalid Name", f"Cannot open: {full_path!r}")
            return

        self._set_status(f"Downloading {full_path} from Pico…")

        def do_open() -> None:
            suffix = os.path.splitext(safe_basename)[1] or ".py"
            try:
                tf = tempfile.NamedTemporaryFile(
                    mode="wb", suffix=suffix, prefix="picosync_", delete=False)
                tmp_path = tf.name
                tf.close()
            except OSError as exc:
                self.after(0, lambda: messagebox.showerror(
                    "Open Failed", f"Could not create temp file:\n{exc}"))
                return

            result = subprocess.run(
                ["mpremote", "connect", port, "cp", f":{full_path}", tmp_path],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self._tmp_files.append(tmp_path)

                def load() -> None:
                    try:
                        with open(tmp_path, "r", encoding="utf-8",
                                  errors="replace") as fh:
                            content = fh.read()
                        self._editor_file = tmp_path
                        self._pico_editor_path = full_path
                        self._editor_file_var.set(f"[Pico] {full_path}")
                        self._editor.configure(state="normal")
                        self._editor.delete("1.0", "end")
                        self._editor.insert("1.0", content)
                        self._set_status(f"Opened Pico file: {full_path}")
                    except Exception as exc:
                        messagebox.showerror(
                            "Open Failed", f"Could not read {name}:\n{exc}")
                self.after(0, load)
            else:
                err = (result.stderr or result.stdout or "Unknown error").strip()
                self.after(0, lambda: messagebox.showerror(
                    "Open Failed", f"Could not download {name}:\n{err}"))

        threading.Thread(target=do_open, daemon=True).start()

    # ==================================================================
    # Hashing
    # ==================================================================

    def _hash_local_file(self) -> None:
        name = self._local_selected
        if not name:
            messagebox.showwarning("No File Selected", "Select a local file first.")
            return
        path = os.path.join(self._local_dir, name)
        if os.path.isdir(path):
            messagebox.showwarning(
                "Not a File", "Hash is only supported for files, not folders.")
            return
        self._set_status(f"Hashing {name}…")

        def worker() -> None:
            digest = commands.local_file_hash(path)
            if digest is None:
                self._output_queue.put(f"[ERROR] Could not hash: {path}\n")
                self.after(0, lambda: self._set_status(f"Hash failed: {name}"))
            else:
                self._output_queue.put(f"[hash] local  md5: {digest}  {path}\n")
                self.after(0, lambda: self._set_status(f"md5: {digest}"))

        threading.Thread(target=worker, daemon=True).start()

    def _hash_pico_file(self) -> None:
        port = self._require_port()
        if not port:
            return
        name = self._pico_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a Pico file from the list first.")
            return
        if self._pico_is_dir.get(name):
            messagebox.showwarning(
                "Not a File", "Hash is only supported for files, not folders.")
            return
        full_path = self._pico_full_path()
        self._set_status(f"Hashing Pico:{full_path}…")
        self._output_queue.put(f"$ hash pico:{full_path}\n")

        def worker() -> None:
            digest = commands.remote_file_hash(port, full_path)
            if digest is None:
                self._output_queue.put(
                    f"[ERROR] Could not hash Pico file: {full_path}\n")
                self.after(0, lambda: self._set_status(f"Hash failed: {name}"))
            else:
                self._output_queue.put(
                    f"[hash] remote md5: {digest}  :{full_path}\n")
                self.after(0, lambda: self._set_status(f"md5: {digest}"))

        threading.Thread(target=worker, daemon=True).start()

    # ==================================================================
    # Terminal exec
    # ==================================================================

    def _exec_snippet(self) -> None:
        port = self._require_port()
        if not port:
            return
        code = self._exec_entry.get().strip()
        if not code:
            return
        self._exec_entry.delete(0, "end")
        args = ["mpremote", "connect", port, "exec", code]
        self._run_cmd_bg(args, "exec")

    # ==================================================================
    # Editor operations
    # ==================================================================

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=self._local_dir,
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
        )
        if path:
            self._editor_file = path
            self._pico_editor_path = None
            self._editor_file_var.set(path)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self._editor.configure(state="normal")
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", content)

    def _open_local_file(self) -> None:
        """Open the selected local file in the code editor."""
        name = self._local_selected
        if not name:
            messagebox.showwarning(
                "No File Selected", "Select a local file first.")
            return
        path = os.path.join(self._local_dir, name)
        if os.path.isdir(path):
            messagebox.showwarning(
                "Not a File",
                "Cannot open a directory in the editor.\nSelect a file instead.")
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            messagebox.showerror("Open Failed", f"Could not open {name}:\n{exc}")
            return
        self._editor_file = path
        self._pico_editor_path = None
        self._editor_file_var.set(path)
        self._editor.configure(state="normal")
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", content)
        self._set_status(f"Opened: {name}")

    def _save_to_pico(self) -> None:
        """Save the current editor content directly to the Pico."""
        port = self._require_port()
        if not port:
            return
        path = getattr(self, "_editor_file", None)
        if not path or path == "(no file)":
            messagebox.showwarning("No File", "Open or save a file first.")
            return
        # Write content to the local path (temp file or real file) so mpremote
        # has an up-to-date file to upload. Bypass _save_file to avoid the
        # "save to PC" dialog when editing a Pico temp file.
        content = self._editor.get("1.0", "end-1c")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            messagebox.showerror("Write Failed", f"Could not write file:\n{exc}")
            return
        if self._pico_editor_path:
            # File was opened from Pico — push back to the original path
            dest = f":/{self._pico_editor_path}"
            label = f"save to Pico: /{self._pico_editor_path}"
        else:
            # Local file — upload with same basename to Pico root
            basename = os.path.basename(path)
            dest = f":{basename}"
            label = f"save to Pico: {basename}"
        args = ["mpremote", "connect", port, "cp", path, dest]
        self._run_cmd_bg(args, label, on_done=self._refresh_pico_files)

    def _save_file(self) -> None:
        """Save editor content to disk (PC).

        When editing a Pico file opened via 'Open in Editor', the temp path
        is used internally, but 'Save to PC' prompts for a real PC location.
        """
        path = getattr(self, "_editor_file", None)
        # If the current file is a Pico temp file, prompt for a real PC location
        if self._pico_editor_path and path and path.startswith(
                tempfile.gettempdir()):
            suggested = os.path.basename(self._pico_editor_path)
            new_path = filedialog.asksaveasfilename(
                initialfile=suggested,
                defaultextension=".py",
                filetypes=[("Python files", "*.py"), ("All files", "*.*")],
                title="Save to PC",
            )
            if not new_path:
                return
            path = new_path
            self._editor_file = path
            self._pico_editor_path = None  # now a local file
            self._editor_file_var.set(path)
        elif not path or path == "(no file)":
            path = filedialog.asksaveasfilename(
                defaultextension=".py",
                filetypes=[("Python files", "*.py"), ("All files", "*.*")],
            )
            if not path:
                return
            self._editor_file = path
            self._editor_file_var.set(path)
        content = self._editor.get("1.0", "end-1c")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self._set_status(f"Saved: {path}")

    def _save_editor_silent(self) -> bool:
        """Write editor content to *_editor_file* without any dialog.

        Returns True on success.  For a Pico temp file this saves to the
        temp path (so mpremote can read it); for a local file it saves in
        place.  Use this instead of ``_save_file()`` when the caller does
        not want a 'Save to PC' prompt.
        """
        path = getattr(self, "_editor_file", None)
        if not path or path == "(no file)":
            messagebox.showwarning("No File", "Open or save a file first.")
            return False
        content = self._editor.get("1.0", "end-1c")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            messagebox.showerror("Save Failed", f"Could not save file:\n{exc}")
            return False
        return True

    def _run_on_pico(self) -> None:
        port = self._require_port()
        if not port:
            return
        path = getattr(self, "_editor_file", None)
        if not path or path == "(no file)":
            messagebox.showwarning("No File", "Open or save a file first.")
            return
        if not self._save_editor_silent():
            return
        args = ["mpremote", "connect", port, "run", path]
        self._run_cmd_bg(args, f"run {os.path.basename(path)}")

    def _exec_editor_code(self) -> None:
        port = self._require_port()
        if not port:
            return
        try:
            code = self._editor.get("sel.first", "sel.last")
        except tk.TclError:
            code = self._editor.get("1.0", "end-1c")
        if not code.strip():
            return
        args = ["mpremote", "connect", port, "exec", code]
        self._run_cmd_bg(args, "exec snippet")

    def _reset_pico(self) -> None:
        port = self._require_port()
        if not port:
            return
        args = ["mpremote", "connect", port, "reset"]
        self._run_cmd_bg(args, "reset")

    def _deploy_and_run(self) -> None:
        port = self._require_port()
        if not port:
            return
        path = getattr(self, "_editor_file", None)
        if not path or path == "(no file)":
            messagebox.showwarning("No File", "Open or save a file first.")
            return
        if not self._save_editor_silent():
            return
        name = os.path.basename(path)
        dest = f":{name}"
        self.after(0, lambda: self._stop_btn.configure(state="normal"))

        def do_deploy_then_run() -> None:
            try:
                self._output_queue.put(
                    f"$ mpremote connect {port} cp {path} {dest}\n")
                proc = subprocess.Popen(
                    ["mpremote", "connect", port, "cp", path, dest],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                self._running_proc = proc
                for line in proc.stdout:
                    self._output_queue.put(line)
                proc.wait()

                if proc.returncode == 0:
                    self._output_queue.put(
                        f"$ mpremote connect {port} run {path}\n")
                    proc2 = subprocess.Popen(
                        ["mpremote", "connect", port, "run", path],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True,
                    )
                    self._running_proc = proc2
                    for line in proc2.stdout:
                        self._output_queue.put(line)
                    proc2.wait()
                    self._running_proc = None
                    self.after(0, lambda: self._set_status(
                        f"✔ Deploy+Run complete ({name})"))
                else:
                    self._running_proc = None
                    self.after(0, lambda: self._set_status(
                        f"✖ Deploy failed ({name})"))
            except Exception as exc:
                self._running_proc = None
                self._output_queue.put(f"[ERROR] {exc}\n")
                self.after(0, lambda: self._set_status(f"Error: {exc}"))
            finally:
                self.after(0, lambda: self._stop_btn.configure(state="disabled"))

        self._set_status(f"Deploying and running {name}…")
        threading.Thread(target=do_deploy_then_run, daemon=True).start()

    # ==================================================================
    # Misc actions
    # ==================================================================

    def _stop_running(self) -> None:
        proc = self._running_proc
        if proc and proc.poll() is None:
            proc.terminate()
            self._output_queue.put("[INFO] Stopped by user\n\n")
            self._set_status("⏹ Process stopped by user")
        self._stop_btn.configure(state="disabled")

    def _copy_log(self) -> None:
        content = self._terminal.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        self._set_status("Terminal log copied to clipboard")

    def _save_log(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Terminal Log",
        )
        if not path:
            return
        content = self._terminal.get("1.0", "end-1c")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self._set_status(f"Log saved: {path}")

    def _open_repl(self) -> None:
        """Open an interactive REPL in a new terminal window."""
        port = self._require_port()
        if not port:
            return
        cmd = ["mpremote", "connect", port, "repl"]
        try:
            if sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "cmd", "/k"] + cmd)
            elif sys.platform == "darwin":
                # Use single-quoted shell args — safe inside the AppleScript double-quoted string
                shell_cmd = " ".join(shlex.quote(c) for c in cmd)
                subprocess.Popen([
                    "osascript", "-e",
                    f'tell application "Terminal" to do script "{shell_cmd}"',
                ])
            else:
                for term in ("x-terminal-emulator", "gnome-terminal", "xterm"):
                    try:
                        subprocess.Popen([term, "--"] + cmd)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    messagebox.showinfo(
                        "Open REPL",
                        f"Run this in a terminal:\n\n  {' '.join(cmd)}")
                    return
            self._set_status(f"REPL opened in new terminal ({port})")
        except Exception as exc:
            messagebox.showerror("Open REPL Failed", str(exc))


# ===================================================================
# Entry point
# ===================================================================

def launch() -> None:
    """Launch the pico-sync GUI."""
    app = PicoSyncApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
