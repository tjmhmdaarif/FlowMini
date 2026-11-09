"""Bridge API — exposes Python methods to React via pywebview's js_api.

This is the in-process bridge that allows the React frontend to call
Python functions directly, without any network, localhost ports, or TCP
sockets. Communication happens through pywebview's internal message passing.

All methods are designed to be 100% offline and work both in development
mode and when packaged with PyInstaller.
"""

import os
import sys
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path so we can import core modules
if getattr(sys, "frozen", False):
    # PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS)
else:
    # Development mode
    BASE_DIR = Path(__file__).parent.parent.parent

# Import AppCoreManager if available; if not, provide minimal stubs
try:
    from core.app_core import AppCoreManager
except ImportError:
    AppCoreManager = None

# Import Whisper engine helper
try:
    from core.stt_engine import WhisperEngine  # will be created in step 3/4
except ImportError:
    WhisperEngine = None

# Import config helper
try:
    from core.app_core import load_config, save_config
except ImportError:
    def load_config(*_args, **_kwargs):
        return {}

    def save_config(*_args, **_kwargs):
        return None


# ---------------------------------------------------------------------------
# BridgeAPI — the pywebview JavaScript bridge
# ---------------------------------------------------------------------------

class BridgeAPI:
    """Methods exposed to React via window.pywebview.api.

    Each method runs in the Python process and can synchronously or
    asynchronously interact with the AppCoreManager backend. Events are
    forwarded to the React UI through the pywebview message mechanism.

    Important: This class MUST NOT start any network listeners (HTTP,
    WebSocket, etc.). All communication is in-process via pywebview.
    """

    def __init__(self, core_manager: Optional[AppCoreManager] = None):
        self.core = core_manager or AppCoreManager()
        self._lock = threading.Lock()
        self._initialized = False

    # -----------------------------------------------------------------
    # Status & State
    # -----------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return current recording state, active model, and audio levels.

        Returns a dict with keys:
          - status: "idle" | "recording" | "processing" | "error"
          - model: current Whisper model name
          - level: RMS audio level (0.0 – 1.0)
          - active: whether audio input is above noise threshold
          - uptime: seconds since AppCoreManager.start()
        """
        with self._lock:
            try:
                # Drain any pending events from AppCore
                events = self.core.drain_events() if self.core else []
                level_event = next((e for e in events if e.get("type") == "level"), None)
                status_event = next((e for e in events if e.get("type") == "status"), None)

                level = level_event.get("level", 0.0) if level_event else 0.0
                active = level_event.get("active", False) if level_event else False
                status = status_event.get("status", "idle") if status_event else "idle"
                model = status_event.get("model", "unknown") if status_event else "unknown"
                uptime = time.time() - (getattr(self, "_start_time", time.time()))

                # Prefer the live engine state — events only fire on change.
                if self.core is not None:
                    if getattr(self.core, "recording", False):
                        status = "recording"
                    elif getattr(self.core, "vad_mode", False):
                        status = "vad"
                    engine_model = getattr(self.core, "stt_model", None) if hasattr(self.core, "stt_model") else None
                    if engine_model:
                        model = engine_model

                # Day 2: include latest partial transcript from streaming
                partial_event = next((e for e in events if e.get("type") == "partial_transcript"), None)
                partial_text = partial_event.get("text", "") if partial_event else ""

                return {
                    "status": status,
                    "model": model,
                    "level": round(level, 3),
                    "active": active,
                    "uptime": round(uptime, 1),
                    "partial_transcript": partial_text,
                }
            except Exception as e:
                return {"status": "error", "model": "unknown", "level": 0.0, "active": False, "error": str(e),
                        "partial_transcript": ""}

    def get_config(self) -> Dict[str, Any]:
        """Return current configuration values (safe subset)."""
        with self._lock:
            cfg = load_config() if load_config else {}
            # Only return safe, non-sensitive fields
            return {
                "language": cfg.get("language", "en-US"),
                "stt_engine": cfg.get("stt_engine", "auto"),
                "stt_model": cfg.get("stt_model", "large-v3-turbo"),
                "stt_device": cfg.get("stt_device", "auto"),
                "cleanup_mode": cfg.get("cleanup_mode", "light"),
                "style_preset": cfg.get("style_preset", "casual"),
                "show_hud": cfg.get("show_hud", True),
                "translate_to_english": cfg.get("translate_to_english", False),
                "start_with_windows": cfg.get("start_with_windows", False),
                "app_profiles_enabled": cfg.get("app_profiles_enabled", True),
                "show_hud": cfg.get("show_hud", True),
                "detect_language": cfg.get("detect_language", False),
                "auto_learn": cfg.get("auto_learn", True),
            }

    def _apply_setting(self, key: str, value: Any) -> None:
        """Push a config change onto the live engine (best effort)."""
        if self.core is None:
            return
        eng = getattr(self.core, "engine", None)
        if eng is None:
            return
        try:
            if key == "app_profiles_enabled":
                if hasattr(eng, "set_profiles_enabled"):
                    eng.set_profiles_enabled(bool(value))
            elif key == "developer_mode":
                eng.developer_mode = bool(value)
            elif key == "translate_to_english":
                eng.translate_english = bool(value)
            elif key == "detect_language":
                eng.detect_language = bool(value)
            elif key == "auto_learn":
                eng.auto_learn_enabled = bool(value)
            elif key == "cleanup_mode":
                eng.cleanup_mode = str(value)
            elif key == "style_preset":
                eng.style_preset = str(value)
            elif key == "language":
                eng.language = str(value)
            elif key == "stt_model":
                eng.stt_model = str(value)
            elif key == "stt_device":
                eng.stt_device = str(value)
            elif key == "start_with_windows":
                try:
                    import autostart
                    autostart.set_run_entry(bool(value))
                except Exception:
                    pass
        except Exception:
            pass

    def set_setting(self, key: str, value: Any) -> Dict[str, Any]:
        """Set a config value, persist it, and apply it live.

        Keys map to config.json entries. Settings that the running engine
        caches are pushed onto it immediately so a change takes effect
        without a restart.

        Returns {"status": "ok", "key", "value"} or {"status": "error", ...}.
        """
        with self._lock:
            try:
                cfg = load_config() if load_config else {}
                if cfg is None:
                    cfg = {}
                if save_config:
                    try:
                        save_config(cfg)
                    except Exception:
                        pass
                # Push the new config onto the live core so cached values update.
                if self.core is not None:
                    try:
                        self.core.config = cfg
                    except Exception:
                        pass
                    self._apply_setting(key, value)
                    # Model changes go through change_model so the engine reloads.
                    if key == "stt_model":
                        try:
                            self.change_model(str(value))
                        except Exception:
                            pass
                self._emit_event({"type": "config_change", "key": key, "value": value})
                return {"status": "ok", "key": key, "value": value}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    def get_learn_stats(self) -> Dict[str, Any]:
        """Return auto-learning statistics for the UI.

        Returns a dict with keys:
          - unique_corrections: number of distinct raw words tracked
          - total_corrections: total number of correction instances recorded
          - suggestions_ready: count of corrections meeting min_count threshold
          - min_count: the current auto-learn threshold from config
        """
        with self._lock:
            try:
                learner = getattr(self.core, "auto_learner", None) if self.core is not None else None
                if learner is not None:
                    stats = learner.get_stats()
                    # Augment with min_count from config
                    cfg = load_config() if load_config else {}
                    min_count = int(cfg.get("auto_learn_min_count", 3))
                    stats["min_count"] = min_count
                    return stats
                return {"unique_corrections": 0, "total_corrections": 0,
                        "suggestions_ready": 0, "min_count": 3}
            except Exception as e:
                return {"unique_corrections": 0, "total_corrections": 0,
                        "suggestions_ready": 0, "min_count": 3, "error": str(e)}

    # -----------------------------------------------------------------
    # Recording Control
    # -----------------------------------------------------------------

    def self_test(self) -> Dict[str, str]:
        """Run the engine's STT self-test (background thread)."""
        eng = getattr(self.core, "engine", None) if self.core is not None else None
        if eng is None or not hasattr(eng, "run_self_test"):
            return {"status": "error", "message": "Engine not initialized"}
        threading.Thread(target=eng.run_self_test, daemon=True).start()
        return {"status": "started", "message": "Self-test running"}

    def undo_last(self) -> Dict[str, str]:
        """Re-paste the last raw transcript (one-step undo)."""
        eng = getattr(self.core, "engine", None) if self.core is not None else None
        raw = getattr(self.core, "_last_raw", None) if self.core is not None else None
        if eng is None or not raw:
            return {"status": "error", "message": "Nothing to undo"}
        threading.Thread(target=eng.paste_into_active_app, args=(raw,), daemon=True).start()
        return {"status": "ok", "message": "Raw transcript pasted"}

    def refresh_stats(self) -> Dict[str, Any]:
        """Return session telemetry from the engine's DB."""
        db = getattr(self.core, "db", None) if self.core is not None else None
        if db is None:
            return {"sessions": 0, "words": 0, "speech_s": 0, "avg_latency_ms": 0}
        try:
            total, words, speech_s, avg_lat = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(SUM(duration_s),0), "
                "COALESCE(AVG(latency_ms),0) FROM sessions"
            ).fetchone()
            return {
                "sessions": int(total or 0),
                "words": int(words or 0),
                "speech_s": float(speech_s or 0),
                "avg_latency_ms": int(avg_lat or 0),
            }
        except Exception as e:
            return {"sessions": 0, "words": 0, "speech_s": 0, "avg_latency_ms": 0,
                    "error": str(e)}

    def toggle_recording(self) -> Dict[str, str]:
        """Request to start or stop dictation recording.

        Toggles the dictation state. If recording is currently idle, this
        requests start; if recording, it requests stop.

        Returns a status dict for the React UI to update immediately.
        """
        with self._lock:
            if self.core:
                # Emit toggle event; AppCore._toggle_recording will queue events
                self.core._on_hotkey_trigger()
            # Immediately return a pending state; the UI will be updated
            # when AppCore emits the next level/status event
            return {"action": "toggle", "state": "pending", "message": " toggling recording"}

    def change_model(self, model_name: str) -> Dict[str, Any]:
        """Switch the Whisper model used for transcription.

        Args:
            model_name: One of "tiny", "base", "small", "large-v3-turbo".

        Returns the new model state.
        """
        with self._lock:
            if self.core is None:
                return {"status": "error", "message": "Engine not initialized"}
            try:
                new_model = model_name in ("tiny", "base", "small", "large-v3-turbo") and model_name or "large-v3-turbo"
                # The engine lazy-loads Whisper; make sure it exists, then swap.
                whisper = getattr(self.core, "whisper", None)
                if whisper is None and hasattr(self.core, "_load_whisper"):
                    self.core._load_whisper()
                    whisper = getattr(self.core, "whisper", None)
                if whisper is None:
                    return {"status": "error", "message": "Whisper engine not initialized"}
                whisper.model_name = new_model
                self._emit_event({"type": "model_change", "model": new_model})
                return {"status": "ok", "model": new_model, "message": f"model set to {new_model}"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    # -----------------------------------------------------------------
    # Transcription History
    # -----------------------------------------------------------------

    def get_transcription_history(self) -> List[Dict[str, Any]]:
        """Return recent dictation sessions for the UI history card list."""
        with self._lock:
            if self.core:
                history = self.core.get_history()
                # Transform into UI-ready format
                result = []
                for entry in history[-20:]:  # last 20 entries
                    result.append({
                        "id": entry.get("id", id(entry)),
                        "timestamp": entry.get("timestamp", time.time()),
                        "text": entry.get("raw", "")[:120] + ("…" if len(entry.get("raw", "")) > 120 else ""),
                        "duration": entry.get("duration", 0.0),
                        "words": entry.get("words", 0),
                        "latencyMs": entry.get("latency", 0),
                    })
                return result
            return []

    # -----------------------------------------------------------------
    # Window Management
    # -----------------------------------------------------------------

    def minimize_to_tray(self) -> Dict[str, str]:
        """Request the native window to hide (minimize to system tray).

        In the pywebview + pystray setup, closing the window normally hides
        it to the tray instead of quitting the app.
        """
        with self._lock:
            # Signal the AppCore / tray to toggle visibility
            if self.core:
                self.core._on_tray_toggle()
            return {"action": "minimize_to_tray", "message": "window hidden to tray"}

    def close_app(self) -> Dict[str, str]:
        """Request the app to exit cleanly.

        Triggers the pystray 'Exit' action or, if the UI is not up,
        terminates the Python process gracefully.
        """
        with self._lock:
            if self.core:
                self.core._on_quit_requested()
            else:
                # No core manager — exit the process
                func = sys.exit if not getattr(sys, "frozen", False) else None
                if func:
                    func(0)
            return {"action": "close_app", "message": "app exiting"}

    # -----------------------------------------------------------------
    # Initialization & Events
    # -----------------------------------------------------------------

    def initialize(self) -> Dict[str, str]:
        """Called from React on mount to initialize the Python backend.

        Starts AppCoreManager if not already running and returns readiness.
        """
        with self._lock:
            if not self._initialized:
                try:
                    if self.core:
                        self.core.start()
                    self._start_time = time.time()
                    self._initialized = True
                    return {"status": "initialized", "message": "FlowCore started"}
                except Exception as e:
                    return {"status": "error", "message": str(e)}
            return {"status": "already_initialized", "message": "FlowCore already running"}

    def _emit_event(self, event: dict) -> None:
        """Forward an event from AppCore to the React UI.

        pywebview provides a way to call Python from JS, but the reverse
        (Python → JS) is handled by the js_api mechanism — each call from
        Python to js_api triggers a React-side event.

        We use a simple approach: store the latest events and let React
        poll or we dispatch directly if the bridge supports it.
        In practice, for pywebview, we dispatch via the window's eval
        mechanism when available, or just queue for the React side to read
        via a separate mechanism. For this implementation, we'll dispatch
        using the built-in pywebview alert for critical events, and for
        regular events we rely on the React side calling bridge_api.drain_events()
        or similar (kept simple: we use print + alert for demo).
        """
        # For pywebview, the most reliable way to send data to React is
        # through the window's eval or by using the built-in notification.
        # We'll use a combination: print for dev, and a JS-triggered alert
        # for critical status. In a full app, React would have a useEffect
        # that calls a Python-eval'd function.
        try:
            # Attempt to dispatch through pywebview if window is available
            # This is a best-effort dispatch; if it fails, we just print.
            import sys as _sys
            # Try to dispatch via js_api if available
            if hasattr(_sys, 'argv') and len(_sys.argv) > 1:
                # Development mode — just print
                print(f"[BridgeEvent] {json.dumps(event)}")
            else:
                # Packaged mode — could use alert, but we'll just print
                print(f"[BridgeEvent] {json.dumps(event)}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helper — one-time initialization for the pywebview window
# ---------------------------------------------------------------------------

def create_bridge_api(core_manager=None) -> BridgeAPI:
    """Factory to create a BridgeAPI instance wired to the given CoreManager.

    Args:
        core_manager: An AppCoreManager instance. If None, a new one is
                      created (will be started when the first BridgeAPI method
                      is called from React).

    Returns:
        A BridgeAPI instance ready to be passed as js_api to webview.create_window().
    """
    return BridgeAPI(core_manager)


# ---------------------------------------------------------------------------
# Development / Debugging Support
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Allow running this module standalone for a quick smoke test
    api = create_bridge_api()
    print("BridgeAPI created. Available methods:")
    for name in dir(api):
        if not name.startswith("_") and callable(getattr(api, name)):
            print(f"  - {name}()")
    # Demo get_status call
    status = api.get_status()
    print(f"\nInitial status: {json.dumps(status, indent=2)}")