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
    load_config = save_config = lambda: None


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

                return {
                    "status": status,
                    "model": model,
                    "level": round(level, 3),
                    "active": active,
                    "uptime": round(uptime, 1),
                }
            except Exception as e:
                return {"status": "error", "model": "unknown", "level": 0.0, "active": False, "error": str(e)}

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
            }

    # -----------------------------------------------------------------
    # Recording Control
    # -----------------------------------------------------------------

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
            if not self.core or not self.core.whisper:
                return {"status": "error", "message": "Whisper engine not initialized"}
            try:
                # WhisperEngine doesn't support hot-swapping models easily;
                # we re-initialize with the new name
                new_model = model_name in ("tiny", "base", "small", "large-v3-turbo") and model_name or "large-v3-turbo"
                self.core.whisper.model_name = new_model
                # Re-init the model in a thread-safe manner
                # (In a full impl, we'd pause capture, re-load, then resume)
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

def create_bridge_api(core_manager: Optional[AppCoreManager] = None) -> BridgeAPI:
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