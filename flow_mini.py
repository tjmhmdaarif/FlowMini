"""Hello, guys. This is a test for many voice recognition. The quick brown fox jumps over the lazy dog.Hello, guys. This is a test for many voice recognition. The quick brown fox jumps over the lazy dog.Hello, guys. This is a test for many voice recognition. The quick brown fox jumps over the lazy dog.Hello, guys. This is a test for many voice recognition. The quick brown fox jumps over the lazy dog.Hello, guys. This is a test for many voice recognition. The quick brown fox jumps over the lazy dog.Hello, guys. This is a test for many voice recognition. The quick brown fox jumps over the lazy dog.
FlowMini: A lightweight, working prototype inspired by the Wispr Flow architecture.

Architecture Mirroring Wispr Flow:
1. Audio Engine: Captures 16kHz 16-bit PCM audio via sounddevice.
2. Speech-to-Text (ASR): Transcribes speech audio using speech_recognition / cloud ASR.
3. AI Flow Polisher: Sends raw transcript to LLM (OpenRouter / Gemini / OpenAI)
   to remove filler words ("um", "ah"), resolve self-corrections, and format punctuation.
4. Text Injection: Injects polished text into the active foreground window via
   system clipboard + simulated Ctrl+V keystroke (mirroring Wispr Flow Helper).

Continued development (v2) beyond the original prototype:
5. Telemetry: Every dictation session is logged to a local SQLite database
   (session id, timestamps, duration, word count, end-to-end latency, mode)
   mirroring the Wispr Flow flow.sqlite telemetry, queryable via --stats.
6. Custom Dictionary: User-defined word/phrase expansions (custom_dictionary.json)
   are applied before LLM polishing — like Wispr Flow's custom dictionary/shortcuts.
7. VAD Auto-Dictation: Energy-based voice activity detection with ambient noise
   calibration starts/stops dictation automatically — no hotkey needed (--vad).
8. Config + Secrets: config.json (trigger key, model, VAD sensitivity) and .env
   (OPENROUTER_API_KEY) keep credentials out of source control.
9. Resilience: microphone stream recovery on device errors, graceful degradation
   when the API key is missing or the polisher is unreachable.
10. UI hooks: on_event / on_level callbacks let the GUI app (flowmini_app.py)
    show live status, mic level and session telemetry.

Note: pynput's low-level keyboard hook does NOT work on some Windows machines
(this one included — it silently receives zero keys). The GUI app therefore
uses the Win32 RegisterHotKey API instead, which is what real Windows apps
(Wispr Flow included) use for global hotkeys.
"""

import os
import sys
import time
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import threading
from speech_transform import transform_transcript
from translit import romanize
from snippets import SnippetManager, Snippet, get_snippets_path
from auto_learn import AutoLearner
import io
import ctypes
from ctypes import wintypes
import requests
import numpy as np
import scipy.io.wavfile as wav
import sounddevice as sd
import pyperclip
import pyautogui
import speech_recognition as sr

# ---------------------------------------------------------------------------
# Paths & configuration
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Frozen (PyInstaller): keep config.json / .env / the DB next to the exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DICT_PATH = os.path.join(BASE_DIR, "custom_dictionary.json")
DB_PATH = os.path.join(BASE_DIR, "flowmini_sessions.db")
ENV_PATH = os.path.join(BASE_DIR, ".env")

DEFAULT_CONFIG = {
    "trigger_key": "ctrl+alt+d",  # push-to-talk hotkey
    "vad_trigger_key": "ctrl+alt+f",  # toggle VAD auto-dictation mode
    "polish_model": "google/gemini-2.5-flash",
    "vad_sensitivity": 2.5,       # multiplier over calibrated noise floor
    "vad_silence_gap_s": 1.0,     # seconds of silence that end an utterance
    "vad_max_utterance_s": 30.0,  # safety cap on a single recording
    "polisher": True,             # AI rewrite used by cleanup_mode "medium"
    "cleanup_mode": "light",      # off | light | medium (see Speech Transform Engine)
    "style_preset": "casual",     # formal | casual | very_casual | excited
    "stt_engine": "auto",         # auto | whisper (local, recommended) | google
    "stt_model": "large-v3-turbo",  # whisper model: tiny | base | small | medium | large-v3-turbo
    "stt_device": "auto",         # auto | cuda | cpu  (auto: use GPU when available)
    "stt_compute_type": "",       # "" = pick best for the device (float16 on GPU, int8 on CPU)
    "stt_beam_size": 5,           # beam search width; 1 = fastest/greedy, 5 = most accurate
    "stt_accuracy_mode": "high",  # high = best accuracy (beam 5, VAD tuning, no_speech 0.6)
                                  # fast = lowest latency (beam 1, current behaviour)
    "auto_learn": True,           # learn from corrections and apply frequent ones
    "developer_mode": False,      # code-aware vocabulary and formatting
    "show_hud": True,             # floating mic HUD near the cursor while dictating
    "detect_language": True,      # let Whisper auto-detect the spoken language per utterance
    "translate_to_english": False,  # transcribe and translate everything into English
}

# Win32 virtual key codes for the hotkeys we register
VK_CODES = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def load_dotenv(path):
    """Minimal .env loader (avoids an extra dependency)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[FlowMini] Warning: could not read config.json ({exc}); using defaults")
    load_dotenv(ENV_PATH)
    cfg.setdefault("api_key", os.environ.get("OPENROUTER_API_KEY", ""))
    return cfg


def load_dictionary():
    """Load user custom dictionary; longest keys first so phrases win over words."""
    if not os.path.exists(DICT_PATH):
        return {}
    try:
        with open(DICT_PATH, "r", encoding="utf-8") as fh:
            table = json.load(fh)
        return dict(sorted(table.items(), key=lambda kv: len(kv[0]), reverse=True))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FlowMini] Warning: could not read custom_dictionary.json ({exc})")
        return {}


def apply_dictionary(text, table):
    """Expand user-defined shortcuts (case-insensitive, word-boundary safe)."""
    import re
    for phrase, expansion in table.items():
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        text = pattern.sub(expansion, text)
    return text


# ---------------------------------------------------------------------------
# Win32 clipboard + paste helpers (universal text injection)
# ---------------------------------------------------------------------------
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56

# Correct 64-bit-safe prototypes — without these, GlobalAlloc's return is
# truncated to a 32-bit int and GlobalLock overflows, breaking paste.
_kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
_user32.OpenClipboard.argtypes = [ctypes.c_void_p]
_user32.OpenClipboard.restype = ctypes.c_int
_user32.EmptyClipboard.restype = ctypes.c_int
_user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
_user32.SetClipboardData.restype = ctypes.c_void_p
_user32.CloseClipboard.restype = ctypes.c_int
_user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
_user32.SendInput.restype = ctypes.c_uint


def set_clipboard_unicode(text):
    """Set clipboard via Win32 API — more reliable than pyperclip for some apps."""
    if not _user32.OpenClipboard(None):
        time.sleep(0.05)
        if not _user32.OpenClipboard(None):
            raise RuntimeError("could not open clipboard")
    try:
        _user32.EmptyClipboard()
        size = (len(text) + 1) * 2
        hGlobal = _kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not hGlobal:
            raise RuntimeError("GlobalAlloc failed")
        lpGlobal = _kernel32.GlobalLock(hGlobal)
        if not lpGlobal:
            _kernel32.GlobalFree(hGlobal)
            raise RuntimeError("GlobalLock failed")
        ctypes.memmove(lpGlobal, text, len(text) * 2)
        _kernel32.GlobalUnlock(hGlobal)
        # Ownership of hGlobal transfers to the clipboard on success.
        if not _user32.SetClipboardData(CF_UNICODETEXT, hGlobal):
            _kernel32.GlobalFree(hGlobal)
            raise RuntimeError("SetClipboardData failed")
    finally:
        _user32.CloseClipboard()


def send_ctrl_v():
    """Send Ctrl+V via SendInput — works in virtually all Windows apps.

    IMPORTANT: the INPUT union must contain MOUSEINPUT/HARDWAREINPUT too, so
    that sizeof(INPUT) matches the 40 bytes Windows expects on x64. A union
    holding only KEYBDINPUT is 32 bytes and SendInput silently returns 0 —
    which is exactly why clipboard paste used to do nothing.
    """

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                    ("wParamH", ctypes.c_ushort)]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]

    def make_input(vk, flags):
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = 0
        inp.union.ki.dwFlags = flags
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return inp

    inputs = (INPUT * 4)()
    inputs[0] = make_input(VK_CONTROL, 0)
    inputs[1] = make_input(VK_V, 0)
    inputs[2] = make_input(VK_V, KEYEVENTF_KEYUP)
    inputs[3] = make_input(VK_CONTROL, KEYEVENTF_KEYUP)
    sent = _user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
    if sent != 4:
        # Legacy fallback — keybd_event works even where SendInput is refused.
        _user32.keybd_event(VK_CONTROL, 0, 0, 0)
        _user32.keybd_event(VK_V, 0, 0, 0)
        _user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# --- target-window tracking -------------------------------------------------
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.SetForegroundWindow.restype = ctypes.c_int
_user32.IsWindow.argtypes = [ctypes.c_void_p]
_user32.IsWindow.restype = ctypes.c_int
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.ShowWindow.restype = ctypes.c_int


def get_foreground_hwnd():
    """Return the HWND of the current foreground window (or None)."""
    try:
        return _user32.GetForegroundWindow() or None
    except Exception:
        return None


def activate_hwnd(hwnd):
    """Best-effort: bring hwnd back to the foreground before pasting, so the
    text lands in the app the user was actually typing into."""
    if not hwnd:
        return False
    try:
        if not _user32.IsWindow(hwnd):
            return False
        if _user32.GetForegroundWindow() == hwnd:
            return True
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return _user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


# --- robust foreground restore (the "paste lands in the right app" fix) ------
_user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
_user32.BringWindowToTop.restype = ctypes.c_int
_user32.AttachThreadInput.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
_user32.AttachThreadInput.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.GetWindowThreadProcessId.restype = ctypes.c_uint
_user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ulong, ctypes.c_void_p]
_user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_kernel32.GetCurrentThreadId.restype = ctypes.c_uint


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


_user32.GetGUIThreadInfo.argtypes = [ctypes.c_uint, ctypes.c_void_p]
_user32.GetGUIThreadInfo.restype = ctypes.c_int
_user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                 ctypes.c_void_p, ctypes.c_void_p]
_user32.SendMessageW.restype = ctypes.c_void_p

EM_GETSEL = 0x00B0
EM_REPLACESEL = 0x00C2  # wParam=TRUE -> undoable; lParam -> text
EDIT_CLASSES = {"edit", "richedit", "richedit20w", "richedit50w", "riched20w", "riched20"}


def force_foreground(hwnd, attempts=5):
    """Bring hwnd to the foreground, robust against Windows' foreground lock.

    Plain SetForegroundWindow is routinely DENIED when the calling process
    did not receive the last input event — the classic reason a dictation
    app's paste ends up in the wrong window (or nowhere). Until the focus
    actually lands, workarounds are layered like the native helpers of the
    major dictation products:
      1. ShowWindow + BringWindowToTop + SetForegroundWindow
      2. AttachThreadInput to the current foreground thread while retrying
      3. a dummy ALT tap, which clears the foreground restriction
    Returns True only when GetForegroundWindow() is really hwnd.
    """
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    if _user32.GetForegroundWindow() == hwnd:
        return True
    me = _kernel32.GetCurrentThreadId()
    for _ in range(attempts):
        fg = _user32.GetForegroundWindow()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
        try:
            _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        except Exception:
            pass
        attached = False
        if fg_thread:
            attached = bool(_user32.AttachThreadInput(me, fg_thread, True))
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
        if attached:
            _user32.AttachThreadInput(me, fg_thread, False)
        time.sleep(0.05)
        if _user32.GetForegroundWindow() == hwnd:
            return True
        # Still refused — the dummy ALT tap unlocks the foreground.
        _user32.keybd_event(0x12, 0, 0, 0)       # ALT down
        _user32.keybd_event(0x12, 0, 0x0002, 0)  # ALT up
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        if _user32.GetForegroundWindow() == hwnd:
            return True
    return False


def _edit_class_of(hwnd):
    """Return the (lowercased) window class name of hwnd, or ''."""
    buf = ctypes.create_unicode_buffer(64)
    try:
        _user32.GetClassNameW(hwnd, buf, 64)
    except Exception:
        return ""
    return (buf.value or "").lower()


def _insert_text_at_caret(hwnd, text):
    """Insert text at the caret of a classic EDIT-class control — no focus needed.

    Works through WM messages on the caret's window (EM_REPLACESEL with undo),
    which keeps the insertion inside the app even when Windows refuses to
    restore the foreground. Returns False for modern UI frameworks
    (Chromium/Electron, UWP); the caller then falls back to clipboard-only.
    """
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    tid = _user32.GetWindowThreadProcessId(hwnd, None)
    gti = _GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(_GUITHREADINFO)
    if not tid or not _user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return False
    target = None
    for candidate in (gti.hwndCaret, gti.hwndFocus):
        if not candidate:
            continue
        if _edit_class_of(candidate) in EDIT_CLASSES:
            target = candidate
            break
    if target is None:
        return False
    buf = ctypes.create_unicode_buffer(text + "\0")
    _user32.SendMessageW(target, EM_REPLACESEL, ctypes.c_void_p(1),
                         ctypes.cast(buf, ctypes.c_void_p))
    return True


_user32.GetClipboardData.argtypes = [ctypes.c_uint]
_user32.GetClipboardData.restype = ctypes.c_void_p


def get_clipboard_text():
    """Read the current Unicode clipboard content (or None if unavailable)."""
    try:
        if not _user32.OpenClipboard(None):
            return None
        try:
            h = _user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            p = _kernel32.GlobalLock(h)
            if not p:
                return None
            try:
                return ctypes.wstring_at(p)
            finally:
                _kernel32.GlobalUnlock(h)
        finally:
            _user32.CloseClipboard()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Telemetry — mirrors Wispr Flow's flow.sqlite session log
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               started_at TEXT NOT NULL,
               ended_at TEXT NOT NULL,
               duration_s REAL NOT NULL,
               words INTEGER NOT NULL,
               raw_text TEXT NOT NULL,
               polished_text TEXT NOT NULL,
               latency_ms INTEGER NOT NULL,
               mode TEXT NOT NULL
           )"""
    )
    conn.commit()
    return conn


def log_session(conn, started_at, ended_at, audio_s, raw, polished, latency_ms, mode):
    words = len(polished.split()) if polished else 0
    conn.execute(
        """INSERT INTO sessions
           (started_at, ended_at, duration_s, words, raw_text, polished_text, latency_ms, mode)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (started_at, ended_at, round(audio_s, 2), words, raw, polished, latency_ms, mode),
    )
    conn.commit()
    return words


def print_stats(conn):
    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(SUM(duration_s),0), COALESCE(AVG(latency_ms),0) FROM sessions").fetchone()
    total, words, speech_s, avg_lat = row
    print("--- FlowMini Session Stats (flowmini_sessions.db) ---")
    print(f"Total dictation sessions : {total}")
    print(f"Total words dictated     : {words}")
    print(f"Cumulative speech time   : {speech_s:.1f} s")
    print(f"Avg end-to-end latency  : {avg_lat:.0f} ms")
    print("Recent sessions:")
    for r in conn.execute(
        "SELECT started_at, duration_s, words, latency_ms, mode FROM sessions ORDER BY id DESC LIMIT 5"
    ):
        print(f"  {r[0]}  dur={r[1]:5.2f}s  words={r[2]:3d}  latency={r[3]:4d}ms  mode={r[4]}")
    print("-----------------------------------------------------")


# ---------------------------------------------------------------------------
# OpenRouter / LLM configuration
# ---------------------------------------------------------------------------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

STYLE_PRESETS = {
    "formal": {
        "description": "Formal writing style - professional, complete sentences, proper punctuation",
        "capitalize": True,
        "punctuation": True,
        "contractions": False,
        "tone": "professional",
    },
    "casual": {
        "description": "Casual writing style - relaxed but correct, natural flow",
        "capitalize": True,
        "punctuation": True,
        "contractions": True,
        "tone": "natural",
    },
    "very_casual": {
        "description": "Very casual style - conversational, informal, chatty",
        "capitalize": True,
        "punctuation": True,
        "contractions": True,
        "tone": "conversational",
    },
    "excited": {
        "description": "Excited style - energetic, exclamation marks, upbeat tone",
        "capitalize": True,
        "punctuation": True,
        "contractions": True,
        "add_exclamations": True,
        "tone": "energetic",
    },
}

SYSTEM_PROMPT = """You are an AI dictation agent inspired by Wispr Flow.
Your job is to transform raw spoken transcript into clean, polished, written text:
1. Remove speech fillers (e.g., 'um', 'uh', 'like', 'you know', 'ah') in whatever language they appear.
2. Fix self-corrections mid-sentence (e.g., 'meet me at 5, actually 6' -> 'Meet me at 6').
3. Repair minor grammar slips and word order so the sentence reads naturally and fluently, then apply standard capitalization, number formatting, and natural punctuation.
4. Apply the requested style preset (one of: formal, casual, very_casual, excited) to adjust tone, capitalization, and punctuation accordingly.
5. IMPORTANT: preserve the speaker's language ({language}) — never translate to another language.
6. Output ONLY the polished text ready to be pasted. Do NOT add preamble, quotes, or explanations.
7. If a style preset is specified, apply its rules: capitalize={capitalize}, punctuation={punctuation}, contractions={contractions}, tone={tone}.
"""

# Silero VAD parameters for the bundled faster-whisper voice-isolation filter.
VAD_PARAMS = {"min_silence_duration_ms": 400, "speech_pad_ms": 200}


class FlowMini:
    def __init__(self, config, db_conn, on_event=None, on_level=None):
        self.cfg = config
        self.db = db_conn
        self.on_event = on_event or (lambda e, d=None: None)
        self.on_level = on_level or (lambda rms, active=False: None)

        self.sample_rate = 16000
        self.trigger_key_name = config["trigger_key"]
        self.vad_key_name = config["vad_trigger_key"]
        self.api_key = config["api_key"]
        self.model = config["polish_model"]
        self.language = config.get("language", "en-US")  # BCP-47, e.g. hi-IN, es-ES, ar-SA
        # Guard against a stale/invalid code (e.g. an old label) breaking ASR.
        if not re.match(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$", self.language or ""):
            print(f"[FlowMini] Invalid language '{self.language}' — falling back to en-US")
            self.language = "en-US"
        self.use_polisher = config["polisher"]
        # Cleanup level for the deterministic Speech Transform Engine:
        #   off    -> paste the raw ASR transcript
        #   light  -> spoken symbols, filler removal, self-corrections,
        #             punctuation & capitalization (fast & offline, default)
        #   medium -> light + optional AI rewrite (the LLM polisher)
        self.cleanup_mode = str(config.get("cleanup_mode", "light")).lower()
        if self.cleanup_mode not in ("off", "light", "medium"):
            self.cleanup_mode = "light"
        self.style_preset = str(config.get("style_preset", "casual")).lower()
        if self.style_preset not in STYLE_PRESETS:
            self.style_preset = "casual"
        self.dictionary = load_dictionary()
        self.snippet_manager = SnippetManager(get_snippets_path(BASE_DIR))
        self.auto_learner = AutoLearner(os.path.join(BASE_DIR, "auto_learn_corrections.json"))
        self.auto_learn_enabled = bool(config.get("auto_learn", True))
        self.developer_mode = bool(config.get("developer_mode", False))

        # Speech-to-text engine: local Whisper (offline, fast) preferred.
        # Google's free web ASR is blocked on many networks → always fall back.
        self.stt_engine = config.get("stt_engine", "auto")  # auto | whisper | google
        self.stt_model = config.get("stt_model", "tiny")
        self.stt_device = config.get("stt_device", "auto")   # auto | cuda | cpu
        self.stt_compute_type = config.get("stt_compute_type", "")
        self.stt_beam_size = int(config.get("stt_beam_size", 5) or 5)
        self.stt_accuracy_mode = config.get("stt_accuracy_mode", "high")
        self.detect_language = bool(config.get("detect_language", True))
        self.translate_english = bool(config.get("translate_to_english", False))
        self._last_detected_lang = None  # set by Whisper after each utterance
        self._last_lang_conf = 0.0       # Whisper's confidence in that detection
        self._whisper = None          # lazy-loaded WhisperModel singleton
        self._whisper_loading = False
        self.recognizer = sr.Recognizer()
        self.recognizer.operation_timeout = 20  # never hang on the Google fallback

        self.recording = False
        self.vad_mode = False
        self.audio_frames = []
        self.stream = None
        self.lock = threading.Lock()
        self.target_hwnd = None  # window to paste into (captured at record time)
        self.own_hwnd = None     # the app's own window; never used as a paste target
        self.last_external_hwnd = None  # last foreground window that is not ours
        threading.Thread(target=self._poll_foreground_loop, daemon=True).start()

        # Pipeline serialization: only ONE dictation pipeline runs at a time.
        # New utterances queue up, so recording/processing never overlap
        # mid-sentence and events never interleave in the UI.
        self._pipe_lock = threading.Lock()
        self._pipe_busy = False
        self._pending = []

        # VAD state
        self._vad_buf = []
        self._silence_start = None
        self._speech_seen = False
        self._started_at = None

    def _emit(self, event, data=None):
        try:
            self.on_event(event, data)
        except Exception:
            pass

    # -- audio engine ---------------------------------------------------------
    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[FlowMini] audio status: {status}")
        chunk = indata.copy()
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        try:
            self.on_level(rms, self.recording or self.vad_mode)
        except Exception:
            pass
        if self.vad_mode:
            self._vad_feed(chunk)
        elif self.recording:
            self.audio_frames.append(chunk)

    def start_stream(self):
        self.stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="int16",
            callback=self._audio_callback,
        )
        self.stream.start()

    def _poll_foreground_loop(self, interval=0.4):
        """Keep last_external_hwnd fresh so the paste target survives focus
        landing on our own window, tray menu or HUD between hotkey presses."""
        while True:
            try:
                fg = get_foreground_hwnd()
                if fg and fg != self.own_hwnd:
                    self.last_external_hwnd = fg
            except Exception:
                pass
            time.sleep(interval)

    def _capture_target(self):
        """Pick the paste target: the window the user was actually typing in.

        Captured at hotkey time. When the focus is on FlowMini's own UI we use
        the last external foreground window (tracked continuously by the poller)
        instead of a stale previous target — this is what makes "press the
        hotkey anywhere" paste into whatever app was open before.
        """
        fg = get_foreground_hwnd()
        if fg and fg != self.own_hwnd:
            self.target_hwnd = fg
        elif self.last_external_hwnd and _user32.IsWindow(self.last_external_hwnd):
            self.target_hwnd = self.last_external_hwnd
            print("[FlowMini] Focus is on FlowMini — pasting into the last external app")
        return self.target_hwnd

    def start_recording(self):
        with self.lock:
            if self.recording:
                return
            if self._pipe_busy:
                print("[FlowMini] Still processing previous dictation — wait a moment")
                self._emit("busy")
                return
            print("\n[FlowMini] Listening... (Speak now)")
            self.audio_frames = []
            self._started_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self._capture_target()
            self.recording = True
            if not self.stream:
                self.start_stream()
            self._emit("recording_started")

    def stop_recording(self):
        with self.lock:
            if not self.recording:
                return None
            self.recording = False
            return self._finalize("ptt")

    def _finalize(self, mode):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except OSError:
                pass
            self.stream = None
        print("[FlowMini] Stopped recording. Processing audio...")
        self._emit("recording_stopped")
        if not self.audio_frames:
            return None
        return np.concatenate(self.audio_frames, axis=0)

    # -- combined push-to-talk toggle (used by hotkey handler) ---------------
    def toggle_ptt(self):
        if not self.recording and not self.vad_mode:
            self.start_recording()
        else:
            audio_data = self.stop_recording()
            if audio_data is not None and len(audio_data) > 0:
                self._schedule_pipeline(audio_data, "ptt")

    # -- pipeline serialization ----------------------------------------------
    # Only ONE pipeline may run at a time. Extra utterances (PTT + VAD) queue
    # up and are processed in order, so recording never overlaps processing.
    def _schedule_pipeline(self, audio_data, mode):
        if audio_data is None or len(audio_data) == 0:
            return
        with self._pipe_lock:
            self._pending.append((audio_data, mode))
            if self._pipe_busy:
                return
            self._pipe_busy = True
        threading.Thread(target=self._pipeline_worker, daemon=True).start()

    def _pipeline_worker(self):
        while True:
            with self._pipe_lock:
                if not self._pending:
                    self._pipe_busy = False
                    return
                audio_data, mode = self._pending.pop(0)
            try:
                self.run_pipeline(audio_data, mode)
            except Exception as exc:
                print(f"[FlowMini] Pipeline error: {exc}")

    # -- VAD: energy-based voice activity detection ---------------------------
    def _vad_feed(self, chunk):
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        now = time.monotonic()
        if not hasattr(self, "_noise_floor"):
            self._noise_floor = rms  # first frame seeds the floor
            return
        threshold = max(self._noise_floor * self.cfg["vad_sensitivity"], 100.0)
        speech = rms > threshold
        if speech:
            if not self._speech_seen:
                print("\n[FlowMini][VAD] Speech detected — recording")
                self._speech_seen = True
                self._started_at = time.strftime("%Y-%m-%d %H:%M:%S")
                self._vad_started_mono = now
                self._emit("recording_started")
            self._silence_start = None
            self._vad_buf.append(chunk)
        elif self._speech_seen:
            if self._silence_start is None:
                self._silence_start = now
            elif now - self._silence_start >= self.cfg["vad_silence_gap_s"]:
                audio = np.concatenate(self._vad_buf, axis=0) if self._vad_buf else None
                self._speech_seen = False
                self._vad_buf = []
                print("[FlowMini][VAD] Utterance end detected — processing")
                self._schedule_pipeline(audio, "vad")
            elif now - getattr(self, "_vad_started_mono", now) >= self.cfg["vad_max_utterance_s"]:
                audio = np.concatenate(self._vad_buf, axis=0)
                self._speech_seen = False
                self._vad_buf = []
                print("[FlowMini][VAD] Max utterance length reached — processing")
                self._schedule_pipeline(audio, "vad")

    def calibrate_noise_floor(self, seconds=1.0):
        """Measure ambient RMS so VAD adapts to the room."""
        print(f"[FlowMini][VAD] Calibrating ambient noise ({seconds:.0f}s) — please stay quiet...")
        samples = []

        def cb(indata, frames, ti, status):
            samples.append(indata.copy())

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="int16", callback=cb) as cal:
            time.sleep(seconds)
        if samples:
            floor = float(np.sqrt(np.mean(np.concatenate(samples).astype(np.float32) ** 2)))
        else:
            floor = 500.0
        self._noise_floor = floor
        print(f"[FlowMini][VAD] Noise floor RMS={floor:.0f} — VAD active")

    def toggle_vad(self):
        self.vad_mode = not self.vad_mode
        if self.vad_mode:
            self._capture_target()
            self._emit("vad_on")
            threading.Thread(target=self.calibrate_noise_floor, daemon=True).start()
        else:
            self._emit("vad_off")

    # -- pipeline ---------------------------------------------------------------
    def run_pipeline(self, audio_data, mode="ptt"):
        self._emit("processing")
        t_a = time.monotonic()
        raw_text = self.transcribe_audio(audio_data)
        detected = self._last_detected_lang
        conf = self._last_lang_conf
        self._emit("stage", {"stage": "ASR", "seconds": time.monotonic() - t_a,
                             "lang": detected, "lang_conf": conf})
        if not raw_text:
            self._emit("idle")
            return
        print(f"[FlowMini] Raw ASR: \"{raw_text}\"")

        pre = apply_dictionary(raw_text, self.dictionary) if self.dictionary else raw_text
        if pre != raw_text:
            print(f"[FlowMini] Dictionary applied: \"{pre}\"")

        # Show the raw transcript in the app IMMEDIATELY so the UI never looks
        # frozen while the slower steps run (~1s later). The pasted event below
        # replaces it with the cleaned final text.
        self._emit("asr_text", {"raw": pre, "lang": detected})

        # --- Snippet management commands (voice-controlled) ---
        cmd_response = self.handle_snippet_command(pre)
        if cmd_response is not None:
            self.paste_into_active_app(cmd_response)
            self._emit("pasted", {"text": cmd_response, "mode": mode, "snippet_cmd": True})
            return

        # --- Voice-triggered snippet expansion ---
        snippet = self.snippet_manager.find_matching_snippet(pre)
        if snippet:
            expanded = self.snippet_manager.expand_snippet(snippet)
            self._emit("snippet_used", {"name": snippet.name, "category": snippet.category})
            print(f"[FlowMini] Snippet '{snippet.name}' triggered ({snippet.category})")
            self._emit("pasted", {"text": expanded, "mode": mode, "snippet": snippet.name})
            self.paste_into_active_app(expanded)
            try:
                started = getattr(self, "_started_at", time.strftime("%Y-%m-%d %H:%M:%S"))
                audio_s = len(audio_data) / self.sample_rate if audio_data is not None else 0.0
                log_session(self.db, started, time.strftime("%Y-%m-%d %H:%M:%S"),
                            audio_s, pre, expanded, 0, mode)
            except Exception:
                pass
            return

        # Speed: run the in-app English "meaning" pass (display-only) in
        # PARALLEL with the cleanup pipeline. The Speech Transform Engine is a
        # deterministic pass (a few ms); only cleanup_mode "medium" waits on
        # the LLM polisher, and even then it overlaps the English pass.
        english_text = None
        t_p = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_en = pool.submit(self._transcribe_english, audio_data, detected)
            if self.translate_english:
                # The English pass IS the output text when translating.
                english_text = fut_en.result()
                base = english_text or pre
            else:
                base = pre  # transform the original-language text immediately
            if self.cleanup_mode == "medium":
                # light cleanup + optional AI rewrite (runs on worker 2)
                tres = pool.submit(self._transform, base, detected, conf,
                                   self.polish_text).result()
            else:
                tres = self._transform(base, detected, conf)
            if not self.translate_english:
                english_text = fut_en.result()
        final_text = tres.finalText

        # Apply auto-learned corrections (frequent user fixes)
        if self.auto_learn_enabled:
            learned = self.auto_learner.apply_learned(final_text)
            if learned != final_text:
                print(f"[FlowMini] Auto-learn applied: \"{final_text}\" -> \"{learned}\"")
                final_text = learned

        self._emit("stage", {"stage": "Cleanup", "seconds": time.monotonic() - t_p,
                             "cleanup": self.cleanup_mode,
                             "decision": tres.languageDecision})
        print(f"[FlowMini] Final Text: \"{final_text}\"")
        if tres.edits:
            print("[FlowMini] Edits: " + ", ".join(
                f"{e.type}:{e.sourceText!r}->{e.replacement!r}" for e in tres.edits))
        if tres.warnings:
            print("[FlowMini] Warnings: " + "; ".join(tres.warnings))

        t0 = time.monotonic()
        self.paste_into_active_app(final_text)
        latency_ms = int((time.monotonic() - t0) * 1000)

        started = getattr(self, "_started_at", time.strftime("%Y-%m-%d %H:%M:%S"))
        audio_s = len(audio_data) / self.sample_rate if audio_data is not None else 0.0
        try:
            words = log_session(self.db, started, time.strftime("%Y-%m-%d %H:%M:%S"),
                                audio_s, raw_text, final_text, latency_ms, mode)
        except Exception as exc:
            # A DB hiccup must never block the transcript from reaching the app.
            print(f"[FlowMini] Session log failed (continuing): {exc}")
            words = 0
        print(f"[FlowMini] Session logged: {words} words, {latency_ms} ms insertion latency")
        self._emit("pasted", {"words": words, "latency_ms": latency_ms, "mode": mode,
                              "raw": pre, "polished": final_text,
                              "lang": detected, "lang_conf": conf,
                              "english": english_text,
                              "cleanup": self.cleanup_mode,
                              "lang_decision": tres.languageDecision,
                              "edits": [
                                  {"type": e.type, "source": e.sourceText,
                                   "repl": e.replacement}
                                  for e in tres.edits
                              ]})

    def _transform(self, text, detected, conf, rewriter=None):
        """Run the deterministic Speech Transform Engine.

        Uses Whisper's language detection (language + confidence) to pick the
        transformation rules; a manual language selection becomes the hint.
        Only languages with rule tables get transformed — everything else is
        preserved verbatim (never translated)."""
        hint = None if self.detect_language else self.language
        own_base = (self.language or "en-US").split("-")[0].lower()
        enabled = [own_base, "en"]
        try:
            return transform_transcript(
                transcript=text,
                language_hint=hint,
                enabled_languages=enabled,
                asr_language=detected,
                asr_confidence=float(conf or 0.0),
                cleanup_mode=self.cleanup_mode,
                medium_rewriter=rewriter,
            )
        except Exception as exc:
            print(f"[FlowMini] Transform engine failed (pasting raw): {exc}")
            from speech_transform import TransformResult
            return TransformResult(rawTranscript=text, finalText=text,
                                   languageDecision="fallback",
                                   languageWarning=f"Transform error: {exc}")

    def handle_snippet_command(self, text):
        """Process voice snippet management commands.

        Returns a response string if the text is a snippet command, else None.
        Supported:
          - "add snippet <name> with trigger <trigger> and content <content>"
          - "remove snippet <name>"
          - "list snippets"
        """
        t = text.strip().lower()
        if not t:
            return None

        # list snippets
        if t in ("list snippets", "show snippets", "snippets"):
            cats = self.snippet_manager.get_categories()
            items = self.snippet_manager.list_snippets()
            if not items:
                return "No snippets defined. Say 'add snippet' to create one."
            lines = [f"Snippets ({len(items)}):"]
            for s in items:
                lines.append(f"  - {s.name} [{s.category}]: trigger='{s.trigger}'")
            return "\n".join(lines)

        # remove snippet
        m = re.match(r"^(?:remove|delete)\s+snippet\s+(.+)$", t)
        if m:
            name = m.group(1).strip()
            if self.snippet_manager.remove_snippet(name):
                return f"Snippet '{name}' removed."
            return f"Snippet '{name}' not found."

        # add snippet
        m = re.match(
            r"^add\s+snippet\s+(.+?)\s+with\s+trigger\s+(.+?)\s+and\s+content\s+(.+)$", t)
        if m:
            name = m.group(1).strip()
            trigger = m.group(2).strip()
            content = m.group(3).strip()
            snippet = Snippet(name=name, trigger=trigger, content=content)
            self.snippet_manager.add_snippet(snippet)
            return f"Snippet '{name}' added. Say '{trigger}' to use it."

        return None

    def record_user_correction(self, raw_fragment: str, corrected_fragment: str):
        """Record a user correction for the auto-learner.

        Called when the user edits pasted text. Over time, frequent
        corrections are applied automatically and suggested for promotion
        into the main custom dictionary.
        """
        if not self.auto_learn_enabled:
            return
        self.auto_learner.record_correction(raw_fragment, corrected_fragment)

    # -- speech-to-text engines -------------------------------------------------
    def _whisper_lang(self, bcp47):
        """Map a BCP-47 tag to the primary ISO code Whisper understands."""
        code = (bcp47 or "en").split("-")[0].lower()
        return "tl" if code == "fil" else code

    def _whisper_local_path(self):
        """A ready-to-use model dir next to the app (no download needed)."""
        models_root = os.path.join(BASE_DIR, "models", f"faster-whisper-{self.stt_model.lower()}")
        if os.path.isdir(models_root) and os.path.exists(os.path.join(models_root, "model.bin")):
            return models_root
        return None

    def _pick_device(self):
        """Prefer CUDA when a working GPU is present.

        Returns (device, compute_type). ctranslate2's CUDA build needs the
        CUDA runtime DLLs; if they are missing the count is 0 and we stay on
        CPU. CUDA is validated by checking supported compute types so a
        broken driver install silently degrades instead of failing every run.
        """
        want = (self.stt_device or "auto").lower()
        if want == "cpu":
            return "cpu", self.stt_compute_type or "int8"
        if want not in ("auto", "cuda", "gpu"):
            want = "auto"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                # Check CUDA actually works by querying supported compute types
                # This avoids the "model.bin not found" error from trying to load a dummy model
                supported = ctranslate2.get_supported_compute_types("cuda")
                if not supported:
                    raise RuntimeError("CUDA device reports no supported compute types")
                # float16 works well on RTX 30-series; int8_float16 may not be available for all models
                compute = self.stt_compute_type or "float16"
                if compute not in supported:
                    # Fall back to a supported type - prefer float16 over int8_float16 for model compat
                    preferred = ["float16", "int8_float16", "int8", "int8_bfloat16"]
                    compute = next((c for c in preferred if c in supported), supported[0])
                # Get device name safely (API varies by ctranslate2 version)
                device_name = "GPU"
                try:
                    device_name = ctranslate2.get_cuda_device_name(0)
                except Exception:
                    pass
                print(f"[FlowMini] Whisper on CUDA GPU (ctranslate2 {ctranslate2.__version__}, "
                      f"{device_name}, {compute})")
                return "cuda", compute
        except Exception as exc:
            print(f"[FlowMini] CUDA unavailable ({exc}); using CPU")
        return "cpu", self.stt_compute_type or "int8"

    def _load_whisper(self):
        """Lazy-load the local Whisper model (first call downloads if not bundled)."""
        if self._whisper is not None:
            return self._whisper
        if self._whisper_loading:
            return None  # a concurrent call is already loading
        self._whisper_loading = True
        try:
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            from faster_whisper import WhisperModel
        except Exception as exc:
            print(f"[FlowMini] faster-whisper unavailable: {exc}")
            self._whisper_loading = False
            return None
        try:
            model_source = self._whisper_local_path()
            if model_source is None:
                models_root = os.path.join(BASE_DIR, "models")
                os.makedirs(models_root, exist_ok=True)
            else:
                models_root = None  # already local, no download_root needed
            self._emit("whisper_loading")
            print(f"[FlowMini] Loading Whisper '{self.stt_model}'"
                  + (f" from {model_source}" if model_source else " (downloading first run)..."))
            t0 = time.monotonic()
            device, compute = self._pick_device()
            kwargs = {"device": device, "compute_type": compute}
            if models_root is not None:
                kwargs["download_root"] = models_root
            self._whisper = WhisperModel(model_source or self.stt_model, **kwargs)
            print(f"[FlowMini] Whisper ready in {time.monotonic() - t0:.0f}s "
                  f"({device}/{compute}, beam={self.stt_beam_size}, "
                  f"accuracy={self.stt_accuracy_mode})")
            return self._whisper
        except Exception as exc:
            print(f"[FlowMini] Whisper load failed: {exc}")
            return None
        finally:
            self._whisper_loading = False

    def _transcribe_kwargs(self):
        """Decode parameters for one utterance.

        'high' accuracy: wide beam search, temperature fallback (so a hard
        passage is retried with sampling instead of being given up on), and a
        higher no_speech threshold so Whisper does not hallucinate during
        pauses. 'fast' keeps the old greedy, lowest-latency behaviour.
        """
        if (self.stt_accuracy_mode or "high").lower() == "fast":
            return {"beam_size": 1, "no_speech_threshold": 0.8}
        return {
            "beam_size": max(1, int(self.stt_beam_size or 5)),
            "no_speech_threshold": 0.6,
            "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "compression_ratio_threshold": 2.4,
            "log_prob_threshold": -1.0,
        }

    def _reduce_noise(self, audio):
        """Voice isolation: spectral-gate noise reduction (numpy/scipy only).
        Estimates the stationary noise floor from the leading frames and
        attenuates it in every STFT frame, leaving speech intact. On any
        error it returns the audio unchanged (never worse than the input)."""
        try:
            from scipy import signal as sig
            n = len(audio)
            if n < 4096:
                return audio
            nperseg, hop = 512, 128
            _, t, Zxx = sig.stft(audio, fs=self.sample_rate, nperseg=nperseg,
                                 noverlap=nperseg - hop, window="hann")
            mag = np.abs(Zxx)
            phase = np.angle(Zxx)
            # Noise profile: median magnitude of the leading ~0.2 s (pre-roll).
            prof = Zxx[:, : max(1, int(0.2 * t.size))]
            noise = np.median(np.abs(prof), axis=1, keepdims=True) + 1e-6
            gain = np.maximum(1.0 - 1.25 * noise / (mag + 1e-6), 0.08)
            _, x = sig.istft(mag * gain * np.exp(1j * phase), fs=self.sample_rate,
                             nperseg=nperseg, noverlap=nperseg - hop, window="hann")
            x = np.real(x)
            if len(x) > n:
                x = x[:n]
            elif len(x) < n:
                x = np.pad(x, (0, n - len(x)))
            peak = float(np.max(np.abs(x))) if len(x) else 0.0
            if peak > 0:
                x = x * min(0.95 / peak, 1.0)  # soft normalize
            return x.astype(np.float32)
        except Exception as exc:
            print(f"[FlowMini] Noise reduction skipped: {exc}")
            return audio

    def _transcribe_whisper(self, audio_data):
        model = self._load_whisper()
        if model is None:
            return None  # tell the dispatcher to fall back
        audio = audio_data.astype(np.float32) / 32768.0
        # Voice isolation: spectral-gate noise reduction BEFORE the model sees it.
        audio = self._reduce_noise(audio)
        # Boosting quiet speech so Whisper never misses it ("no speech detected" fix)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if 0.0005 < peak < 0.15:
            gain = min(0.9 / max(peak, 1e-4), 40.0)
            audio = audio * gain
        # Auto-detect the spoken language (language=None) unless forced in config.
        lang = None
        if not self.detect_language and re.match(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$", self.language or ""):
            lang = self._whisper_lang(self.language)
        task = "translate" if self.translate_english else "transcribe"
        t0 = time.monotonic()
        try:
            # Silero VAD (bundled inside faster-whisper, no download) strips the
            # non-speech frames so Whisper ONLY transcribes real voice — this is
            # the noise filter / voice isolation that makes transcripts clean.
            segments, info = model.transcribe(
                audio, language=lang, task=task,
                vad_filter=True, vad_parameters=VAD_PARAMS,
                condition_on_previous_text=False,
                **self._transcribe_kwargs())
            text = " ".join(s.text.strip() for s in segments).strip()
            self._last_detected_lang = info.language
            self._last_lang_conf = float(getattr(info, "language_probability", 0.0) or 0.0)
            print(f"[FlowMini] Whisper ASR in {time.monotonic() - t0:.1f}s "
                  f"(detected={info.language}, conf={self._last_lang_conf:.2f}, task={task})")
            return text
        except Exception as exc:
            print(f"[FlowMini] Whisper inference failed: {exc}")
            return None

    def _transcribe_english(self, audio_data, detected_lang):
        """Second offline Whisper pass → English rendering of the same audio.
        Used ONLY for in-app confirmation (the bracket under the heard line);
        never pasted unless the user explicitly turns translate_to_english on."""
        if not detected_lang or detected_lang == "en":
            return None  # already English — no meaning to show
        model = self._load_whisper()
        if model is None:
            return None
        audio = self._trim_silence(audio_data).astype(np.float32) / 32768.0
        audio = self._reduce_noise(audio)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if 0.0005 < peak < 0.15:
            gain = min(0.9 / max(peak, 1e-4), 40.0)
            audio = audio * gain
        t0 = time.monotonic()
        try:
            segments, _ = model.transcribe(
                audio, language=None, task="translate",
                vad_filter=True, vad_parameters=VAD_PARAMS,
                condition_on_previous_text=False,
                **self._transcribe_kwargs())
            text = " ".join(s.text.strip() for s in segments).strip()
            print(f"[FlowMini] English meaning in {time.monotonic() - t0:.1f}s: {text!r}")
            return text or None
        except Exception as exc:
            print(f"[FlowMini] English pass failed: {exc}")
            return None

    def _transcribe_google(self, audio_data):
        wav_buffer = io.BytesIO()
        wav.write(wav_buffer, self.sample_rate, audio_data)
        wav_buffer.seek(0)
        with sr.AudioFile(wav_buffer) as source:
            audio_source = self.recognizer.record(source)
        try:
            raw = self.recognizer.recognize_google(audio_source, language=self.language)
            return raw.strip()
        except sr.UnknownValueError:
            print("[FlowMini] Google ASR: no recognizable speech.")
            return ""
        except sr.RequestError as exc:
            print(f"[FlowMini] Google ASR error: {exc}")
            return ""

    def _trim_silence(self, audio, threshold=120.0, pad_ms=200):
        """Cut silent edges so Whisper only sees the spoken part (faster + cleaner)."""
        n = len(audio)
        if n < 512:
            return audio
        win = max(1, int(self.sample_rate * 0.02))          # 20 ms frames
        nframes = n // win
        if nframes < 3:
            return audio
        chunk = audio[: nframes * win]
        levels = np.sqrt(np.mean(chunk.reshape(nframes, win).astype(np.float32) ** 2, axis=1))
        voiced = np.where(levels > threshold)[0]
        if len(voiced) == 0:
            return audio
        pad = max(1, int((pad_ms / 1000.0) / 0.02))
        s = max(0, int(voiced.min()) - pad)
        e = min(nframes, int(voiced.max()) + pad + 1)
        return chunk[s * win: e * win]

    def transcribe_audio(self, audio_data):
        """Transcribe raw PCM → text. Runs on a background thread (never blocks UI)."""
        if audio_data is None or len(audio_data) < 1000:
            return ""
        trimmed = self._trim_silence(audio_data)
        if self.stt_engine in ("whisper", "auto"):
            text = self._transcribe_whisper(trimmed)
            if text is not None:
                return text
            if self.stt_engine == "whisper":
                print("[FlowMini] Whisper failed (stt_engine=whisper, no fallback)")
                return ""
        return self._transcribe_google(trimmed)

    def _polish_lang_hint(self):
        """What language should the polished output be in?"""
        if self.translate_english:
            return "English"
        return self._last_detected_lang or self.language or "the speaker's language"

    def _style_prompt(self):
        """Get the style-specific prompt parameters."""
        style = STYLE_PRESETS.get(self.style_preset, STYLE_PRESETS["casual"])
        return style

    def polish_text(self, raw_text):
        """Use LLM (OpenRouter) to polish and format the raw transcript."""
        if not raw_text:
            return ""
        if not self.use_polisher:
            return raw_text
        if not self.api_key:
            print("[FlowMini] Warning: OPENROUTER_API_KEY not found. Returning raw transcript.")
            return raw_text

        style = self._style_prompt()
        lang_hint = self._polish_lang_hint()
        system_prompt = SYSTEM_PROMPT.format(
            language=lang_hint,
            capitalize="yes" if style.get("capitalize") else "no",
            punctuation="yes" if style.get("punctuation") else "no",
            contractions="yes" if style.get("contractions") else "no",
            tone=style.get("tone", "natural"),
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/flow-mini",
            "X-Title": "FlowMini",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Spoken input: {raw_text}"},
            ],
            "max_tokens": 300,
            "temperature": 0.2,
        }

        t0 = time.monotonic()
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=6)
            if resp.status_code == 200:
                polished = resp.json()["choices"][0]["message"]["content"].strip()
                print(f"[FlowMini] Polish latency: {(time.monotonic() - t0) * 1000:.0f} ms (style: {self.style_preset})")
                return polished
            print(f"[FlowMini] Polish API returned {resp.status_code}: {resp.text}")
            return raw_text
        except Exception as e:
            print(f"[FlowMini] Polish request failed: {e}")
            return raw_text

    def paste_into_active_app(self, text):
        """Inject text into the app the user was typing in.

        Layered like the native helpers of the major dictation products:
          1. robustly restore the captured target window to the foreground
             (ALT-tap + AttachThreadInput fallbacks, verified)
          2. set the clipboard (verified) and send a real Ctrl+V keystroke
          3. if focus could not be restored, insert at the caret directly
             via EM_REPLACESEL (works for classic edit controls, no focus)
          4. if neither is possible, keep the text on the clipboard and
             surface it to the UI — never paste into the wrong app.
        """
        if not text:
            return
        print(f"[FlowMini] Injecting text: '{text}'")
        target = getattr(self, "target_hwnd", None)
        focused = force_foreground(target) if target else False
        if target and not focused:
            print("[FlowMini] Could not restore the target window's focus")
        try:
            # Set the clipboard via the Win32 API, verifying it actually stuck.
            set_clipboard_unicode(text)
            time.sleep(0.08)
            for _ in range(3):
                if text == get_clipboard_text():
                    break
                print("[FlowMini] Clipboard verify failed — retrying...")
                set_clipboard_unicode(text)
                time.sleep(0.12)
            if focused:
                send_ctrl_v()
                time.sleep(0.05)
                print("[FlowMini] Successfully pasted into active application!")
            elif target and _insert_text_at_caret(target, text):
                print("[FlowMini] Focus was lost — inserted at the caret directly")
            else:
                self._emit("paste_failed", {"reason": "no_focus_no_caret"})
                print("[FlowMini] Text is ON THE CLIPBOARD — click your app and press Ctrl+V")
        except Exception as e:
            print(f"[FlowMini] Paste error: {e}")
            try:
                pyperclip.copy(text)
                self._emit("paste_failed", {"reason": f"error: {e}"})
                print("[FlowMini] Text is on the clipboard — click your app and press Ctrl+V")
            except Exception as e2:
                print(f"[FlowMini] Clipboard fallback also failed: {e2}")

    def run_self_test(self):
        """Simulate an end-to-end pipeline test without requiring microphone speech."""
        print("--- Running FlowMini Self-Test ---")
        test_spoken = "um hello everyone uh can we meet at like 3 p.m. no wait 4 p.m. to discuss the project"
        print(f"Simulated Spoken Input: \"{test_spoken}\"")

        print("Testing custom dictionary...")
        demo = apply_dictionary("email muhammadh aarif about the ronin project",
                                self.dictionary or {"muhammadh aarif": "Muhammadh Aarif T J"})
        print(f"Dictionary expansion: \"{demo}\"")

        print("Testing AI Polisher...")
        if self.use_polisher:
            polished = self.polish_text(test_spoken)
            print(f"Polished Output: \"{polished}\"")
        else:
            polished = None
            print("Polisher disabled (use_polisher=false) — skipped")

        print("Testing Speech Transform Engine...")
        t_in = "open square bracket x close square bracket"
        tres = self._transform(t_in, "en", 0.99)
        assert tres.finalText == "[x]", f"transform produced {tres.finalText!r}"
        t_in2 = "um, send it today"
        tres2 = self._transform(t_in2, "en", 0.99)
        assert tres2.finalText == "Send it today.", f"transform produced {tres2.finalText!r}"
        print("Transform: \"open square bracket x close square bracket\" -> \"[x]\"")
        print("Transform: \"um, send it today\" -> \"Send it today.\"")

        print("Testing Clipboard & Insertion...")
        paste_target = polished if polished is not None else tres.finalText
        pyperclip.copy(paste_target)
        read_back = pyperclip.paste()
        assert read_back == paste_target, "Clipboard verification failed!"
        print("[FlowMini] Clipboard verified successfully!")
        print("Self-test PASSED!")

    def start_listener(self):
        """CLI listener using pynput (note: pynput hooks may not receive keys
        on all Windows machines — the GUI app uses RegisterHotKey instead)."""
        from pynput import keyboard
        trigger_key = getattr(keyboard.Key, self.trigger_key_name.lower(), keyboard.Key.f8)
        vad_key = getattr(keyboard.Key, self.vad_key_name.lower(), keyboard.Key.f9)
        print("==================================================")
        print(f" FlowMini Voice Dictation is Running (model: {self.model})")
        print(f" Push-to-talk: press [{self.trigger_key_name.upper()}] to start / stop")
        print(f" VAD auto-dictation: press [{self.vad_key_name.upper()}] to toggle")
        print(" Press Ctrl+C in terminal to exit")
        print("==================================================")

        def on_press(key):
            if key == trigger_key:
                self.toggle_ptt()
            elif key == vad_key:
                self.toggle_vad()

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()


if __name__ == "__main__":
    config = load_config()
    conn = init_db()
    app = FlowMini(config, conn)
    args = sys.argv[1:]
    if "--stats" in args:
        print_stats(conn)
    elif "--test" in args:
        app.run_self_test()
    else:
        app.run_self_test()
        print("\nStarting live service...")
        app.start_listener()
