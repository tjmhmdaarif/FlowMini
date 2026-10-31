"""
FlowMini App — a world-class Windows desktop dictation app (Wispr Flow style).

Design: dark premium utility, single crimson accent, fluid spring animations,
iOS-style toggle, live waveform, typewriter transcription, glassmorphism cards.

Features:
- Push-to-talk (Ctrl+Alt+D) and VAD auto-dictation (Ctrl+Alt+F) global hotkeys
- Reliable universal paste into ANY active textbox (Notepad, browsers, editors)
- Live mic level waveform, recording pulse, processing animation
- System tray icon, minimize-to-tray, self-test, session stats
- Custom dictionary, LLM polish, SQLite telemetry

Run:  .venv\\Scripts\\python.exe flowmini_app.py   (or run_flow.bat)
"""

import os
import sys
import queue
import threading
import time
import math

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    sys.path.insert(0, BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE_DIR)

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
import json
import ctypes
from ctypes import wintypes

import flow_mini
from flow_mini import FlowMini, load_config, init_db

# ===========================================================================
# Heard-line formatting — pronunciation + optional original script / meaning
# ===========================================================================
def format_heard(raw, english=None, detected=None, conf=0.0):
    """Build the secondary "heard" line for the transcript card.

    Shows the English *pronunciation* (romanized) of what was spoken so that
    non-Latin languages are readable, plus the original script and the English
    meaning when they add information. Returns "" when there is nothing heard.
    """
    if not raw:
        return ""
    got = ""
    if detected:
        got = f" ({detected}" + (f" · {int(conf * 100)}%" if conf >= 0.5 else "") + ")"
    try:
        spoken = flow_mini.romanize(raw, detected)
    except Exception:
        spoken = raw
    line = f"heard{got}: {spoken}"
    extras = []
    if spoken and spoken.strip() != raw.strip():
        extras.append(f"[script: {raw}]")
    if english and english.strip().lower() != raw.strip().lower():
        extras.append(f"[English meaning: {english}]")
    return line + ("\n" + "\n".join(extras) if extras else "")


# ===========================================================================
# Win32 API — hotkeys, clipboard, paste
# ===========================================================================
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
# CRITICAL: without these prototypes, CreateWindowExW mangles the -3 parent
# HWND on a worker thread, the message-only window is never created (hwnd 0),
# and RegisterHotKey "succeeds" while posting into the void — dead hotkeys.
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = ctypes.c_ushort
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_long
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.EmptyClipboard.argtypes = []
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_V = 0x56
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

MOD_WIN = 0x0008

KEY_MAP = {
    "ctrl+alt+d": (MOD_CONTROL | MOD_ALT, 0x44),
    "ctrl+alt+f": (MOD_CONTROL | MOD_ALT, 0x46),
    "ctrl+alt+q": (MOD_CONTROL | MOD_ALT, 0x51),
    "ctrl+alt+w": (MOD_CONTROL | MOD_ALT, 0x57),
    "ctrl+shift+d": (MOD_CONTROL | MOD_SHIFT, 0x44),
    "ctrl+shift+f": (MOD_CONTROL | MOD_SHIFT, 0x46),
    "f8": (0, 0x77), "f9": (0, 0x78), "f10": (0, 0x79),
    "f11": (0x7A), "f12": (0, 0x7B),
}


class _HotkeyWindow:
    """Message-only window that owns RegisterHotKey hotkeys.

    CRITICAL: RegisterHotKey posts WM_HOTKEY to the message queue of the thread
    that CALLED RegisterHotKey. The window is therefore created, the hotkeys
    registered, AND the message loop run all on the same dedicated thread —
    otherwise WM_HOTKEY never reaches the pump and the hotkeys appear dead.

    Callbacks (on_registered / on_hotkey) run on the pump thread; the app must
    marshal them to the UI thread via its queue.
    """

    def __init__(self, hotkey_specs, on_registered, on_hotkey):
        # hotkey_specs: list of (hotkey_id, label, modifiers, vk)
        self._specs = hotkey_specs
        self._on_registered = on_registered
        self._on_hotkey = on_hotkey
        self._hwnd = None
        self._wndproc_ref = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            try:
                self._on_hotkey(wparam)
            except Exception:
                pass
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        hInst = kernel32.GetModuleHandleW(None)
        wndproc = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)(self._wndproc)
        self._wndproc_ref = wndproc  # keep the callback alive

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(wndproc, ctypes.c_void_p)
        wc.hInstance = hInst
        wc.lpszClassName = "FlowMiniHotkeyWindow"
        user32.RegisterClassW(ctypes.byref(wc))
        # HWND_MESSAGE = -3 → message-only window (no UI, just a message target)
        self._hwnd = user32.CreateWindowExW(
            0, "FlowMiniHotkeyWindow", "FlowMini Hotkeys", 0,
            0, 0, 0, 0, -3, None, hInst, None)

        # Register on THIS thread so WM_HOTKEY lands in this thread's queue.
        for hotkey_id, label, modifiers, vk in self._specs:
            ok = False
            try:
                ok = bool(user32.RegisterHotKey(self._hwnd, hotkey_id,
                                                modifiers | MOD_NOREPEAT, vk))
            except Exception:
                ok = False
            try:
                self._on_registered(hotkey_id, label, ok)
            except Exception:
                pass

        msg = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:  # WM_QUIT (0) or error (-1)
                break
            # DispatchMessageW routes WM_HOTKEY to our WndProc exactly once.
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        try:
            user32.PostMessageW(self._hwnd, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass


# ===========================================================================
# Design system — "refined crimson" (front-end reframe)
# One tinted cool-dark surface family, ONE standing accent (crimson) reserved
# for live/active meaning, a unified cool-gray text ramp, and a real type
# scale using Segoe UI Semibold/Medium as tkinter's missing 500/600 weights.
# Spacing grid: 4 / 8 / 12 / 16 / 22.
# ===========================================================================
BG = "#0b0d13"             # window background — deep blue-black, never #000
BG_RAISED = "#12151d"      # cards & panels (waveform, settings, transcript, log)
BG_HOVER = "#1a1f2a"       # hover / pressed surface
BORDER = "#232936"         # hairline frames around cards
BORDER_SOFT = "#1b202b"    # faint divider inside panels
TRACK_OFF = "#2a2f3d"      # toggle track, off
KNOB = "#f4f6fb"           # toggle knob
WAVE_REST = "#39415a"      # waveform at rest — quiet slate, not a shout
ACCENT = "#e63946"         # crimson — the one standing accent
ACCENT_GLOW = "#ff5c6b"    # hover + live crimson
ACCENT_DIM = "#8f2733"     # crimson halo / shadow
TEXT_PRIMARY = "#eef1f7"   # headings, transcript
TEXT_SECONDARY = "#9aa3b5" # body, log text, row labels
TEXT_MUTED = "#626b7e"     # captions, section labels
SUCCESS = "#3ddc84"        # semantic: enabled / idle / pasted
WARNING = "#ffb02e"        # semantic: processing
INFO = "#4da3ff"           # semantic: loading / vad armed

#: Base font tuples. "Segoe UI Semibold"/"Segoe UI Medium" give tkinter the
#: 500/600 weights it cannot express in a plain ("Segoe UI", n) tuple; when a
#: family is missing (older Windows) _init_fonts() falls back to bold/regular.
FONT_BASE = {
    "display":  ("Segoe UI Semibold", 24),   # the big status word
    "title":    ("Segoe UI Semibold", 16),   # "FlowMini"
    "hero":     ("Segoe UI Semibold", 12),   # VAD block title
    "hud":      ("Segoe UI Semibold", 10),   # HUD status word
    "section":  ("Segoe UI Semibold", 9),    # uppercase micro-labels
    "control":  ("Segoe UI Medium", 10),     # settings row labels + combos
    "body":     ("Segoe UI", 11),
    "caption":  ("Segoe UI", 9),
    "mono":     ("Consolas", 9),             # log + stats (tabular figures)
}
FONTS = dict(FONT_BASE)  # refined in FlowMiniApp.__init__ via _init_fonts()

#: App version shown in the UI and shipped on GitHub releases.
APP_VERSION = "1.1.0.2"


def _init_fonts():
    """Resolve the weight-via-family fonts against what this Windows ships."""
    global FONTS
    try:
        families = {f.lower() for f in tkfont.families()}
    except Exception:
        families = set()
    FONTS = dict(FONT_BASE)
    if "segoe ui semibold" not in families:
        FONTS["display"] = ("Segoe UI", 24, "bold")
        FONTS["title"] = ("Segoe UI", 16, "bold")
        FONTS["hero"] = ("Segoe UI", 12, "bold")
        FONTS["hud"] = ("Segoe UI", 10, "bold")
        FONTS["section"] = ("Segoe UI", 9, "bold")
    if "segoe ui medium" not in families:
        FONTS["control"] = ("Segoe UI", 10)


#: Below this window width the layout stacks in one column; at or above it the
#: settings panel moves to a right-hand side column (maximized / fullscreen).
WIDE_BREAKPOINT = 900

#: Floating HUD cards auto-hide after this long without a state update — a
#: card whose events stop arriving (stuck "STARTING ASR" load) must never
#: pin itself to the screen forever. Live "recording" cards are exempt.
HUD_AUTO_HIDE_MS = 10_000

#: Section placement per mode. Every section is a direct child of the root, so
#: reflow is just grid_forget() + grid() with mode-specific coordinates — no
#: re-parenting, widget state (toggles, combos) survives untouched.
_LAYOUT_NARROW = {
    "header":     dict(row=0, column=0, columnspan=2, sticky="ew", padx=22, pady=(14, 0)),
    "status":     dict(row=1, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    "wave":       dict(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    "record":     dict(row=3, column=0, columnspan=2, pady=(10, 0)),
    "panel":      dict(row=4, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    "transcript": dict(row=5, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    "buttons":    dict(row=6, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    "stats":      dict(row=7, column=0, columnspan=2, sticky="w", padx=22, pady=(8, 0)),
    "log":        dict(row=8, column=0, columnspan=2, sticky="nsew", padx=22, pady=(8, 16)),
    "log_row": 8,
    "flex_rows": (),          # only the log grows vertically
    "col1_minsize": 0,
}
_LAYOUT_WIDE = {
    "header":     dict(row=0, column=0, columnspan=2, sticky="ew", padx=22, pady=(14, 0)),
    "status":     dict(row=1, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    # stage stays in the left column; settings panel becomes a right sidebar
    "wave":       dict(row=2, column=0, sticky="ew", padx=(22, 12), pady=(10, 0)),
    "record":     dict(row=3, column=0, pady=(10, 0)),
    "transcript": dict(row=4, column=0, sticky="nsew", padx=(22, 12), pady=(10, 0)),
    "panel":      dict(row=2, column=1, rowspan=3, sticky="nsew", padx=(0, 22), pady=(10, 0)),
    "buttons":    dict(row=5, column=0, columnspan=2, sticky="ew", padx=22, pady=(10, 0)),
    "stats":      dict(row=6, column=0, columnspan=2, sticky="w", padx=22, pady=(8, 0)),
    "log":        dict(row=7, column=0, columnspan=2, sticky="nsew", padx=22, pady=(8, 16)),
    "log_row": 7,
    "flex_rows": (4, 7),      # transcript + log share extra height
    "col1_minsize": 360,
}


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return "#%02x%02x%02x" % (int(r1 + (r2 - r1) * t),
                              int(g1 + (g2 - g1) * t),
                              int(b1 + (b2 - b1) * t))


# BCP-47 codes supported by Google speech recognition
LANGUAGES = [
    ("en-US", "English (US)"), ("en-GB", "English (UK)"),
    ("hi-IN", "Hindi"), ("bn-IN", "Bengali"), ("ta-IN", "Tamil"),
    ("te-IN", "Telugu"), ("mr-IN", "Marathi"), ("gu-IN", "Gujarati"),
    ("kn-IN", "Kannada"), ("ml-IN", "Malayalam"), ("pa-IN", "Punjabi"),
    ("ur-PK", "Urdu"), ("ne-NP", "Nepali"),
    ("es-ES", "Spanish"), ("fr-FR", "French"), ("de-DE", "German"),
    ("it-IT", "Italian"), ("pt-BR", "Portuguese (BR)"), ("ru-RU", "Russian"),
    ("ar-SA", "Arabic"), ("tr-TR", "Turkish"), ("fa-IR", "Persian"),
    ("ja-JP", "Japanese"), ("ko-KR", "Korean"), ("zh-CN", "Chinese (Simplified)"),
    ("zh-TW", "Chinese (Traditional)"), ("nl-NL", "Dutch"), ("pl-PL", "Polish"),
    ("sv-SE", "Swedish"), ("id-ID", "Indonesian"), ("th-TH", "Thai"),
    ("vi-VN", "Vietnamese"), ("he-IL", "Hebrew"), ("el-GR", "Greek"),
    ("cs-CZ", "Czech"), ("uk-UA", "Ukrainian"), ("fil-PH", "Filipino"),
]
LANG_DISPLAY = {code: f"{label}  —  {code}" for code, label in LANGUAGES}
LANG_BY_DISPLAY = {f"{label}  —  {code}": code for code, label in LANGUAGES}
VALID_LANG_CODES = {code for code, _ in LANGUAGES}


class ToggleSwitch(tk.Canvas):
    """iOS-style animated toggle switch."""

    def __init__(self, parent, command=None, initial=False, bg=None):
        super().__init__(parent, width=56, height=32, bg=bg or BG, highlightthickness=0,
                         cursor="hand2")
        self.command = command
        self._on = initial
        self._anim = 0  # 0=off, 1=on
        self._target = 1 if initial else 0
        self._draw()
        self.bind("<Button-1>", self._click)
        self._animate()

    def _draw(self):
        self.delete("all")
        a = self._anim
        # track: quiet slate when off, semantic green when on
        track_color = self._lerp_color(TRACK_OFF, SUCCESS, a)
        self.create_oval(2, 2, 30, 30, fill=track_color, width=0)
        self.create_rectangle(1, 1, 31, 31, fill=track_color, width=0)
        self.create_oval(26, 2, 54, 30, fill=track_color, width=0)
        # knob
        knob_x = 4 + 24 * a
        self.create_oval(knob_x, 4, knob_x + 24, 28, fill="white", width=0)

    def _lerp_color(self, c1, c2, t):
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _click(self, _=None):
        self._on = not self._on
        self._target = 1 if self._on else 0
        self._ensure_animate()
        if self.command:
            self.command(self._on)

    def _ensure_animate(self):
        if not getattr(self, "_animating", False):
            self._animating = True
            self._animate()

    def _animate(self):
        diff = self._target - self._anim
        if abs(diff) > 0.01:
            self._anim += diff * 0.25
            self._draw()
            self.after(16, self._animate)
        else:
            self._anim = float(self._target)
            self._draw()
            self._animating = False

    def set_state(self, on):
        self._on = on
        self._target = 1 if on else 0
        self._ensure_animate()


class WaveformCanvas(tk.Canvas):
    """Animated waveform / mic level visualizer."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_RAISED, highlightthickness=0, **kw)
        self._level = 0
        self._ema = 0
        self._recording = False
        self._phase = 0
        self._bars = []
        self._n_bars = 32
        self._bar_w = 6
        self._bar_gap = 3

    def set_level(self, level, recording=False):
        self._level = level
        self._recording = recording

    def draw(self):
        self.delete("all")
        w = self.winfo_width() or 400
        h = self.winfo_height() or 60
        self._ema = max(self._ema * 0.82, min(self._level, 1.0))
        self._phase += 0.22 if self._recording else 0.05
        # Adaptive meter: bar count follows the window width (any snap size),
        # and wide windows spread the bars instead of clustering in the middle.
        n = max(16, min(64, w // 10))
        bar_w = self._bar_w
        gap = self._bar_gap
        if w > n * (bar_w + gap) + 160:
            gap = min(12, max(gap, int((w * 0.72 - n * bar_w) / max(1, n - 1))))
        total_w = n * (bar_w + gap)
        x0 = (w - total_w) // 2
        self._n_bars = n
        # Rest: quiet slate. Recording: ramps WAVE_REST -> crimson with level,
        # so the accent MEANS "live" instead of decorating an idle screen.
        if self._recording:
            color = lerp_color(WAVE_REST, ACCENT_GLOW, min(1.0, 0.35 + self._ema))
        else:
            color = lerp_color(WAVE_REST, TEXT_MUTED, min(1.0, self._ema * 0.6))
        for i in range(n):
            center_offset = abs(i - (n - 1) / 2) / ((n - 1) / 2)
            envelope = 1.0 - center_offset * 0.65
            if self._recording:
                wave = (math.sin(self._phase + i * 0.55) + 1) / 2
                bar_h = max(4, (self._ema * 0.55 + wave * 0.45) * envelope * (h - 10))
            else:
                idle = (math.sin(self._phase + i * 0.35) + 1) / 2
                bar_h = max(4, (self._ema * 0.85 + idle * 0.06) * envelope * (h - 10))
            x = x0 + i * (bar_w + gap) + bar_w / 2
            cy = h / 2
            self.create_line(x, cy - bar_h / 2, x, cy + bar_h / 2,
                             fill=color, width=bar_w, capstyle="round")


# ===========================================================================
# Floating dictation HUD — the always-on-top card that appears near the
# cursor while you dictate, so you get feedback even with the main window
# minimized to the tray. Borderless, never steals focus (WS_EX_NOACTIVATE).
# ===========================================================================
class DictationHud:
    """Small always-on-top status card shown near the mouse while dictating."""

    # Win32 extended window styles
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    GWL_EXSTYLE = -20
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    WIDTH = 340
    HEIGHT = 74
    MARGIN = 18

    # state -> (label, dot/text color)
    STATES = {
        "recording": ("RECORDING", ACCENT_GLOW),
        "processing": ("THINKING…", WARNING),
        "loading": ("STARTING ASR", INFO),
        "pasted": ("PASTED ✓", SUCCESS),
        "clipboard": ("ON CLIPBOARD", WARNING),
    }

    def __init__(self):
        self.win = tk.Toplevel()
        self.win.withdraw()                       # hidden until first dictation
        self.win.overrideredirect(True)
        self.win.configure(bg=BORDER)             # border colour = 1px frame
        inner = tk.Frame(self.win, bg=BG_RAISED)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        top = tk.Frame(inner, bg=BG_RAISED)
        top.pack(fill="x", padx=12, pady=(9, 0))
        self.dot = tk.Canvas(top, width=10, height=10, bg=BG_RAISED,
                             highlightthickness=0)
        self.dot.create_oval(1, 1, 9, 9, fill=SUCCESS, width=0, tags="dot")
        self.dot.pack(side="left")
        self.status = tk.Label(top, text="IDLE", font=FONTS["hud"],
                               bg=BG_RAISED, fg=SUCCESS)
        self.status.pack(side="left", padx=(8, 0))
        self.text = tk.Label(inner, text="", font=("Segoe UI", 10),
                             bg=BG_RAISED, fg=TEXT_SECONDARY, anchor="w")
        self.text.pack(fill="x", padx=12, pady=(4, 0))

        # thin level meter along the bottom edge
        self.meter = tk.Canvas(inner, height=3, bg=BG_RAISED, highlightthickness=0)
        self.meter.pack(fill="x", padx=12, pady=(6, 8))
        self._meter_id = None

        self._ema = 0.0
        self._state = None
        self._visible = False

        self.win.bind("<Map>", self._on_map)
        self.win.withdraw()

    # ------------------------------------------------------------- Win32 ---
    def _on_map(self, _=None):
        """After the window first maps, strip the taskbar entry / focus steal."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            if not hwnd:
                hwnd = self.win.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, self.GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, self.GWL_EXSTYLE,
                style | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _cursor_pos(self):
        pt = wintypes.POINT()
        try:
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        except Exception:
            return 100, 100

    def _place_near_cursor(self):
        """Position above-right of the cursor, clamped to the virtual screen."""
        cx, cy = self._cursor_pos()
        u = ctypes.windll.user32
        vx = u.GetSystemMetrics(self.SM_XVIRTUALSCREEN)
        vy = u.GetSystemMetrics(self.SM_YVIRTUALSCREEN)
        vw = u.GetSystemMetrics(self.SM_CXVIRTUALSCREEN) or 1920
        vh = u.GetSystemMetrics(self.SM_CYVIRTUALSCREEN) or 1080
        x = cx + self.MARGIN
        y = cy - self.HEIGHT - self.MARGIN
        x = max(vx + 4, min(x, vx + vw - self.WIDTH - 4))
        y = max(vy + 4, min(y, vy + vh - self.HEIGHT - 4))
        self.win.geometry(f"{self.WIDTH}x{self.HEIGHT}+{int(x)}+{int(y)}")

    # ------------------------------------------------------------ public ---
    def show(self, state, text=None):
        """Show (or update) the HUD in the given state; positions at the cursor."""
        label, color = self.STATES.get(state, self.STATES["processing"])
        self.status.config(text=label, fg=color)
        self.dot.itemconfig("dot", fill=color)
        if text is not None:
            self.set_text(text)
        self._state = state
        if not self._visible:
            self._place_near_cursor()
            self.win.deiconify()
            self.win.attributes("-topmost", True)
            try:
                self.win.lift()
            except Exception:
                pass
            self._visible = True

    def set_text(self, text):
        """Show a one-line, truncated transcript in the HUD."""
        line = " ".join((text or "").split())
        if len(line) > 60:
            line = line[:59] + "…"
        self.text.config(text=line, fg=TEXT_PRIMARY if line else TEXT_MUTED)

    def hide(self):
        if self._visible:
            try:
                self.win.withdraw()
            except Exception:
                pass
            self._visible = False
            self._state = None

    @property
    def visible(self):
        return self._visible

    def set_level(self, rms):
        """Feed the mic RMS from the audio thread; drawn on the UI tick."""
        self._ema = max(self._ema * 0.8, min(rms / 3000.0, 1.0))

    def draw_meter(self):
        """Repaint the bottom level meter (call from the app's 33ms tick)."""
        if not self._visible:
            return
        self.meter.delete("all")
        w = self.meter.winfo_width() or (self.WIDTH - 24)
        self.meter.create_rectangle(0, 0, w, 3, fill=BG, width=0)
        fill_w = int(w * self._ema)
        if fill_w > 0:
            color = ACCENT_GLOW if self._state == "recording" else INFO
            self.meter.create_rectangle(0, 0, fill_w, 3, fill=color, width=0)


# ===========================================================================
# Main App
# ===========================================================================
class FlowMiniApp:
    def __init__(self):
        self.config = load_config()
        self.db = init_db()
        self.core = None
        self._hotkey_win = None
        self.hotkey_ids = {}
        self.ui_queue = queue.Queue()
        self._stats = {"sessions": 0, "words": 0, "latency": 0}
        self._typewriter_job = None
        self._status = "idle"
        self.hud = None
        self._hud_hide_job = None

        self.root = tk.Tk()
        self.root.title("FlowMini — Voice Dictation")
        self.root.geometry("544x990")   # tall enough for every section at once
        self.root.minsize(400, 560)   # small enough for quarter-screen snaps
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

        _init_fonts()
        self._setup_ttk()
        self._build_ui()

        # responsive layout: stacked when narrow, side panel when wide
        # (maximized / fullscreen / any snapped orientation)
        self._wide_mode = None
        self._wrap_at = 0
        self._reflow()
        self.root.bind("<Configure>", self._on_root_configure)
        self._redirect_stdout()
        self._refresh_stats()
        self._refresh_stats_label()

        self.root.after(300, self._register_hotkeys)
        self.root.after(50, self._pump_ui_queue)
        self.root.after(33, self._draw_waveform)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        """Reframed layout: brand + stage on top, one raised settings panel,
        output and tools below. Same widget names — only the styling moved."""
        PADX = 22  # window gutter (spacing grid: 4 / 8 / 12 / 16 / 22)

        # --- header: brand + hotkey reference chips ---
        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=PADX, pady=(18, 0))
        header.grid_columnconfigure(1, weight=1)
        tk.Label(header, text="FlowMini", font=FONTS["title"],
                 bg=BG, fg=TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=f"voice dictation · v{APP_VERSION}", font=FONTS["caption"],
                 bg=BG, fg=TEXT_MUTED).grid(row=0, column=1, sticky="w",
                                            padx=(10, 0))
        chips = tk.Frame(header, bg=BG)
        chips.grid(row=0, column=2, sticky="e")
        for i, key in enumerate(("CTRL+ALT+D", "CTRL+ALT+F")):
            chip = tk.Frame(chips, bg=BG_RAISED, highlightthickness=1,
                            highlightbackground=BORDER)
            tk.Label(chip, text=key, font=FONTS["mono"], bg=BG_RAISED,
                     fg=TEXT_MUTED, padx=7, pady=3).pack()
            chip.pack(side="left", padx=(6, 0) if i else 0)

        # --- status line: dot + display word + mode caption ---
        status_row = tk.Frame(self.root, bg=BG)
        status_row.grid(row=1, column=0, sticky="ew", padx=PADX, pady=(16, 0))
        status_row.grid_columnconfigure(1, weight=1)
        self.status_dot = tk.Canvas(status_row, width=12, height=12, bg=BG,
                                    highlightthickness=0)
        self.status_dot.create_oval(1, 1, 11, 11, fill=SUCCESS, width=0, tags="dot")
        self.status_dot.grid(row=0, column=0, sticky="w", pady=(7, 0))
        self.status_label = tk.Label(status_row, text="IDLE", font=FONTS["display"],
                                     bg=BG, fg=SUCCESS)
        self.status_label.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.mode_label = tk.Label(status_row, text="push-to-talk",
                                   font=FONTS["caption"], bg=BG, fg=TEXT_MUTED)
        self.mode_label.grid(row=0, column=2, sticky="e", pady=(8, 0))

        # --- waveform: raised card, quiet slate at rest ---
        wave_frame = tk.Frame(self.root, bg=BG_RAISED, highlightthickness=1,
                              highlightbackground=BORDER)
        wave_frame.grid(row=2, column=0, sticky="ew", padx=PADX, pady=(14, 0))
        self.wave = WaveformCanvas(wave_frame, height=56)
        self.wave.pack(fill="both", expand=True, padx=1, pady=1)

        # --- record button ---
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.grid(row=3, column=0, pady=(16, 0))
        self.record_canvas = tk.Canvas(btn_frame, width=96, height=96, bg=BG,
                                       highlightthickness=0, cursor="hand2")
        self.record_canvas.pack()
        self.record_canvas.bind("<Button-1>", lambda _: self._toggle_ptt())
        self.record_canvas.bind("<Enter>", lambda _: self._set_btn_hover(True))
        self.record_canvas.bind("<Leave>", lambda _: self._set_btn_hover(False))
        self.hint_label = tk.Label(btn_frame, text="click, or press Ctrl+Alt+D",
                                   font=FONTS["caption"], bg=BG, fg=TEXT_MUTED)
        self.hint_label.pack(pady=(8, 0))
        self._btn_hover = False
        self._draw_record("idle")

        # --- settings panel: one raised surface, consistent row rhythm ---
        panel = tk.Frame(self.root, bg=BG_RAISED, highlightthickness=1,
                         highlightbackground=BORDER)
        panel.grid(row=4, column=0, sticky="ew", padx=PADX, pady=(16, 0))
        panel.grid_columnconfigure(0, weight=1)

        def separator(row):
            tk.Frame(panel, bg=BORDER_SOFT, height=1).grid(
                row=row, column=0, sticky="ew", padx=14, pady=8)

        def section(row, text):
            tk.Label(panel, text=text, font=FONTS["section"], bg=BG_RAISED,
                     fg=TEXT_MUTED).grid(row=row, column=0, sticky="w", padx=14)

        def row_control(row, label, factory):
            """Label left, control right. The control is BUILT inside the row
            frame (factory pattern) — a widget can only ever be gridded in its
            own parent, so creating it elsewhere would pile it up."""
            r = tk.Frame(panel, bg=BG_RAISED)
            r.grid(row=row, column=0, sticky="ew", padx=14, pady=3)
            r.grid_columnconfigure(0, weight=1)
            tk.Label(r, text=label, font=FONTS["control"], bg=BG_RAISED,
                     fg=TEXT_SECONDARY).grid(row=0, column=0, sticky="w")
            control = factory(r)
            control.grid(row=0, column=1, sticky="e")
            return control

        # VAD hero row
        vad_row = tk.Frame(panel, bg=BG_RAISED)
        vad_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 0))
        vad_row.grid_columnconfigure(0, weight=1)
        vad_text = tk.Frame(vad_row, bg=BG_RAISED)
        vad_text.grid(row=0, column=0, sticky="w")
        tk.Label(vad_text, text="VAD auto-dictation", font=FONTS["hero"],
                 bg=BG_RAISED, fg=TEXT_PRIMARY).pack(anchor="w")
        tk.Label(vad_text, text="hands-free — starts when you speak",
                 font=FONTS["caption"], bg=BG_RAISED,
                 fg=TEXT_MUTED).pack(anchor="w", pady=(2, 0))
        self.toggle = ToggleSwitch(vad_row, command=self._on_toggle_vad,
                                   bg=BG_RAISED)
        self.toggle.grid(row=0, column=1, sticky="e")

        separator(1)
        section(2, "LANGUAGE & OUTPUT")

        self.lang_combo = row_control(
            3, "Speech language",
            lambda par: ttk.Combobox(
                par, values=list(LANG_DISPLAY.values()), state="readonly",
                width=24, font=FONTS["control"], style="Flow.TCombobox"))
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_change)

        self.trans_toggle = row_control(
            4, "Translate to English",
            lambda par: ToggleSwitch(par, command=self._on_translate_toggle,
                                     bg=BG_RAISED))

        self.cleanup_combo = row_control(
            5, "Cleanup mode",
            lambda par: ttk.Combobox(
                par, values=["light", "medium", "off"], state="readonly",
                width=7, font=FONTS["control"], style="Flow.TCombobox"))
        self.cleanup_combo.bind("<<ComboboxSelected>>", self._on_cleanup_change)

        self.style_combo = row_control(
            6, "Style preset",
            lambda par: ttk.Combobox(
                par, values=["formal", "casual", "very_casual", "excited"],
                state="readonly", width=10, font=FONTS["control"],
                style="Flow.TCombobox"))
        self.style_combo.bind("<<ComboboxSelected>>", self._on_style_change)

        separator(7)
        section(8, "BEHAVIOUR")

        self.dev_toggle = row_control(
            9, "Developer mode",
            lambda par: ToggleSwitch(par, command=self._on_developer_toggle,
                                     bg=BG_RAISED))

        self.profiles_toggle = row_control(
            10, "Per-app profiles",
            lambda par: ToggleSwitch(par, command=self._on_profiles_toggle,
                                     bg=BG_RAISED))
        tk.Frame(panel, bg=BG_RAISED, height=6).grid(row=11, column=0)

        # --- last dictation card ---
        card = tk.Frame(self.root, bg=BG_RAISED, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=5, column=0, sticky="ew", padx=PADX, pady=(16, 0))
        card.grid_columnconfigure(0, weight=1)
        tk.Label(card, text="LAST DICTATION", font=FONTS["section"],
                 bg=BG_RAISED, fg=TEXT_MUTED).grid(row=0, column=0, sticky="w",
                                                   padx=14, pady=(11, 0))
        self.transcript_text = tk.Label(card, text="nothing dictated yet",
                                        font=("Segoe UI", 13), bg=BG_RAISED,
                                        fg=TEXT_MUTED, wraplength=466,
                                        justify="left", anchor="w")
        self.transcript_text.grid(row=1, column=0, sticky="w", padx=14,
                                  pady=(6, 2))
        self.transcript_raw = tk.Label(card, text="", font=FONTS["caption"],
                                       bg=BG_RAISED, fg=TEXT_MUTED,
                                       wraplength=466, justify="left", anchor="w")
        self.transcript_raw.grid(row=2, column=0, sticky="w", padx=14,
                                 pady=(0, 12))

        # --- ghost action buttons ---
        row_btns = tk.Frame(self.root, bg=BG)
        row_btns.grid(row=6, column=0, sticky="ew", padx=PADX, pady=(14, 0))
        row_btns.grid_columnconfigure(0, weight=1)
        row_btns.grid_columnconfigure(1, weight=1)
        row_btns.grid_columnconfigure(2, weight=1)
        self.btn_test = self._ghost_button(row_btns, "Self-Test", self._on_self_test)
        self.btn_stats = self._ghost_button(row_btns, "Refresh Stats",
                                            self._on_refresh_stats)
        self.btn_undo = self._ghost_button(row_btns, "↩ Undo (raw)",
                                           self._undo_paste, state="disabled")
        for i, btn in enumerate((self.btn_test, self.btn_stats, self.btn_undo)):
            btn.grid(row=0, column=i, sticky="ew", ipady=6,
                     padx=(0, 8) if i == 0 else (8, 0) if i == 1 else 0)

        # --- stats (mono, tabular) ---
        self.stats_label = tk.Label(self.root, text="", font=FONTS["mono"],
                                    bg=BG, fg=TEXT_MUTED)
        self.stats_label.grid(row=7, column=0, sticky="w", padx=PADX,
                              pady=(10, 0))

        # --- log console ---
        log_frame = tk.Frame(self.root, bg=BG_RAISED, highlightthickness=1,
                             highlightbackground=BORDER)
        log_frame.grid(row=8, column=0, sticky="nsew", padx=PADX, pady=(12, 20))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(8, weight=1)

        self.log_box = tk.Text(log_frame, bg=BG_RAISED, fg=TEXT_SECONDARY,
                               font=FONTS["mono"], relief="flat", state="disabled",
                               insertbackground="white", wrap="word", height=6,
                               highlightthickness=0, padx=12, pady=10)
        self.log_box.grid(row=0, column=0, sticky="nsew")
        self.log_box.tag_configure("ok", foreground=SUCCESS)
        self.log_box.tag_configure("warn", foreground=WARNING)
        self.log_box.tag_configure("err", foreground=ACCENT_GLOW)
        self.log_box.tag_configure("dim", foreground=TEXT_MUTED)

        # sections kept for responsive reflow (narrow <-> wide); the transcript
        # card re-wraps its text to whatever width it gets
        self._sec = {"header": header, "status": status_row, "wave": wave_frame,
                     "record": btn_frame, "panel": panel, "transcript": card,
                     "buttons": row_btns, "stats": self.stats_label,
                     "log": log_frame}
        card.bind("<Configure>", self._sync_wraplength)

    def _on_root_configure(self, event=None):
        """Root resized (maximize, snap, drag): reflow when the mode changes."""
        if event is not None and event.widget is not self.root:
            return
        self._reflow()
        self._fit_status_font()

    def _fit_status_font(self):
        """Scale the big status word so it never wraps at small snap sizes.

        Quarter-window snaps are only ~360 logical px wide — the 24pt
        heading plus the mode caption no longer fit there, so the grid
        squeezed the labels and the heading broke across two lines.
        """
        try:
            width = self.root.winfo_width()
        except Exception:
            return
        size = 24 if width >= 400 else (20 if width >= 350 else 17)
        if getattr(self, "_display_pt", None) == size:
            return
        self._display_pt = size
        base = FONTS["display"]
        self.status_label.config(font=(base[0], size) + tuple(base[2:]))

    def _reflow(self, _=None):
        """Switch between the stacked (narrow) and side-panel (wide) layouts.

        Runs on every root resize but only lays out again when the mode
        actually flips (>= WIDE_BREAKPOINT). Works for maximize, Win+arrow
        snaps, and free dragging to any size.
        """
        try:
            width = self.root.winfo_width()
        except Exception:
            return
        wide = width >= WIDE_BREAKPOINT
        if wide == self._wide_mode:
            return
        self._wide_mode = wide
        table = _LAYOUT_WIDE if wide else _LAYOUT_NARROW
        for section in self._sec.values():
            section.grid_forget()
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=0,
                                       minsize=table["col1_minsize"])
        for row in range(9):
            self.root.grid_rowconfigure(row, weight=0)
        for row in table["flex_rows"]:
            self.root.grid_rowconfigure(row, weight=1)
        for name, section in self._sec.items():
            section.grid(**table[name])
        self._sync_wraplength()

    def _sync_wraplength(self, event=None):
        """Transcript text wraps to the card width at any window size."""
        try:
            width = (event.width if event is not None
                     else self._sec["transcript"].winfo_width())
        except Exception:
            return
        if width < 80:
            return
        wrap = max(280, width - 44)
        if abs(wrap - getattr(self, "_wrap_at", 0)) < 12:
            return
        self._wrap_at = wrap
        self.transcript_text.config(wraplength=wrap)
        self.transcript_raw.config(wraplength=wrap)

    def _setup_ttk(self):
        """Dark ttk comboboxes end-to-end: field, arrow, and the popdown list.

        The vista/alt themes draw the combobox field via VSAPI and ignore
        `fieldbackground` (the field stays light no matter what we ask), so
        the ttk layer runs on clam — it honors every color and stays crisp.
        """
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Flow.TCombobox",
                        padding=(10, 6), font=FONTS["control"], borderwidth=1,
                        arrowsize=13,
                        fieldbackground=BG_RAISED, background=BG_RAISED,
                        foreground=TEXT_PRIMARY, bordercolor=BORDER,
                        arrowcolor=TEXT_SECONDARY, lightcolor=BORDER,
                        darkcolor=BORDER)
        style.map("Flow.TCombobox",
                  foreground=[("readonly", TEXT_PRIMARY)],
                  fieldbackground=[("readonly", BG_RAISED)],
                  selectbackground=[("readonly", BG_RAISED)],
                  selectforeground=[("readonly", TEXT_PRIMARY)],
                  bordercolor=[("hover", ACCENT_DIM)],
                  arrowcolor=[("hover", TEXT_PRIMARY)])
        # the dropdown list is Tk-drawn — theme it dark too
        self.root.option_add("*TCombobox*Listbox*Background", BG_RAISED)
        self.root.option_add("*TCombobox*Listbox*Foreground", TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox*selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox*Font", FONTS["control"])

    def _ghost_button(self, parent, text, command, state="normal"):
        """Flat ghost button: raised surface, lightens on hover, dim when off."""
        disabled = state == "disabled"
        btn = tk.Button(parent, text=text, command=command, bd=0, relief="flat",
                        bg=BG_RAISED, font=FONTS["control"],
                        fg=TEXT_MUTED if disabled else TEXT_SECONDARY,
                        activebackground=BG_HOVER, activeforeground=TEXT_PRIMARY,
                        disabledforeground=TEXT_MUTED, cursor="hand2",
                        highlightthickness=0, state=state)
        if not disabled:
            btn.bind("<Enter>",
                     lambda e, b=btn: b.config(bg=BG_HOVER, fg=TEXT_PRIMARY))
            btn.bind("<Leave>",
                     lambda e, b=btn: b.config(bg=BG_RAISED, fg=TEXT_SECONDARY))
        return btn

    def _set_btn_hover(self, on):
        """Hover feedback on the mic button (redraws with a glow ring)."""
        on = bool(on)
        if getattr(self, "_btn_hover", False) == on:
            return
        self._btn_hover = on
        self._draw_record(getattr(self, "_record_state", "idle"),
                          getattr(self, "_pulse", 0.0))

    def _draw_record(self, state="idle", pulse=0.0):
        """The mic button — crimson disc with state rings and a hover glow."""
        c = self.record_canvas
        c.delete("all")
        self._record_state = state
        colors = {"idle": ACCENT, "recording": ACCENT_GLOW,
                  "processing": WARNING, "vad": INFO}
        col = colors.get(state, ACCENT)
        cx = 48
        # expanding pulse rings while recording
        if state == "recording":
            for k in range(3):
                t = (pulse + k / 3.0) % 1.0
                r = 34 + t * 9
                ring = lerp_color(col, BG, t * 0.9)
                c.create_oval(cx - r, cx - r, cx + r, cx + r,
                              outline=ring, width=2)
        # hover glow ring (any state)
        if getattr(self, "_btn_hover", False):
            c.create_oval(2, 2, 94, 94, outline=lerp_color(col, BG, 0.35),
                          width=2)
        # main disc with a soft outer halo
        c.create_oval(4, 4, 92, 92, outline=lerp_color(col, BG, 0.75), width=1)
        c.create_oval(8, 8, 88, 88, fill=col, width=0)
        if state == "recording":
            c.create_rectangle(38, 38, 58, 58, fill="white", width=0)
        else:
            c.create_oval(38, 38, 58, 58, fill="white", width=0)

    def _redirect_stdout(self):
        class UiStream:
            def __init__(self, app):
                self.app = app
            def write(self, s):
                if s.strip():
                    self.app.ui_queue.put(("log", s.rstrip()))
            def flush(self):
                pass
        sys.stdout = UiStream(self)

    def log(self, msg, tag=None):
        self.ui_queue.put(("log", msg, tag))

    # ------------------------------------------------------------- stats ----
    def _refresh_stats(self):
        try:
            row = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(AVG(latency_ms),0) FROM sessions"
            ).fetchone()
            self._stats = {"sessions": row[0], "words": row[1], "latency": round(row[2])}
        except Exception:
            pass

    def _refresh_stats_label(self):
        s = self._stats
        self.stats_label.config(
            text=f"{s['sessions']} sessions  ·  {s['words']} words  ·  {s['latency']} ms avg"
        )

    def _on_refresh_stats(self):
        self._refresh_stats()
        self._refresh_stats_label()

    # ------------------------------------------------------------- state ----
    STATUS_MAP = {
        "idle": ("IDLE", SUCCESS),
        "recording": ("RECORDING", ACCENT_GLOW),
        "processing": ("PROCESSING", WARNING),
        "loading": ("STARTING ASR", INFO),
        "vad": ("VAD ACTIVE", INFO),
    }

    def set_status(self, key):
        self.ui_queue.put(("status", key))

    def _apply_status(self, key):
        label, color = self.STATUS_MAP.get(key, self.STATUS_MAP["idle"])
        self.status_label.config(text=label, fg=color)
        self.status_dot.itemconfig("dot", fill=color)
        self._draw_record(key, getattr(self, "_pulse", 0.0))
        self._status = key
        vad = bool(self.core and self.core.vad_mode)
        self.mode_label.config(text="vad auto" if vad else "push-to-talk")
        hints = {
            "idle": "click, or press Ctrl+Alt+D",
            "recording": "recording — press Ctrl+Alt+D to stop",
            "processing": "transcribing…",
            "loading": "warming up Whisper engine…",
            "vad": "hands-free — just start speaking",
        }
        self.hint_label.config(text=hints.get(key, hints["idle"]))

    def on_level(self, rms, active):
        self.wave.set_level(rms / 3000.0, active)
        if self.hud:
            self.hud.set_level(rms)

    def _draw_waveform(self):
        self.wave.draw()
        if self.hud:
            self.hud.draw_meter()
        if self._status == "recording":
            self._pulse = (getattr(self, "_pulse", 0.0) + 0.05) % 1.0
            self._draw_record("recording", self._pulse)
        self.root.after(33, self._draw_waveform)

    # ------------------------------------------------------------ hotkeys ---
    def _register_hotkeys(self):
        self.core = FlowMini(self.config, self.db,
                             on_event=self._on_core_event, on_level=self.on_level)
        # Never treat our own window as a paste target.
        try:
            self.core.own_hwnd = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
        except Exception:
            pass
        # Sync the language picker with the core's configured language.
        if hasattr(self, "lang_combo"):
            try:
                self.lang_combo.set(LANG_DISPLAY.get(self.core.language, self.core.language))
            except Exception:
                pass
        if hasattr(self, "trans_toggle"):
            try:
                self.trans_toggle.set_state(self.core.translate_english)
            except Exception:
                pass
        if hasattr(self, "cleanup_combo"):
            try:
                self.cleanup_combo.set(self.core.cleanup_mode or "light")
            except Exception:
                pass
        if hasattr(self, "style_combo"):
            try:
                self.style_combo.set(self.core.style_preset or "casual")
            except Exception:
                pass
        if hasattr(self, "dev_toggle"):
            try:
                self.dev_toggle.set_state(bool(getattr(self.core, "developer_mode", False)))
            except Exception:
                pass
        if hasattr(self, "profiles_toggle"):
            try:
                self.profiles_toggle.set_state(
                    bool(getattr(self.core, "app_profiles_enabled", True)))
            except Exception:
                pass
        # Build specs, then let _HotkeyWindow register + pump them on one thread.
        self.hotkey_ids = {}
        self._register_count = 0
        specs = []
        names = [self.config["trigger_key"], self.config["vad_trigger_key"]]
        for i, key_name in enumerate(names):
            spec = KEY_MAP.get(key_name.lower())
            if not spec:
                self.log(f"Hotkey '{key_name}' unknown — see KEY_MAP", "err")
                continue
            mods, vk = spec
            self.hotkey_ids[i + 1] = i  # 0 = ptt, 1 = vad
            specs.append((i + 1, key_name, mods, vk))
        self._hotkey_win = _HotkeyWindow(specs, self._on_hotkey_registered, self._on_hotkey)
        self.log(f"Model: {self.core.model}  ·  Polisher: {'on' if self.core.use_polisher else 'off'}", "dim")
        if self.core.detect_language:
            self.log("Auto language detect ON — speak any language, it's recognized automatically", "dim")
            self.log(f"Default language: {self.core.language}", "dim")
        else:
            self.log(f"Language: {self.core.language} (manual — pick from the dropdown)", "dim")
        self._apply_status("idle")
        # Prewarm Whisper in the background so the FIRST dictation is instant.
        threading.Thread(target=self.core._load_whisper, daemon=True).start()

    def _on_hotkey_registered(self, hotkey_id, label, ok):
        # Called from the pump thread — marshal to the UI thread.
        self.ui_queue.put(("hotkey_reg", label, ok))

    def _handle_hotkey_registered(self, label, ok):
        if ok:
            self.log(f"Hotkey {label} ACTIVE", "ok")
        else:
            self.log(f"Hotkey {label} FAILED — change it in config.json", "err")

    def _on_hotkey(self, hotkey_id):
        which = self.hotkey_ids.get(hotkey_id)
        if which == 0:
            self.ui_queue.put(("action", "ptt"))
        elif which == 1:
            self.ui_queue.put(("action", "vad"))

    def _handle_action(self, action):
        if action == "ptt":
            self._toggle_ptt()
        elif action == "vad":
            self._toggle_vad()

    # ------------------------------------------------------------ actions ---
    def _toggle_ptt(self):
        if not self.core or self.core.vad_mode:
            return
        self.core.toggle_ptt()
        self.set_status("recording" if self.core.recording else "idle")

    def _toggle_vad(self):
        if not self.core:
            return
        self.core.toggle_vad()

    def _on_toggle_vad(self, on):
        if self.core and on != self.core.vad_mode:
            self.core.toggle_vad()

    def _on_language_change(self, _=None):
        if not self.core:
            return
        sel = self.lang_combo.get()
        # Display strings are "Label  —  code"; the BCP-47 CODE comes last.
        code = LANG_BY_DISPLAY.get(sel, "").strip() if sel else ""
        if not code or code == self.core.language:
            return
        self.core.language = code
        self.config["language"] = code
        # Manual pick OVERRIDES auto detect so the choice actually takes effect.
        # (Auto-detect stays on by default; picking a language opts into manual.)
        if self.core.detect_language:
            self.core.detect_language = False
            self.config["detect_language"] = False
        self.log(f"Speech language set to {code} (manual — auto detect off)", "ok")
        self._save_config_safe()

    def _on_translate_toggle(self, on):
        if not self.core:
            return
        self.core.translate_english = bool(on)
        self.config["translate_to_english"] = bool(on)
        mode = "ON — every language transcribes & pastes as English" if on else "OFF"
        self.log(f"Translate to English: {mode}", "ok")
        self._save_config_safe()

    def _on_cleanup_change(self, _=None):
        if not self.core:
            return
        mode = (self.cleanup_combo.get() or "light").lower()
        if mode not in ("off", "light", "medium"):
            mode = "light"
        self.core.cleanup_mode = mode
        self.config["cleanup_mode"] = mode
        self.log("Cleanup: " + {
            "off": "off — pastes the raw transcript",
            "light": "light — symbols, fillers, corrections & punctuation (offline, fast)",
            "medium": "medium — light + AI rewrite (slower, needs API key)",
        }.get(mode, mode), "ok")
        self._save_config_safe()

    def _on_style_change(self, _=None):
        if not self.core:
            return
        style = (self.style_combo.get() or "casual").lower()
        valid = ("formal", "casual", "very_casual", "excited")
        if style not in valid:
            style = "casual"
        self.core.style_preset = style
        self.config["style_preset"] = style
        labels = {
            "formal": "formal — professional, complete sentences",
            "casual": "casual — relaxed but correct",
            "very_casual": "very casual — conversational, chatty",
            "excited": "excited — energetic, exclamation marks",
        }
        self.log(f"Style: {labels.get(style, style)}", "ok")
        self._save_config_safe()

    def _on_developer_toggle(self, on):
        if not self.core:
            return
        self.core.developer_mode = bool(on)
        self.config["developer_mode"] = bool(on)
        mode = "ON — code vocabulary & formatting" if on else "OFF"
        self.log(f"Developer mode: {mode}", "ok")
        self._save_config_safe()

    def _on_profiles_toggle(self, on):
        """Day 3: per-app profiles — each app picks its own mode automatically."""
        if not self.core:
            return
        self.core.set_profiles_enabled(bool(on))
        self.config["app_profiles_enabled"] = bool(on)
        if on:
            n = len(getattr(self.core, "profiles", []) or [])
            self.log(f"Per-app profiles: ON — {n} rule(s) active "
                     "(editors → developer, mail → formal)", "ok")
        else:
            self.log("Per-app profiles: OFF — your global settings apply everywhere", "ok")
        self._save_config_safe()

    def _undo_paste(self):
        """One-step undo: paste the raw transcript that was just cleaned."""
        if not self.core:
            return
        raw = getattr(self, "_last_raw_paste", None)
        if not raw:
            return
        try:
            threading.Thread(target=lambda: self.core.paste_into_active_app(raw),
                             daemon=True).start()
            self.log("Undid transform — raw transcript pasted", "warn")
        except Exception as exc:
            self.log(f"Undo paste failed: {exc}", "err")

    def _save_config_safe(self):
        try:
            safe = {k: v for k, v in self.config.items() if k != "api_key"}
            with open(os.path.join(flow_mini.BASE_DIR, "config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(safe, fh, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _on_self_test(self):
        if not self.core:
            return
        self.log("--- Self-Test ---", "dim")
        threading.Thread(target=self.core.run_self_test, daemon=True).start()

    def _on_core_event(self, event, data=None):
        self.ui_queue.put(("core_event", event, data))

    # ----------------------------------------------------------------- HUD --
    def _hud_show(self, state, text=None):
        """Lazily create the floating HUD and show it (no-op if disabled)."""
        if not self.config.get("show_hud", True):
            return
        try:
            if self.hud is None:
                self.hud = DictationHud()
            if self._hud_hide_job:
                self.root.after_cancel(self._hud_hide_job)
                self._hud_hide_job = None
            self.hud.show(state, text)
            if state != "recording":
                # 10s auto-hide backstop: any card whose events stop arriving
                # removes itself (the loading card used to pin forever).
                # "recording" is exempt — it lives until the state machine
                # moves on to processing/pasted/idle, each of which re-arms.
                self._hud_hide_later(HUD_AUTO_HIDE_MS)
        except Exception as exc:
            self.log(f"HUD unavailable: {exc}", "err")
            self.hud = None

    def _hud_hide_later(self, ms):
        if self.hud is None or not self.hud.visible:
            return
        if self._hud_hide_job:
            try:
                self.root.after_cancel(self._hud_hide_job)
            except Exception:
                pass
        self._hud_hide_job = self.root.after(ms, self._hud_hide)

    def _hud_hide(self):
        self._hud_hide_job = None
        if self.hud:
            self.hud.hide()

    def _hud_profile_chip(self):
        """The active per-app profile name for the HUD sub-line ('' = default)."""
        try:
            return ((getattr(self.core, "active_profile", None) or {}).get("name")
                    or "")
        except Exception:
            return ""

    def _hud_sync(self, event, data):
        """Mirror the core's state machine onto the floating HUD."""
        if event == "recording_started":
            self._hud_show("recording", self._hud_profile_chip())
        elif event == "recording_stopped":
            self._hud_show("processing", "transcribing…")
        elif event == "whisper_loading":
            self._hud_show("loading", "first run downloads the model once (~1.5 GB)")
        elif event == "model_download":
            self._hud_show("loading", (data or {}).get("text") or "downloading model…")
        elif event == "asr_text" and self.hud:
            self.hud.set_text((data.get("raw") or "") if data else "")
        elif event == "pasted":
            polished = (data.get("polished") or data.get("raw") or "") if data else ""
            self._hud_show("pasted", polished)
            self._hud_hide_later(2600)
        elif event == "paste_failed":
            self._hud_show("clipboard", "focus moved away — click your app, press Ctrl+V")
            self._hud_hide_later(5000)
        elif event == "idle":
            self._hud_hide_later(1200)

    def _handle_core_event(self, event, data=None):
        self._hud_sync(event, data)
        if event == "recording_started":
            self.set_status("recording")
            self._set_transcript("", "", placeholder="Listening…")
        elif event == "recording_stopped":
            self.set_status("processing")
            self._set_transcript("", "", placeholder="Transcribing…")
        elif event == "processing":
            self.set_status("processing")
        elif event == "whisper_loading":
            self.set_status("loading")
            self._set_transcript("", "", placeholder="Loading Whisper engine (first run downloads the model)…")
        elif event == "model_download":
            self.set_status("loading")
            self._set_transcript("", "", placeholder=(data or {}).get("text") or "Downloading model…")
        elif event == "whisper_ready":
            # model finished loading — leave the loading state for real
            # (previously nothing cleared it, so the status/HUD sat on
            # "STARTING ASR" until the first completed dictation)
            was_loading = getattr(self, "_status", None) == "loading"
            self.set_status("vad" if (self.core and self.core.vad_mode) else "idle")
            if self.hud and self.hud.visible:
                self._hud_hide()
            if was_loading:
                self._set_transcript("", "", placeholder="nothing dictated yet")
        elif event == "stage":
            if data:
                name = data.get("stage", "ASR")
                secs = data.get("seconds", 0.0)
                lang = data.get("lang") or ""
                conf = data.get("lang_conf") or 0.0
                conf_s = f"  ·conf {int(conf * 100)}%" if conf >= 0.5 else ""
                self.log(f"{name} — {secs:.1f}s" + (f"  ·detected language: {lang}" if lang else "") + conf_s, "dim")
                self.hint_label.config(text=f"{name} {secs:.1f}s…")
        elif event == "busy":
            self.hint_label.config(text="Still processing — wait a moment…")
            self.log("Still processing previous dictation — press again in a moment", "dim")
        elif event == "profile":
            self._handle_profile_event(data)
        elif event == "asr_text":
            # Raw transcript is ready (~1s) — show it instantly so the UI never
            # feels frozen while cleaning finishes in the background.
            self.set_status("processing")
            self.hint_label.config(text="Cleaning…")
            raw = (data.get("raw") or "") if data else ""
            self._set_transcript(raw, raw)
        elif event == "idle":
            self.set_status("vad" if (self.core and self.core.vad_mode) else "idle")
            self._set_transcript("", "", placeholder="No speech detected — speak up, or check your mic in Windows Sound settings")
        elif event == "pasted":
            self.set_status("vad" if (self.core and self.core.vad_mode) else "idle")
            self._refresh_stats()
            self._refresh_stats_label()
            raw = (data.get("raw") or "") if data else ""
            polished = (data.get("polished") or "") if data else ""
            english = (data.get("english") or "") if data else ""
            self._set_transcript(raw, polished, english)
            if data:
                edits = data.get("edits") or []
                c = data.get("cleanup") or ""
                extra = ""
                if data.get("lang_decision") and data["lang_decision"] == "ambiguous":
                    extra += " ·language unclear, no cleanup"
                if edits:
                    extra += f" ·{len(edits)} edit(s): " + ", ".join(
                        {"spoken_command": "symbol", "filler_removed": "filler",
                         "correction": "correction", "formatting": "rewrite"}
                        .get(e.get("type"), e.get("type", "edit")) for e in edits)
                if data.get("profile"):
                    extra += f" ·profile {data['profile']}"
                self.log(f"Pasted — {data['words']} words, {data['latency_ms']} ms "
                         f"({data['mode']}) ·cleanup {c}{extra}", "ok")
            # one-step undo: remember the raw version in case the user needs it
            self._last_raw_paste = raw if (raw and raw != polished) else None
            try:
                self.btn_undo.config(state="normal" if self._last_raw_paste else "disabled")
            except Exception:
                pass
        elif event == "vad_on":
            self.set_status("vad")
            self.toggle.set_state(True)
            self.log("VAD ON — speak naturally, stops on silence", "ok")
        elif event == "vad_off":
            self.set_status("idle")
            self.toggle.set_state(False)
            self.log("VAD OFF", "dim")

    def _handle_profile_event(self, data):
        """Day 3: log when a per-app profile activates or drops back to default."""
        data = data or {}
        name = data.get("name")
        enabled = bool(getattr(self.core, "app_profiles_enabled", True))
        if not name:
            # Turning profiles off already logs its own line — don't double it.
            if enabled:
                self.log("Profile: default — your global settings apply here", "dim")
            return
        bits = []
        overrides = data.get("overrides") or {}
        if "developer_mode" in overrides:
            bits.append("developer mode " + ("on" if overrides["developer_mode"] else "off"))
        if "style_preset" in overrides:
            bits.append(f"style {overrides['style_preset']}")
        if "cleanup_mode" in overrides:
            bits.append(f"cleanup {overrides['cleanup_mode']}")
        app = data.get("app") or ""
        msg = f"Profile '{name}'" + (f" · {app}" if app else "")
        if bits:
            msg += " · " + ", ".join(bits)
        self.log(msg, "dim")

    def _set_transcript(self, raw, polished, english=None, placeholder=None):
        text = polished or raw or placeholder or "nothing dictated yet"
        # placeholders (listening / thinking / idle) read as muted captions,
        # real dictation reads as primary text
        self.transcript_text.config(
            fg=TEXT_PRIMARY if (polished or raw) else TEXT_MUTED)
        self._tw_text = text
        self._tw_idx = 0
        self.transcript_text.config(text="")
        # secondary line: the "heard" pronunciation + optional script / meaning
        detected = None
        conf = 0.0
        try:
            detected = self.core._last_detected_lang if self.core else None
            conf = getattr(self.core, "_last_lang_conf", 0.0) if self.core else 0.0
        except Exception:
            pass
        self.transcript_raw.config(
            text=format_heard(raw, english, detected, conf) if raw else "")
        if self._typewriter_job:
            try:
                self.root.after_cancel(self._typewriter_job)
            except Exception:
                pass
            self._typewriter_job = None
        self._typewrite()

    def _typewrite(self):
        text = getattr(self, "_tw_text", "")
        idx = getattr(self, "_tw_idx", 0)
        if idx <= len(text):
            self.transcript_text.config(text=text[:idx])
            self._tw_idx = idx + 1
            self._typewriter_job = self.root.after(18, self._typewrite)
        else:
            self._typewriter_job = None

    # -------------------------------------------------------------- pump ----
    def _pump_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                if item[0] == "log":
                    self._append_log(item[1], item[2] if len(item) > 2 else None)
                elif item[0] == "status":
                    self._apply_status(item[1])
                elif item[0] == "core_event":
                    self._handle_core_event(item[1], item[2])
                elif item[0] == "action":
                    self._handle_action(item[1])
                elif item[0] == "hotkey_reg":
                    self._handle_hotkey_registered(item[1], item[2])
        except queue.Empty:
            pass
        self.root.after(50, self._pump_ui_queue)

    def _append_log(self, text, tag=None):
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n", tag or ())
        self.log_box.see("end")
        if int(self.log_box.index("end-1c").split(".")[0]) > 300:
            self.log_box.delete("1.0", "50.0")
        self.log_box.config(state="disabled")

    # -------------------------------------------------------------- tray ----
    def _make_icon(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (64, 64), (12, 12, 18))
        d = ImageDraw.Draw(img)
        d.ellipse([14, 14, 50, 50], fill=(230, 57, 70))
        d.ellipse([24, 24, 40, 40], fill=(12, 12, 18))
        return img

    def start_tray(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("FlowMini — Voice Dictation", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show window", lambda i, _: self._show_window()),
            pystray.MenuItem("Hide window", lambda i, _: self._hide_to_tray()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Dictation", lambda i, _: self._toggle_ptt()),
            pystray.MenuItem("Toggle VAD", lambda i, _: self._toggle_vad()),
            pystray.MenuItem("Run Self-Test", lambda i, _: self._on_self_test()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i, _: self._quit()),
        )
        self._tray = pystray.Icon("flowmini", self._make_icon(),
                                  "FlowMini — Voice Dictation", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _hide_to_tray(self):
        self.root.withdraw()
        self.log("Hidden to tray — hotkeys still active", "dim")

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()

    def _quit(self):
        if self._hotkey_win:
            self._hotkey_win.close()
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.root.destroy()
        os._exit(0)

    def run(self):
        self.start_tray()
        print("FlowMini app started")
        self.root.mainloop()


def stt_selftest():
    """CLI mode: run the real STT path on synthetic audio and write a report.
    Used to verify the packaged exe bundles faster-whisper correctly."""
    import time as _t
    import numpy as np
    from flow_mini import FlowMini, load_config
    cfg = load_config()
    core = FlowMini(cfg, None, on_event=lambda e, d=None: None)
    sr_ = core.sample_rate
    t = np.arange(sr_ * 7) / sr_
    sig = (np.sin(2 * np.pi * 220 * t) *
           (0.35 + 0.65 * np.abs(np.sin(2 * np.pi * 0.9 * t))) * 12000).astype(np.int16)
    t0 = _t.monotonic()
    text = None
    try:
        text = core.transcribe_audio(sig)
    except Exception as exc:
        print(f"[SelfTest] transcribe raised: {exc}")
    # Verify the Silero VAD voice-isolation model ships with the frozen app.
    silero_ok = False
    try:
        from faster_whisper.utils import get_assets_path
        silero_ok = os.path.exists(os.path.join(get_assets_path(), "silero_vad_v6.onnx"))
    except Exception as exc:
        print(f"[SelfTest] silero check failed: {exc}")
    # Verify the deterministic Speech Transform Engine ships and works.
    transform_ok = False
    try:
        tres = core._transform("open square bracket x close square bracket", "en", 0.99)
        transform_ok = tres.finalText == "[x]"
    except Exception as exc:
        print(f"[SelfTest] transform check failed: {exc}")
    # Verify the offline pronunciation romanizer (translit) ships and works.
    translit_ok = False
    try:
        translit_ok = flow_mini.romanize("नमस्ते", "hi") == "namaste"
    except Exception as exc:
        print(f"[SelfTest] translit check failed: {exc}")
    report = {
        "ok": text is not None,
        "total_s": round(_t.monotonic() - t0, 2),
        "engine": core.stt_engine,
        "model": core.stt_model,
        "silero_vad": silero_ok,
        "transform_engine": transform_ok,
        "translit": translit_ok,
        "cleanup_mode": core.cleanup_mode,
        "recognized": text,
    }
    out = os.path.join(flow_mini.BASE_DIR, "stt_selftest.txt")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"[SelfTest] STT result: {report}")
    return 0


_SINGLE_INSTANCE_MUTEX_NAME = "FlowMini_SingleInstance_Mutex"
_g_single_instance_handle = None  # keeps the OS handle alive for the process lifetime
_kernel32 = None


def _kernel32_lib():
    """kernel32 loaded with use_last_error so error codes are reliable."""
    global _kernel32
    if _kernel32 is None:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        _kernel32.CreateMutexW.restype = ctypes.c_void_p
        _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        _kernel32.CloseHandle.restype = ctypes.c_int
    return _kernel32


def _acquire_single_instance_mutex(name=_SINGLE_INSTANCE_MUTEX_NAME):
    """Ensure only one FlowMini instance runs at a time (Windows).

    Double-clicking a one-file PyInstaller exe while the first copy is
    still unpacking spawns a second instance; several instances then race
    for the global hotkey and the microphone, and dictation breaks in
    ways that look like random bugs. A named OS mutex makes exactly one
    instance win; the OS releases it automatically when that process
    exits, so quitting FlowMini always unblocks the next launch.

    Returns an OS handle (int) on success, the string "exists" when
    another instance already holds the mutex, or None on non-Windows
    platforms / if the mutex API is unavailable (app still allowed to
    run — the guard must never become the reason the app won't start).
    """
    global _g_single_instance_handle
    if sys.platform != "win32":
        return None
    if os.environ.get("FLOWMINI_MULTI") == "1":
        # Explicit opt-out for automated tests / multiple dev copies.
        return None
    try:
        k32 = _kernel32_lib()
        handle = k32.CreateMutexW(None, False, name)
    except Exception:
        return None
    if not handle:
        return None
    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        k32.CloseHandle(handle)
        return "exists"
    _g_single_instance_handle = handle
    return handle


def _tell_already_running():
    """Show a short notice when a second instance is blocked.

    Uses the raw Win32 MessageBox (no Tk) — in a frozen windowed exe a
    second instance must be able to show this without building a whole
    Tk runtime, and it must survive even if Tk misbehaves.
    """
    try:
        MB_OK = 0x00000000
        MB_ICONINFORMATION = 0x00000040
        MB_TOPMOST = 0x00040000
        MB_SETFOREGROUND = 0x00010000
        user32 = ctypes.windll.user32
        user32.MessageBoxW(
            None,
            "FlowMini is already running on this computer.\n\n"
            "Look for its window or the tray icon near the clock, and use "
            "Ctrl+Alt+D to start/stop dictation.\n\n"
            "(A second copy was blocked: two instances would fight over "
            "the microphone and the Ctrl+Alt+D hotkey.)",
            "FlowMini already running",
            MB_OK | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND,
        )
    except Exception:
        print("[FlowMini] Another instance is already running - exiting.")


def main():
    if "--selftest-stt" in sys.argv:
        raise SystemExit(stt_selftest())
    guard = _acquire_single_instance_mutex()
    if guard == "exists":
        _tell_already_running()
        return
    FlowMiniApp().run()


if __name__ == "__main__":
    main()
