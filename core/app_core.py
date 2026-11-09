"""Core business logic for FlowMini — decoupled from Tkinter UI.

This module encapsulates all background functionality that must remain
in Python for offline, native operation:
  - System audio capture (sounddevice)
  - Local Whisper ASR model loading & inference
  - Global hotkey listener (keyboard / pynput)
  - Deterministic text cleanup and auto-pasting (pyautogui)
  - System tray management (pystray)
  - Session telemetry (SQLite)

The AppCoreManager emits events that the React UI can subscribe to
via the pywebview BridgeAPI bridge (in-process, zero-network).
"""

import os
import sys
import json
import threading
import time
import queue
import sqlite3
import ctypes
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import sounddevice as sd
import numpy as np
import faster_whisper
import pyperclip
import pyautogui

# Try global hotkey libraries; fall back gracefully
try:
    import keyboard as global_keyboard
    HAS_KEYBOARD = True
except ImportError:
    try:
        from pynput import keyboard as pynput_keyboard
        HAS_KEYBOARD = True
    except ImportError:
        HAS_KEYBOARD = False

import pystray
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Paths & Configuration
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    # PyInstaller: keep config/DB next to the exe so settings persist across
    # runs (sys._MEIPASS is a temp dir that is deleted on exit).
    BASE_DIR = Path(sys.executable).parent
else:
    # Development: project root
    BASE_DIR = Path(__file__).parent.parent.parent

CONFIG_PATH = BASE_DIR / "config.json"
DICT_PATH = BASE_DIR / "custom_dictionary.json"
DB_PATH = BASE_DIR / "flowmini_sessions.db"
ENV_PATH = BASE_DIR / ".env"


def load_config() -> dict:
    """Load config.json, falling back to DEFAULT_CONFIG."""
    default = {
        "trigger_key": "ctrl+alt+d",
        "vad_trigger_key": "ctrl+alt+f",
        "polish_model": "google/gemini-2.5-flash",
        "vad_sensitivity": 2.5,
        "vad_silence_gap_s": 1.0,
        "vad_max_utterance_s": 30.0,
        "polisher": True,
        "cleanup_mode": "light",
        "style_preset": "casual",
        "stt_engine": "auto",
        "stt_model": "large-v3-turbo",
        "stt_device": "auto",
        "stt_compute_type": "",
        "stt_beam_size": 5,
        "stt_accuracy_mode": "high",
        "auto_learn": True,
        "developer_mode": False,
        "app_profiles_enabled": True,
        "show_hud": True,
        "detect_language": True,
        "translate_to_english": False,
        "start_with_windows": False,
        "language": "en-US",
        "ui_host": "127.0.0.1",
        "ui_port": 8765,
        "vad_enabled": False,
        "mic_device": "",
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return default


def save_config(cfg: dict) -> None:
    """Persist config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Microphone Enumeration
# ---------------------------------------------------------------------------

def get_microphone_devices() -> List[str]:
    """Query available input devices via sounddevice.

    Returns a list of device names that support input channels.
    """
    try:
        devices = []
        sd_devices = sd.query_devices()
        for i, d in enumerate(sd_devices):
            if d["max_input_channels"] > 0:
                devices.append(d["name"])
        return devices
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Whisper ASR Engine Wrapper
# ---------------------------------------------------------------------------

class WhisperEngine:
    """Thin wrapper around faster-whisper for local ASR inference.

    Handles model loading, audio chunk transcription, and state tracking.
    Runs entirely in-process — no network, no online services.
    """

    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "",
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self.is_loading = False
        self._load_lock = threading.Lock()
        self._init_model()

    def _init_model(self) -> None:
        """Load the Whisper model in a thread-safe manner."""
        with self._load_lock:
            if self.model is not None:
                return  # already loaded
            self.is_loading = True
            try:
                self.model = faster_whisper.WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type or ("float16" if self.device.startswith("cuda") else "int8"),
                )
            except Exception as exc:
                self.model = None
                self.is_loading = False
                raise RuntimeError(f"Failed to load Whisper model '{self.model_name}': {exc}") from exc
            self.is_loading = False

    def transcribe_file(self, audio_path: str, language: Optional[str] = None) -> dict:
        """Transcribe a WAV audio file and return the result dict."""
        if self.model is None:
            self._init_model()
        if self.model is None:
            return {"text": "", "language": "", "segments": [], "duration": 0.0}
        try:
            segments, info = self.model.transcribe(audio_path, language=language or "en")
            text = " ".join(seg.text for seg in segments).strip()
            return {
                "text": text,
                "language": info.language or "en",
                "segments": [
                    {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                    for seg in segments
                ],
                "duration": info.duration or 0.0,
            }
        except Exception as exc:
            return {"text": "", "language": "", "segments": [], "duration": 0.0, "error": str(exc)}

    def transcribe_buffer(self, audio_buffer: np.ndarray, sample_rate: int) -> dict:
        """Transcribe an in-memory audio buffer (16kHz, 16-bit PCM preferred)."""
        try:
            import tempfile
            import scipy.io.wavfile as wavfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                wavfile.write(tmp.name, sample_rate, audio_buffer.astype(np.int16))
                return self.transcribe_file(tmp.name)
        except Exception as exc:
            return {"text": "", "language": "", "segments": [], "duration": 0.0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Audio Capture & Processing
# ---------------------------------------------------------------------------

class AudioCapture:
    """Manages continuous audio input from the system microphone.

    Captures PCM audio at 16kHz (or the device's native rate) and provides
    a rolling buffer that the Whisper engine can consume.
    """

    CHUNK_DURATION_MS = 30  # 30ms chunks ≈ 480 samples @ 16kHz
    SAMPLE_RATE = 16000
    CHANNELS = 1
    DTYPE = "int16"

    def __init__(self, on_chunk: Callable[[np.ndarray], None], stop_event: threading.Event):
        self.on_chunk = on_chunk
        self.stop_event = stop_event
        self._stream = None
        self._thread = None

    def start(self) -> None:
        """Begin audio capture in a background thread."""
        if self._stream is not None:
            return  # already running
        self._stop_internal()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _stop_internal(self) -> None:
        """Stop the audio stream and join the thread."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

    def stop(self) -> None:
        """Public API to stop audio capture."""
        self._stop_internal()

    def _capture_loop(self) -> None:
        """Continuously capture audio frames and forward to on_chunk callback."""
        try:
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                blocksize=int(self.SAMPLE_RATE * self.CHUNK_DURATION_MS / 1000),
            )
            self._stream.start()
            while not self.stop_event.is_set():
                try:
                    data, _ = self._stream.read(
                        int(self.SAMPLE_RATE * self.CHUNK_DURATION_MS / 1000)
                    )
                    if not self.stop_event.is_set():
                        self.on_chunk(np.frombuffer(data, dtype=self.DTYPE))
                except Exception:
                    if not self.stop_event.is_set():
                        raise
            self._stream.stop()
            self._stream.close()
        except Exception as e:
            print(f"[AudioCapture] Error: {e}")


# ---------------------------------------------------------------------------
# Global Hotkey Listener
# ---------------------------------------------------------------------------

class HotkeyListener:
    """Listens for global hotkeys (push-to-talk / VAD toggle) in a background thread.

    Uses `keyboard` library if available, otherwise `pynput`. Falls back to
    no hotkeys if neither can be imported/initialized.
    """

    def __init__(self, on_trigger: Callable[[], None], on_vad: Callable[[], None], trigger_key: str, vad_key: str):
        self.on_trigger = on_trigger
        self.on_vad = on_vad
        self.trigger_key = trigger_key
        self.vad_key = vad_key
        self._running = False
        self._thread = None
        self._keyboard = None

        if not HAS_KEYBOARD:
            return

        try:
            self._keyboard = global_keyboard if "global_keyboard" in dir() else None
        except Exception:
            self._keyboard = None

    def _on_press(self, key):
        """Called by the keyboard library on each key press event."""
        try:
            k = getattr(key, "name", str(key)).lower()
            if k == self.trigger_key.lower():
                if self.on_trigger:
                    self.on_trigger()
            if k == self.vad_key.lower():
                if self.on_vad:
                    self.on_vad()
        except Exception:
            pass

    def start(self) -> None:
        """Begin listening for hotkeys."""
        if self._running or self._keyboard is None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _listen_loop(self) -> None:
        """Main loop for the keyboard listener."""
        try:
            if self._keyboard:
                self._keyboard.on_press(self._on_press)
                while self._running:
                    time.sleep(0.1)
                self._keyboard.unhook_all()
        except Exception:
            pass

    def stop(self) -> None:
        """Stop the hotkey listener."""
        self._running = False
        if self._keyboard:
            try:
                self._keyboard.unhook_all()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# System Tray (pystray)
# ---------------------------------------------------------------------------

class SystemTray:
    """Manages the Windows system tray icon and menu for FlowMini.

    Provides Show/Hide, Self-Test, About, and Quit items. Clicking the
    tray icon toggles window visibility (when a pywebview window exists).
    """

    def __init__(self, title: str, icon_path: Optional[str], on_quit: Callable[[], None], on_toggle: Callable[[], None]):
        self.title = title
        self.icon_path = icon_path
        self.on_quit = on_quit
        self.on_toggle = on_toggle
        self._menu = None
        self._icon = None
        self._item = None

    def _build_menu(self) -> pystray.Menu:
        """Build the tray context menu."""
        return pystray.Menu(
            pystray.MenuItem("Show", self.on_toggle, default=True),
            pystray.MenuItem("Hide", self.on_toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Self-Test", self._run_selftest),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.on_quit),
        )

    def _run_selftest(self) -> None:
        """Run the STT self-test and log results."""
        try:
            from .stt_selftest import stt_selftest
        except Exception:
            from stt_selftest import stt_selftest
        report = stt_selftest()
        print(f"[SelfTest] {report}")

    def update_icon(self, img: Image.Image) -> None:
        """Update the tray icon image."""
        self._icon = img

    def run(self) -> None:
        """Start the pystray event loop in a daemon thread."""
        if self._icon is None:
            img = Image.new("RGB", (64, 64), (12, 12, 18))
            d = ImageDraw.Draw(img)
            d.text((10, 20), "FM", fill=(230, 57, 70))
            self._icon = img
        self._menu = self._build_menu()
        self._item = pystray.Icon(self.title, self._icon, self.title, self._menu)
        thread = threading.Thread(target=self._item.run, daemon=True)
        thread.start()

    def stop(self) -> None:
        """Request the tray icon to stop."""
        if self._item:
            try:
                self._item.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Text Cleanup & Paste
# ---------------------------------------------------------------------------

def cleanup_transcript(text: str, mode: str = "light") -> str:
    """Apply deterministic text cleanup based on the selected mode."""
    if mode == "off":
        return text.strip()

    if mode == "light":
        import re
        text = re.sub(r"\b(um|uh|er|ah)\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    if mode == "medium":
        text = cleanup_transcript(text, "light")
        # Medium mode: light + local LLM polish (offline-capable placeholder)
        # In a full implementation, this would call a local LMC or rule-based polisher
        return text

    return text.strip()


def simulate_ctrl_v() -> None:
    """Simulate Ctrl+V paste into the currently active foreground window."""
    try:
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# AppCoreManager — the central decoupled logic class
# ---------------------------------------------------------------------------

class AppCoreManager:
    """Decoupled Python logic for FlowMini.

    All background work (audio, ASR, hotkeys, tray, paste) runs in this
    class. The React UI communicates via the pywebview BridgeAPI — no
    TCP sockets, no localhost ports, pure in-process binding.

    Lifecycle:
      - `start()` — initialize everything (audio, model, hotkeys, tray)
      - `stop()` — clean shutdown
      - Event callbacks are routed to the React UI through the bridge
    """

    def __init__(self, bridge_api=None):
        self.bridge_api = bridge_api  # pywebview BridgeAPI instance
        self.config = load_config()

        # Runtime state
        self._running = False
        self._stop_all = threading.Event()

        # Components
        self.audio_capture: Optional[AudioCapture] = None
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.tray: Optional[SystemTray] = None
        self.hotkey_win = None

        # Events queued for the bridge (React UI)
        self._event_queue: "queue.Queue[dict]" = queue.Queue()
        self._queue_lock = threading.Lock()

        # Transcription history (last N sessions)
        self._history: List[dict] = []
        self._max_history = 50
        self._last_raw: Optional[str] = None

        # Thread safety
        self._lock = threading.Lock()

        # Audio level tracking
        self._rms_level = 0.0

        # Dictation thread reference
        self._dictation_thread: Optional[threading.Thread] = None

        # The real engine (flow_mini.FlowMini) — owns audio capture, ASR,
        # hotkeys, paste, and the session DB. AppCoreManager is a thin shim that
        # adapts it to the BridgeAPI/js_api surface.
        self.db = None
        self.engine = None
        try:
            from flow_mini import FlowMini, init_db
            from flow_mini import load_config as load_engine_config
            # The engine's loader adds api_key / env fallbacks that
            # core.app_core.load_config() does not.
            self.config = load_engine_config()
            self.db = init_db()
            self.engine = FlowMini(
                self.config,
                self.db,
                on_event=self._on_engine_event,
                on_level=self._on_engine_level,
            )
        except Exception as exc:
            print(f"[AppCore] Could not create FlowMini engine: {exc}")

    # -----------------------------------------------------------------
    # Engine callbacks
    # -----------------------------------------------------------------

    def _on_engine_event(self, event: str, data=None) -> None:
        """Translate FlowMini engine events into bridge events."""
        mapping = {
            "recording_started": {"type": "status", "status": "recording"},
            "recording_stopped": {"type": "status", "status": "processing"},
            "idle": {"type": "status", "status": "idle"},
            "busy": {"type": "status", "status": "processing"},
            "processing": {"type": "status", "status": "processing"},
            "partial_transcript": {"type": "partial", "text": data or ""},
            "asr_text": {"type": "asr_text", "text": data or ""},
            "pasted": {"type": "log", "text": "Transcript pasted", "tag": "ok"},
            "paste_failed": {"type": "log", "text": "Paste failed", "tag": "err"},
            "vad_on": {"type": "log", "text": "Hands-free VAD on", "tag": "ok"},
            "vad_off": {"type": "log", "text": "Hands-free VAD off", "tag": "dim"},
            "whisper_loading": {"type": "log", "text": "Loading Whisper model…", "tag": "dim"},
            "whisper_ready": {"type": "log", "text": "Whisper ready", "tag": "ok"},
            "model_download": {"type": "log", "text": "Downloading model…", "tag": "dim"},
        }
        mapped = mapping.get(event)
        if mapped is not None:
            self._emit_event(mapped)
        else:
            self._emit_event({"type": event, "data": data or {}})
        # Track completed sessions for the history view.
        if event in ("pasted", "asr_text"):
            self.add_to_history({
                "timestamp": time.time(),
                "raw": data or "",
                "mode": "ptt",
            })
        # Remember the raw transcript so "Undo raw" can re-paste it.
        if event == "asr_text" and data:
            self._last_raw = data

    def _on_engine_level(self, rms: float, active: bool = False) -> None:
        self._rms_level = float(rms or 0.0)
        self._emit_event({
            "type": "level",
            "level": round(self._rms_level, 3),
            "active": bool(active),
        })

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self) -> None:
        """Initialize and start all background services."""
        if self._running:
            return
        self._running = True
        self._stop_all.clear()

        try:
            if self.engine is None:
                raise RuntimeError("FlowMini engine is not available")

            # 1. Start the audio stream (real capture + VAD feed).
            self.engine.start_stream()

            # 2. Register global hotkeys on a dedicated message-only window.
            self._start_hotkeys()

            # 3. System tray
            icon_path = BASE_DIR / "flowmini.ico" if (BASE_DIR / "flowmini.ico").exists() else None
            self.tray = SystemTray(
                title="FlowMini",
                icon_path=icon_path,
                on_quit=self._on_quit_requested,
                on_toggle=self._on_tray_toggle,
            )
            self.tray.run()

            # 4. Emit startup event to UI (via bridge if available)
            self._emit_event({
                "type": "status",
                "status": "idle",
                "model": self.config.get("stt_model", "large-v3-turbo"),
                "level": 0.0,
                "uptime": time.time(),
            })

            print("[AppCore] FlowCore started — audio, hotkeys, tray active (offline).")

        except Exception as exc:
            self._running = False
            self._stop_all.set()
            print(f"[AppCore] Failed to start: {exc}")
            raise

    def _start_hotkeys(self) -> None:
        """Register Ctrl+Alt+D / Ctrl+Alt+F via the real engine's hotkey window."""
        try:
            from flowmini_app import _HotkeyWindow
        except Exception as exc:
            print(f"[AppCore] Hotkey window unavailable: {exc}")
            return
        MOD_CONTROL = 0x0002
        MOD_ALT = 0x0001
        MOD_NOREPEAT = 0x4000
        VK_D = 0x44
        VK_F = 0x46
        specs = [
            (1, "Push-to-talk", MOD_CONTROL | MOD_ALT, VK_D),
            (2, "Hands-free VAD", MOD_CONTROL | MOD_ALT, VK_F),
        ]
        self.hotkey_win = _HotkeyWindow(
            specs,
            self._on_hotkey_registered,
            self._on_hotkey,
        )

    def _on_hotkey_registered(self, hotkey_id, label, ok) -> None:
        print(f"[AppCore] Hotkey {label}: {'registered' if ok else 'FAILED'}")

    def _on_hotkey(self, hotkey_id) -> None:
        if hotkey_id == 1:
            self._toggle_recording()
        elif hotkey_id == 2:
            self._toggle_vad()

    def stop(self) -> None:
        """Clean shutdown of all services."""
        self._running = False
        self._stop_all.set()

        if self.engine is not None:
            try:
                if self.engine.recording:
                    self.engine.stop_recording()
            except Exception:
                pass

        if self.hotkey_win is not None:
            try:
                self.hotkey_win.close()
            except Exception:
                pass
            self.hotkey_win = None

        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None

        if self.tray:
            self.tray.stop()
            self.tray = None

        self._emit_event({"type": "status", "status": "idle", "model": "stopped", "level": 0.0})

        print("[AppCore] FlowCore stopped.")

    def _init_whisper(self) -> None:
        """Kept for compatibility — the real engine lazy-loads Whisper itself."""
        if self.engine is not None:
            self.engine._load_whisper()
            self._emit_event({"type": "model_loaded", "model": self.engine.stt_model})

    # -----------------------------------------------------------------
    # Audio Callback
    # -----------------------------------------------------------------

    def _on_audio_chunk(self, rms_data: np.ndarray) -> None:
        """Called by AudioCapture for each audio frame."""
        try:
            if len(rms_data) > 0:
                peak = float(np.max(np.abs(rms_data)))
                self._rms_level = min(1.0, peak / 3000.0)
            else:
                self._rms_level = 0.0

            self._emit_event({
                "type": "level",
                "level": round(self._rms_level, 3),
                "active": self._rms_level > 0.01,
            })
        except Exception as e:
            print(f"[AppCore] Audio chunk error: {e}")

    # -----------------------------------------------------------------
    # Hotkey Callbacks
    # -----------------------------------------------------------------

    def _on_hotkey_trigger(self) -> None:
        """Push-to-talk / dictation toggle hotkey pressed."""
        self._toggle_recording()

    def _on_hotkey_vad(self) -> None:
        """VAD auto-dictation toggle."""
        self._toggle_vad()

    def _toggle_vad(self) -> None:
        """Toggle hands-free VAD on the real engine."""
        if self.engine is not None:
            self.engine.toggle_vad()

    def _toggle_recording(self) -> None:
        """Toggle the dictation recording state on the real engine."""
        if self.engine is not None:
            self.engine.toggle_ptt()
            print("[AppCore] Dictation toggle -> engine.toggle_ptt()")

    # --- Engine-backed properties used by BridgeAPI ---------------------

    @property
    def whisper(self):
        """The real engine's Whisper model wrapper (lazy-loaded)."""
        if self.engine is None:
            return None
        return getattr(self.engine, "_whisper", None)

    def _load_whisper(self):
        """Force the engine to load its Whisper model now."""
        if self.engine is not None:
            self.engine._load_whisper()

    @property
    def auto_learner(self):
        if self.engine is None:
            return None
        return getattr(self.engine, "auto_learner", None)

    @property
    def recording(self) -> bool:
        return bool(self.engine.recording) if self.engine is not None else False

    @property
    def vad_mode(self) -> bool:
        return bool(self.engine.vad_mode) if self.engine is not None else False

    # -----------------------------------------------------------------
    # Tray Callback
    # -----------------------------------------------------------------

    def _on_quit_requested(self) -> None:
        """User clicked 'Exit' from the system tray."""
        self.stop()
        if self.bridge_api:
            try:
                self.bridge_api.close_app()
            except Exception:
                pass
        # Fallback: exit process after a short delay
        # import time; time.sleep(0.5); os._exit(0)

    def _on_tray_toggle(self) -> None:
        """User clicked 'Show/Hide' from the tray menu."""
        if self.bridge_api:
            try:
                self.bridge_api.minimize_to_tray()
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Transcription History
    # -----------------------------------------------------------------

    def _emit_event(self, event: dict) -> None:
        """Queue an event to be forwarded to the React UI via the bridge."""
        try:
            with self._queue_lock:
                self._event_queue.put_nowait(event)
        except Exception:
            pass

    def drain_events(self) -> List[dict]:
        """Drain all pending events from the queue (call from React side)."""
        events: List[dict] = []
        with self._queue_lock:
            while not self._event_queue.empty():
                try:
                    events.append(self._event_queue.get_nowait())
                except Exception:
                    break
        return events

    def add_to_history(self, session_data: dict) -> None:
        """Add a completed dictation to the history list."""
        with self._lock:
            self._history.insert(0, session_data)
            if len(self._history) > self._max_history:
                self._history = self._history[:self._max_history]

    def get_history(self) -> List[dict]:
        """Return recent dictation sessions from the engine's DB."""
        if self.db is None:
            return []
        try:
            rows = self.db.execute(
                "SELECT started_at, duration_s, words, raw_text, latency_ms, mode "
                "FROM sessions ORDER BY id DESC LIMIT 20"
            ).fetchall()
            return [
                {
                    "timestamp": r[0],
                    "duration": r[1],
                    "words": r[2],
                    "raw": r[3],
                    "latency": r[4],
                    "mode": r[5],
                }
                for r in rows
            ]
        except Exception:
            return list(self._history)

    # -----------------------------------------------------------------
    # Public API methods called from BridgeAPI
    # -----------------------------------------------------------------

    def toggle_recording_action(self) -> dict:
        """Explicit action: toggle recording (called from BridgeAPI)."""
        self._toggle_recording()
        return {"action": "toggle", "state": "requested"}

    def change_model_action(self, model_name: str) -> dict:
        """Explicit action: change Whisper model (called from BridgeAPI)."""
        if not self.whisper:
            return {"status": "error", "message": "Whisper not loaded"}
        try:
            # Re-init with new model name
            self.whisper.model_name = model_name
            self._emit_event({"type": "model_change", "model": model_name})
            return {"status": "ok", "model": model_name, "message": f"model set to {model_name}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_status_snapshot(self) -> dict:
        """Return current status snapshot (called from BridgeAPI)."""
        return {
            "status": "idle",  # simplified; full impl would drain events
            "model": self.whisper.model_name if self.whisper else "unknown",
            "level": self._rms_level,
            "active": self._rms_level > 0.01,
        }


# ---------------------------------------------------------------------------
# Example usage (when running as standalone)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("AppCoreManager — standalone test mode")
    print(f"Base dir: {BASE_DIR}")
    print(f"Config: {load_config()}")
    print(f"Microphones: {get_microphone_devices()}")
    print("Import AppCoreManager and call AppCoreManager(bridge_api).start() from app.py")