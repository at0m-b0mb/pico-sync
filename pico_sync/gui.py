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
# Theme — GitHub-dark inspired palette
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Fonts
if sys.platform == "win32":
    MONO_FONT = ("Cascadia Code", 13)
    MONO_FONT_SMALL = ("Cascadia Code", 11)
    UI_FONT = ("Segoe UI", 12)
    UI_FONT_BOLD = ("Segoe UI", 13, "bold")
    UI_FONT_LG = ("Segoe UI", 15, "bold")
    UI_FONT_SM = ("Segoe UI", 11)
elif sys.platform == "darwin":
    MONO_FONT = ("SF Mono", 13)
    MONO_FONT_SMALL = ("SF Mono", 11)
    UI_FONT = ("SF Pro Text", 12)
    UI_FONT_BOLD = ("SF Pro Text", 13, "bold")
    UI_FONT_LG = ("SF Pro Display", 15, "bold")
    UI_FONT_SM = ("SF Pro Text", 11)
else:
    MONO_FONT = ("DejaVu Sans Mono", 12)
    MONO_FONT_SMALL = ("DejaVu Sans Mono", 11)
    UI_FONT = ("DejaVu Sans", 11)
    UI_FONT_BOLD = ("DejaVu Sans", 12, "bold")
    UI_FONT_LG = ("DejaVu Sans", 14, "bold")
    UI_FONT_SM = ("DejaVu Sans", 10)

# Palette
COL_BG = "#0d1117"           # app background
COL_BG_ALT = "#161b22"       # panels / cards
COL_BG_HOVER = "#21262d"     # hover backgrounds
COL_BORDER = "#30363d"
COL_TEXT = "#c9d1d9"
COL_TEXT_DIM = "#8b949e"
COL_MUTED = "#6e7681"

# Accent colours (button family)
COL_BLUE = "#1f6feb"
COL_BLUE_HV = "#388bfd"
COL_GREEN = "#238636"
COL_GREEN_HV = "#2ea043"
COL_RED = "#da3633"
COL_RED_HV = "#f85149"
COL_ORANGE = "#bd5d00"
COL_ORANGE_HV = "#db6d28"
COL_PURPLE = "#8957e5"
COL_PURPLE_HV = "#a371f7"
COL_SLATE = "#2d333b"
COL_SLATE_HV = "#3a414b"

# Selection / state
_SELECTED_BG = "#1f6feb"
_NORMAL_BG = "transparent"

# Terminal / syntax tags
_TAG_CMD = "#79c0ff"
_TAG_ERROR = "#f85149"
_TAG_SUCCESS = "#3fb950"
_TAG_WARN = "#d29922"
_TAG_DOT_OFF = "#484f58"
_TAG_DOT_ON = "#3fb950"

# Python syntax colours
SYN_KEYWORD = "#ff7b72"      # red-pink
SYN_BUILTIN = "#79c0ff"      # blue
SYN_STRING = "#a5d6ff"       # light blue
SYN_COMMENT = "#8b949e"      # grey
SYN_NUMBER = "#79c0ff"
SYN_DECORATOR = "#d2a8ff"    # purple
SYN_DEF_NAME = "#d2a8ff"

PY_KEYWORDS = (
    "False None True and as assert async await break class continue def del "
    "elif else except finally for from global if import in is lambda nonlocal "
    "not or pass raise return try while with yield match case"
).split()

PY_BUILTINS = (
    "print len range str int float bool list dict tuple set frozenset bytes "
    "bytearray abs all any ascii bin chr dir divmod enumerate eval exec "
    "filter format getattr hasattr hash help hex id input isinstance "
    "issubclass iter map max min next object oct open ord pow repr reversed "
    "round setattr slice sorted staticmethod sum super type vars zip "
    "classmethod property __init__ __name__ self cls"
).split()


# ===================================================================
# Tooltip helper
# ===================================================================

class Tooltip:
    """Lightweight tooltip shown after a short hover delay."""

    def __init__(self, widget, text: str, delay: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add=True)
        widget.bind("<Leave>", self._hide, add=True)
        widget.bind("<ButtonPress>", self._hide, add=True)

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tip.configure(bg=COL_BORDER)
        lbl = tk.Label(
            tip, text=self.text, justify="left",
            background="#1c2128", foreground=COL_TEXT,
            relief="flat", borderwidth=0, font=UI_FONT_SM,
            padx=8, pady=4,
        )
        lbl.pack(padx=1, pady=1)
        self._tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


# ===================================================================
# Line number gutter for the code editor
# ===================================================================

class LineNumbers(tk.Canvas):
    """Render line numbers next to a tk.Text widget."""

    def __init__(self, parent, textwidget: tk.Text, **kwargs) -> None:
        super().__init__(
            parent, width=44, bg=COL_BG_ALT,
            highlightthickness=0, bd=0, **kwargs,
        )
        self.textwidget = textwidget
        self._font = MONO_FONT

    def redraw(self, *_args) -> None:
        self.delete("all")
        i = self.textwidget.index("@0,0")
        while True:
            dline = self.textwidget.dlineinfo(i)
            if dline is None:
                break
            y = dline[1]
            linenum = str(i).split(".")[0]
            self.create_text(
                36, y, anchor="ne", text=linenum,
                fill=COL_MUTED, font=self._font,
            )
            i = self.textwidget.index(f"{i}+1line")


# ===================================================================
# Python syntax highlighter (regex-based)
# ===================================================================

import re as _re

_RE_COMMENT = _re.compile(r"#[^\n]*")
_RE_STRING = _re.compile(
    r"(?P<q>['\"])(?:\\.|(?!(?P=q)).)*(?P=q)"
)
_RE_TRIPLE = _re.compile(r"('''.*?'''|\"\"\".*?\"\"\")", _re.DOTALL)
_RE_KEYWORD = _re.compile(r"\b(" + "|".join(PY_KEYWORDS) + r")\b")
_RE_BUILTIN = _re.compile(r"\b(" + "|".join(PY_BUILTINS) + r")\b")
_RE_NUMBER = _re.compile(r"\b(\d+\.?\d*|\.\d+|0x[0-9a-fA-F]+|0b[01]+)\b")
_RE_DECORATOR = _re.compile(r"^[ \t]*@[\w\.]+", _re.MULTILINE)
_RE_DEFNAME = _re.compile(r"\b(?:def|class)\s+(\w+)")


def apply_python_syntax(text: tk.Text) -> None:
    """Re-tag the entire contents of *text* with Python syntax highlights."""
    for tag in ("kw", "bi", "str", "cmt", "num", "dec", "defn"):
        text.tag_remove(tag, "1.0", "end")
    source = text.get("1.0", "end-1c")

    def add(pattern, tag, source_text=source):
        for m in pattern.finditer(source_text):
            start = f"1.0 + {m.start()} chars"
            end = f"1.0 + {m.end()} chars"
            text.tag_add(tag, start, end)

    # Order matters: comments and strings first, then we re-tag inside? No —
    # we tag everything in order, but the visible tag is whichever was added
    # last. So: numbers/keywords/builtins first, then strings (which override),
    # then comments (which override all).
    add(_RE_NUMBER, "num")
    add(_RE_BUILTIN, "bi")
    add(_RE_KEYWORD, "kw")
    add(_RE_DECORATOR, "dec")
    for m in _RE_DEFNAME.finditer(source):
        start = f"1.0 + {m.start(1)} chars"
        end = f"1.0 + {m.end(1)} chars"
        text.tag_add("defn", start, end)
    add(_RE_TRIPLE, "str")
    add(_RE_STRING, "str")
    add(_RE_COMMENT, "cmt")


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
        self.geometry("1480x920")
        self.minsize(1100, 720)
        self.configure(fg_color=COL_BG)

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
        self._line_numbers: Optional[LineNumbers] = None
        self._syntax_after_id: Optional[str] = None

        self._build_ui()
        self._bind_shortcuts()
        self._poll_output_queue()
        self._refresh_devices()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        mod = "Command" if sys.platform == "darwin" else "Control"
        bindings = {
            f"<{mod}-s>": lambda _e: (self._save_file(), "break"),
            f"<{mod}-S>": lambda _e: (self._save_to_pico(), "break"),
            f"<{mod}-r>": lambda _e: (self._run_on_pico(), "break"),
            f"<{mod}-d>": lambda _e: (self._deploy_and_run(), "break"),
            f"<{mod}-o>": lambda _e: (self._open_file(), "break"),
            f"<{mod}-e>": lambda _e: (self._exec_editor_code(), "break"),
            f"<{mod}-k>": lambda _e: (self._terminal_clear(), "break"),
            f"<{mod}-l>": lambda _e: (self._exec_entry.focus_set(), "break"),
            f"<{mod}-Return>": lambda _e: (self._deploy_and_run(), "break"),
        }
        for seq, fn in bindings.items():
            self.bind_all(seq, fn)

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
        self.grid_columnconfigure(0, weight=1)

        self._build_top_bar()
        self._build_main_pane()
        self._build_status_bar()

    # -- Helper: themed button with tooltip -----------------------------

    def _mk_btn(self, parent, text, cmd, fg, hv, tip=None, **kwargs):
        btn = ctk.CTkButton(
            parent, text=text, command=cmd,
            fg_color=fg, hover_color=hv,
            font=UI_FONT, **kwargs,
        )
        if tip:
            Tooltip(btn, tip)
        return btn

    # -- Top bar --------------------------------------------------------

    def _build_top_bar(self) -> None:
        bar = ctk.CTkFrame(
            self, corner_radius=0, height=60,
            fg_color=COL_BG_ALT, border_width=0,
        )
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(
            bar, text="🔌  pico-sync", font=UI_FONT_LG,
            text_color=COL_TEXT,
        ).grid(row=0, column=0, padx=(20, 6), pady=14, sticky="w")

        self._dot_label = ctk.CTkLabel(
            bar, text="●", font=("Helvetica", 16),
            text_color=_TAG_DOT_OFF,
        )
        self._dot_label.grid(row=0, column=1, padx=(8, 16))

        ctk.CTkLabel(
            bar, text="Device", font=UI_FONT, text_color=COL_TEXT_DIM,
        ).grid(row=0, column=2, padx=(0, 8))

        self._device_var = ctk.StringVar(value="(none)")
        self._device_combo = ctk.CTkComboBox(
            bar, variable=self._device_var, values=["(none)"], width=280,
            command=self._on_device_selected, font=UI_FONT,
            fg_color=COL_BG, border_color=COL_BORDER,
            button_color=COL_SLATE, button_hover_color=COL_SLATE_HV,
            dropdown_font=UI_FONT, dropdown_fg_color=COL_BG_ALT,
        )
        self._device_combo.grid(row=0, column=3, padx=4)

        detect = ctk.CTkButton(
            bar, text="🔍  Detect", width=110, font=UI_FONT,
            fg_color=COL_SLATE, hover_color=COL_SLATE_HV,
            command=self._refresh_devices,
        )
        detect.grid(row=0, column=4, padx=6)
        Tooltip(detect, "Scan USB ports for MicroPython devices")

        self._connect_btn = ctk.CTkButton(
            bar, text="Connect", width=140, font=UI_FONT_BOLD,
            fg_color=COL_GREEN, hover_color=COL_GREEN_HV,
            command=self._toggle_connect,
        )
        self._connect_btn.grid(row=0, column=5, padx=(6, 20), sticky="e")
        Tooltip(self._connect_btn, "Connect to the selected device")

    # -- Main pane: sidebar | (editor / terminal) -----------------------

    def _build_main_pane(self) -> None:
        main = tk.PanedWindow(
            self, orient="horizontal", sashwidth=5, sashrelief="flat",
            bg=COL_BG, bd=0, sashpad=0,
        )
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(8, 6))

        sidebar = ctk.CTkFrame(main, corner_radius=8, fg_color=COL_BG_ALT)
        self._build_sidebar(sidebar)
        main.add(sidebar, minsize=280, width=340, stretch="never")

        right = tk.PanedWindow(
            main, orient="vertical", sashwidth=5, sashrelief="flat",
            bg=COL_BG, bd=0, sashpad=0,
        )
        main.add(right, minsize=620, stretch="always")

        editor_pane = ctk.CTkFrame(right, corner_radius=8, fg_color=COL_BG_ALT)
        self._build_editor_pane(editor_pane)
        right.add(editor_pane, minsize=240, height=560, stretch="always")

        term_pane = ctk.CTkFrame(right, corner_radius=8, fg_color=COL_BG_ALT)
        self._build_terminal(term_pane)
        right.add(term_pane, minsize=120, height=240, stretch="always")

    # -- Sidebar (tabbed file browsers) ---------------------------------

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        tabs = ctk.CTkTabview(
            parent, fg_color=COL_BG_ALT,
            segmented_button_fg_color=COL_BG,
            segmented_button_selected_color=COL_BLUE,
            segmented_button_selected_hover_color=COL_BLUE_HV,
            segmented_button_unselected_color=COL_SLATE,
            segmented_button_unselected_hover_color=COL_SLATE_HV,
            text_color=COL_TEXT,
        )
        tabs.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4, 6))

        local_tab = tabs.add("📁  Local")
        pico_tab = tabs.add("🤖  Pico")

        self._build_local_panel(local_tab)
        self._build_pico_panel(pico_tab)

    def _build_local_panel(self, parent) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # Path bar
        path_row = ctk.CTkFrame(parent, fg_color="transparent")
        path_row.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        path_row.grid_columnconfigure(0, weight=1)
        self._local_dir_var = ctk.StringVar(value=self._local_dir)
        ctk.CTkEntry(
            path_row, textvariable=self._local_dir_var,
            state="readonly", font=MONO_FONT_SMALL,
            fg_color=COL_BG, border_color=COL_BORDER,
            text_color=COL_TEXT_DIM,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        up = ctk.CTkButton(
            path_row, text="⬆", width=32, font=UI_FONT_BOLD,
            fg_color=COL_SLATE, hover_color=COL_SLATE_HV,
            command=self._navigate_up_local,
        )
        up.grid(row=0, column=1, padx=(0, 2))
        Tooltip(up, "Go up one folder")
        browse = ctk.CTkButton(
            path_row, text="…", width=32, font=UI_FONT_BOLD,
            fg_color=COL_SLATE, hover_color=COL_SLATE_HV,
            command=self._browse_local,
        )
        browse.grid(row=0, column=2)
        Tooltip(browse, "Browse for folder")

        # File list
        self._local_frame = ctk.CTkScrollableFrame(
            parent, fg_color=COL_BG,
            scrollbar_button_color=COL_SLATE,
            scrollbar_button_hover_color=COL_SLATE_HV,
        )
        self._local_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        self._local_frame.grid_columnconfigure(0, weight=1)
        self._refresh_local_files()

        # Buttons — 2-col grid
        btns = ctk.CTkFrame(parent, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=4, pady=(4, 4))
        btns.grid_columnconfigure((0, 1), weight=1, uniform="lbtn")

        self._mk_btn(btns, "📝  Open", self._open_local_file,
                     COL_SLATE, COL_SLATE_HV,
                     "Open selected file in the editor").grid(
                         row=0, column=0, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🔍  Hash", self._hash_local_file,
                     COL_SLATE, COL_SLATE_HV,
                     "MD5 hash of selected file").grid(
                         row=0, column=1, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "📤  Push", self._copy_to_pico,
                     COL_BLUE, COL_BLUE_HV,
                     "Copy selected file/folder to Pico").grid(
                         row=1, column=0, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "📤  Push All", self._copy_all_to_pico,
                     COL_BLUE, COL_BLUE_HV,
                     "Copy every item in the local folder to Pico").grid(
                         row=1, column=1, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🚀  Deploy", self._deploy,
                     COL_GREEN, COL_GREEN_HV,
                     "Deploy selected file/folder to Pico").grid(
                         row=2, column=0, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🔄  Refresh", self._refresh_local_files,
                     COL_SLATE, COL_SLATE_HV,
                     "Reload local file list").grid(
                         row=2, column=1, padx=2, pady=2, sticky="ew")

    def _build_pico_panel(self, parent) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        path_row = ctk.CTkFrame(parent, fg_color="transparent")
        path_row.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        path_row.grid_columnconfigure(0, weight=1)
        self._pico_dir_var = ctk.StringVar(value="/")
        ctk.CTkEntry(
            path_row, textvariable=self._pico_dir_var,
            state="readonly", font=MONO_FONT_SMALL,
            fg_color=COL_BG, border_color=COL_BORDER,
            text_color=COL_TEXT_DIM,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        up = ctk.CTkButton(
            path_row, text="⬆", width=32, font=UI_FONT_BOLD,
            fg_color=COL_SLATE, hover_color=COL_SLATE_HV,
            command=self._navigate_up_pico,
        )
        up.grid(row=0, column=1)
        Tooltip(up, "Go up one folder")

        self._pico_frame = ctk.CTkScrollableFrame(
            parent, fg_color=COL_BG,
            scrollbar_button_color=COL_SLATE,
            scrollbar_button_hover_color=COL_SLATE_HV,
        )
        self._pico_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        self._pico_frame.grid_columnconfigure(0, weight=1)

        btns = ctk.CTkFrame(parent, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=4, pady=(4, 4))
        btns.grid_columnconfigure((0, 1), weight=1, uniform="pbtn")

        self._mk_btn(btns, "📝  Open", self._open_pico_file,
                     COL_SLATE, COL_SLATE_HV,
                     "Open selected Pico file in editor").grid(
                         row=0, column=0, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🔍  Hash", self._hash_pico_file,
                     COL_SLATE, COL_SLATE_HV,
                     "MD5 hash of selected Pico file").grid(
                         row=0, column=1, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "⬇  Pull", self._copy_from_pico,
                     COL_BLUE, COL_BLUE_HV,
                     "Copy selected Pico file/folder to local").grid(
                         row=1, column=0, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "📂  MkDir", self._mkdir_pico,
                     COL_SLATE, COL_SLATE_HV,
                     "Create a new directory on Pico").grid(
                         row=1, column=1, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🗑  Remove", self._remove_pico_file,
                     COL_RED, COL_RED_HV,
                     "Delete selected file/folder from Pico").grid(
                         row=2, column=0, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🗑  Delete All", self._delete_all_pico,
                     COL_PURPLE, COL_PURPLE_HV,
                     "Delete every item in current Pico folder").grid(
                         row=2, column=1, padx=2, pady=2, sticky="ew")
        self._mk_btn(btns, "🔄  Refresh", self._refresh_pico_files,
                     COL_SLATE, COL_SLATE_HV,
                     "Reload Pico file list").grid(
                         row=3, column=0, columnspan=2,
                         padx=2, pady=2, sticky="ew")

    # -- Editor pane ----------------------------------------------------

    def _build_editor_pane(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # Header row
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="📝  Editor", font=UI_FONT_BOLD,
            text_color=COL_TEXT,
        ).grid(row=0, column=0, padx=(0, 12))

        self._editor_file_var = ctk.StringVar(value="(no file)")
        ctk.CTkEntry(
            hdr, textvariable=self._editor_file_var, state="readonly",
            font=MONO_FONT_SMALL, fg_color=COL_BG,
            border_color=COL_BORDER, text_color=COL_TEXT_DIM,
        ).grid(row=0, column=1, sticky="ew", padx=4)

        self._mk_btn(hdr, "Open", self._open_file,
                     COL_SLATE, COL_SLATE_HV,
                     "Open file from disk  (⌘O)", width=72).grid(
                         row=0, column=2, padx=2)
        self._mk_btn(hdr, "Save", self._save_file,
                     COL_SLATE, COL_SLATE_HV,
                     "Save to PC  (⌘S)", width=72).grid(
                         row=0, column=3, padx=2)
        self._mk_btn(hdr, "💾  Save to Pico", self._save_to_pico,
                     COL_BLUE, COL_BLUE_HV,
                     "Save current file to Pico  (⇧⌘S)", width=140).grid(
                         row=0, column=4, padx=2)

        # Editor body: line numbers + tk.Text + scrollbars
        body = ctk.CTkFrame(
            parent, fg_color=COL_BG, corner_radius=6,
            border_width=1, border_color=COL_BORDER,
        )
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=2)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        self._editor = tk.Text(
            body, font=MONO_FONT, wrap="none", undo=True,
            bg=COL_BG, fg=COL_TEXT, insertbackground=COL_TEXT,
            selectbackground=_SELECTED_BG, selectforeground="white",
            bd=0, highlightthickness=0, padx=8, pady=8,
            inactiveselectbackground=COL_BORDER,
        )

        self._line_numbers = LineNumbers(body, self._editor)
        self._line_numbers.grid(row=0, column=0, sticky="ns", padx=(2, 0), pady=2)
        self._editor.grid(row=0, column=1, sticky="nsew", pady=2)

        vscroll = ctk.CTkScrollbar(
            body, orientation="vertical",
            button_color=COL_SLATE, button_hover_color=COL_SLATE_HV,
        )
        vscroll.grid(row=0, column=2, sticky="ns", padx=(0, 2), pady=2)
        hscroll = ctk.CTkScrollbar(
            body, orientation="horizontal",
            button_color=COL_SLATE, button_hover_color=COL_SLATE_HV,
        )
        hscroll.grid(row=1, column=1, sticky="ew", padx=2, pady=(0, 2))

        def _on_yview(*args):
            vscroll.set(*args)
            if self._line_numbers:
                self._line_numbers.redraw()

        self._editor.configure(
            yscrollcommand=_on_yview, xscrollcommand=hscroll.set,
        )
        vscroll.configure(command=self._sync_yview)
        hscroll.configure(command=self._editor.xview)

        # Syntax-highlight tags
        italic = MONO_FONT + ("italic",)
        self._editor.tag_configure("kw", foreground=SYN_KEYWORD)
        self._editor.tag_configure("bi", foreground=SYN_BUILTIN)
        self._editor.tag_configure("str", foreground=SYN_STRING)
        self._editor.tag_configure("cmt", foreground=SYN_COMMENT, font=italic)
        self._editor.tag_configure("num", foreground=SYN_NUMBER)
        self._editor.tag_configure("dec", foreground=SYN_DECORATOR)
        self._editor.tag_configure("defn", foreground=SYN_DEF_NAME)

        # Live syntax highlighting (debounced)
        self._editor.bind("<KeyRelease>", self._schedule_syntax)
        self._editor.bind("<<Modified>>", self._on_editor_modified)
        self._editor.bind(
            "<MouseWheel>",
            lambda _e: self.after(1, self._line_numbers.redraw),
        )
        self._editor.bind(
            "<Button-4>",
            lambda _e: self.after(1, self._line_numbers.redraw),
        )
        self._editor.bind(
            "<Button-5>",
            lambda _e: self.after(1, self._line_numbers.redraw),
        )
        self.after(80, self._line_numbers.redraw)

        # Action row
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(8, 10))

        self._mk_btn(actions, "▶  Run on Pico", self._run_on_pico,
                     COL_GREEN, COL_GREEN_HV,
                     "Run current file on Pico  (⌘R)").pack(side="left", padx=3)
        self._mk_btn(actions, "⚡  Exec Snippet", self._exec_editor_code,
                     COL_ORANGE, COL_ORANGE_HV,
                     "Exec selection (or whole file) on Pico  (⌘E)").pack(
                         side="left", padx=3)
        self._mk_btn(actions, "🚀  Deploy + Run", self._deploy_and_run,
                     COL_BLUE, COL_BLUE_HV,
                     "Copy to Pico and run it  (⌘D)").pack(side="left", padx=3)
        self._mk_btn(actions, "🔁  Reset Pico", self._reset_pico,
                     COL_PURPLE, COL_PURPLE_HV,
                     "Hard-reset the Pico").pack(side="left", padx=3)
        self._mk_btn(actions, "🔌  Open REPL", self._open_repl,
                     COL_SLATE, COL_SLATE_HV,
                     "Open interactive REPL in a new terminal window").pack(
                         side="left", padx=3)

    # -- Editor helpers (syntax + gutter sync) --------------------------

    def _sync_yview(self, *args) -> None:
        self._editor.yview(*args)
        if self._line_numbers:
            self.after(1, self._line_numbers.redraw)

    def _schedule_syntax(self, _event=None) -> None:
        if self._syntax_after_id:
            try:
                self.after_cancel(self._syntax_after_id)
            except Exception:
                pass
        self._syntax_after_id = self.after(120, self._apply_syntax)

    def _apply_syntax(self) -> None:
        self._syntax_after_id = None
        try:
            apply_python_syntax(self._editor)
        except Exception:
            pass
        if self._line_numbers:
            self._line_numbers.redraw()

    def _on_editor_modified(self, _event=None) -> None:
        try:
            self._editor.edit_modified(False)
        except tk.TclError:
            return
        if self._line_numbers:
            self._line_numbers.redraw()

    # -- Terminal pane --------------------------------------------------

    def _build_terminal(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        ctk.CTkLabel(
            hdr, text="💻  Terminal", font=UI_FONT_BOLD,
            text_color=COL_TEXT,
        ).pack(side="left")

        self._mk_btn(hdr, "Clear", self._terminal_clear,
                     COL_SLATE, COL_SLATE_HV,
                     "Clear terminal  (⌘K)", width=72).pack(
                         side="left", padx=(14, 2))

        self._stop_btn = ctk.CTkButton(
            hdr, text="⏹  Stop", width=82, font=UI_FONT,
            fg_color=COL_RED, hover_color=COL_RED_HV,
            command=self._stop_running, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=2)
        Tooltip(self._stop_btn, "Stop the running process")

        self._mk_btn(hdr, "📋  Copy", self._copy_log,
                     COL_SLATE, COL_SLATE_HV,
                     "Copy terminal log to clipboard", width=82).pack(
                         side="left", padx=2)
        self._mk_btn(hdr, "💾  Save", self._save_log,
                     COL_SLATE, COL_SLATE_HV,
                     "Save terminal log to file", width=82).pack(
                         side="left", padx=2)

        self._terminal = ctk.CTkTextbox(
            parent, font=MONO_FONT, wrap="word",
            fg_color=COL_BG, text_color=COL_TEXT,
            scrollbar_button_color=COL_SLATE,
            scrollbar_button_hover_color=COL_SLATE_HV,
            border_color=COL_BORDER, border_width=1, corner_radius=6,
        )
        self._terminal.grid(row=1, column=0, sticky="nsew", padx=10, pady=2)

        tw = self._terminal._textbox
        tw.tag_configure("cmd", foreground=_TAG_CMD)
        tw.tag_configure("error", foreground=_TAG_ERROR)
        tw.tag_configure("success", foreground=_TAG_SUCCESS)
        tw.tag_configure("warn", foreground=_TAG_WARN)

        # Exec input row
        inp = ctk.CTkFrame(parent, fg_color="transparent")
        inp.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 10))
        inp.grid_columnconfigure(0, weight=1)

        self._exec_entry = ctk.CTkEntry(
            inp, placeholder_text=">>>  run a snippet on Pico…",
            font=MONO_FONT, height=34,
            fg_color=COL_BG, border_color=COL_BORDER,
            text_color=COL_TEXT,
        )
        self._exec_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._exec_entry.bind("<Return>", lambda _e: self._exec_snippet())

        send = ctk.CTkButton(
            inp, text="Send", width=84, height=34, font=UI_FONT_BOLD,
            fg_color=COL_BLUE, hover_color=COL_BLUE_HV,
            command=self._exec_snippet,
        )
        send.grid(row=0, column=1)
        Tooltip(send, "Send exec snippet to Pico (Enter)")

    # -- Status bar -----------------------------------------------------

    def _build_status_bar(self) -> None:
        self._status_var = ctk.StringVar(value="Ready")
        bar = ctk.CTkFrame(
            self, corner_radius=0, height=30, fg_color=COL_BG_ALT,
        )
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        ctk.CTkLabel(
            bar, textvariable=self._status_var, anchor="w",
            font=UI_FONT_SM, text_color=COL_TEXT_DIM,
        ).pack(side="left", padx=16)
        self._port_label_var = ctk.StringVar(value="Not connected")
        ctk.CTkLabel(
            bar, textvariable=self._port_label_var, anchor="e",
            font=UI_FONT_SM, text_color=COL_TEXT_DIM,
        ).pack(side="right", padx=16)

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
                if pico_dir == "/":
                    full_path = "/" + name
                else:
                    full_path = pico_dir.rstrip("/") + "/" + name
                result = subprocess.run(
                    ["mpremote", "connect", port_snap, "rm", "-r", f":{full_path}"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                if result.stdout:
                    self._output_queue.put(result.stdout)
                if result.returncode != 0:
                    rc = result.returncode
            return rc

        self._output_queue.put(f"$ delete all from {pico_dir}\n")
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
                        self._apply_syntax()
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
            self._apply_syntax()

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
        self._apply_syntax()
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
