"""FlowMini — Main Launcher Script.

Integrates pywebview with the AppCoreManager BridgeAPI for a 100% offline,
native desktop experience. The React frontend runs inside a native window
via pywebview, with Python backend logic exposed through js_api.

Features:
  - PyWebView window (chromium-based, native OS window)
  - BridgeAPI exposes all Python functionality to React
  - AppCoreManager handles audio, ASR, hotkeys, tray offline
  - pystray system tray integration (close → hide, not quit)
  - Development mode + PyInstaller bundle support
  - Fallback: works in browser preview mode without pywebview
"""

import os
import sys
import json
import Path
from pathlib import Path

# ---------------------------------------------------------------------------
# Path Setup
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    # PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS)
    # Frontend dist is bundled inside the exe; we look relative to exe dir
    FRONTEND_DIST = Path(sys._MEIPASS) / "web" / "dist"
    # Also check _MEIPASS / "_MEIPASS/web/dist"
    if not FRONTEND_DIST.exists():
        FRONTEND_DIST = Path(sys._MEIPASS) / "web" / "dist"
else:
    # Development mode
    BASE_DIR = Path(__file__).parent.parent.parent  # project root
    FRONTEND_DIST = BASE_DIR / "web" / "dist"


# ---------------------------------------------------------------------------
# Add project core to path
# ---------------------------------------------------------------------------
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Import BridgeAPI and AppCoreManager from our core modules
try:
    from core.bridge_api import BridgeAPI, create_bridge_api
    from core.app_core import AppCoreManager
except ImportError as e:
    print(f"[FATAL] Could not import core modules: {e}")
    print("Ensure you've run: pip install -e . or installed dependencies")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helper: Load Frontend HTML (development or bundled)
# ---------------------------------------------------------------------------

def load_frontend_html() -> str:
    """Load the index.html from the bundled or development frontend dist."""
    # Priority order:
    # 1. Bundled inside PyInstaller executable directory
    # 2. Development ../frontend/dist/ relative to project root
    # 3. Fallback: simple inline HTML (for debugging)

    candidates = []

    if getattr(sys, "frozen", False):
        candidates.append(FRONTEND_DIST / "index.html")
        candidates.append(Path(sys._MEIPASS) / "frontend" / "dist" / "index.html")

    # Development path: project root / frontend / dist
    dev_path = BASE_DIR / "frontend" / "dist" / "index.html"
    if dev_path.exists():
        candidates.append(dev_path)

    for path in candidates:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                print(f"[Warn] Could not read {path}: {e}")
                continue

    # Fallback: minimal HTML that works in browser preview
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>FlowMini — Offline Mode</title>
  <style>
    body { font-family: system-ui, sans-serif; padding: 2rem; background: #0b0d13; color: #e0e6f0; }
    .fallback { max-width: 600px; margin: 0 auto; }
    .status { padding: 1rem; background: #1e2431; border-radius: 8; margin: 1rem 0; }
    .error { color: #ff7849; }
  </style>
</head>
<body>
  <div class="fallback">
    <h1>FlowMini</h1>
    <p class="error">Running in browser preview mode.</p>
    <div class="status" id="fallback-status">Initializing...</div>
    <script>
      // Minimal fallback — just shows status
      window.addEventListener('load', () => {
        document.getElementById('fallback-status').textContent = 'No pywebview BridgeAPI available';
      });
    </script>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main App Entry
# ---------------------------------------------------------------------------

def main():
    """Main entry point for FlowMini desktop application."""
    print("[FlowMini] Starting...")

    # -----------------------------------------------------------------
    # Initialize BridgeAPI (Python → React bridge)
    # -----------------------------------------------------------------
    bridge_api = create_bridge_api()

    # Track start time for UI uptime display
    bridge_api._start_time = time.time()

    # -----------------------------------------------------------------
    # Initialize AppCoreManager (Python backend)
    # -----------------------------------------------------------------
    core = AppCoreManager(bridge_api=bridge_api)

    # Start all background services (audio, hotkeys, tray, Whisper model)
    try:
        core.start()
        print("[FlowCore] Background services started.")
    except Exception as e:
        print(f"[FATAL] Failed to start FlowCore: {e}")
        # We'll still try to show the window; BridgeAPI has fallbacks
        core = None

    # -----------------------------------------------------------------
    # Load Frontend HTML
    # -----------------------------------------------------------------
    frontend_html = load_frontend_html()
    if not frontend_html:
        print("[FATAL] Could not load frontend HTML — aborting.")
        sys.exit(1)

    # -----------------------------------------------------------------
    # Create pywebview Window
    # -----------------------------------------------------------------
    try:
        import webview

        window_title = "FlowMini — Voice Dictation"

        # Create the webview window with js_api=BridgeAPI
        # The BridgeAPI instance exposes methods as window.pywebview.api.MethodName()
        webview.create_window(
            title=window_title,
            html=frontend_html,
            js_api=bridge_api,  # <-- Python methods exposed to React
            # Optional: resizeable, on_top, etc.
            # width=1400, height=900,
            # resizable=True,
        )

        print("[WebView] Window created with pywebview.")
    except ImportError:
        print("[Warn] pywebview not installed — running in browser fallback mode.")
        # Fallback: just load the HTML in a browser tab or show the fallback HTML
        # For now, print a message and exit gracefully
        print("Install pywebview: pip install pywebview")
        # Show the fallback HTML in a simple way:
        # We'll just print the HTML and exit; the user can open it in a browser
        print("\n--- Fallback Frontend HTML (save as index.html and open in browser) ---")
        print(load_frontend_html())
        print("--- End Fallback HTML ---")
        sys.exit(0)
    except Exception as e:
        print(f"[FATAL] Could not create pywebview window: {e}")
        # Fallback: print HTML and exit
        print("\n--- Fallback Frontend HTML ---")
        print(load_frontend_html())
        print("--- End Fallback HTML ---")
        sys.exit(1)

    # -----------------------------------------------------------------
    # Start pywebview UI loop
    # -----------------------------------------------------------------
    try:
        webview.start()  # blocks; runs the chromium-based native window
    except KeyboardInterrupt:
        print("[FlowMini] Interrupted by user.")
    except Exception as e:
        print(f"[FATAL] pywebview start error: {e}")

    # -----------------------------------------------------------------
    # Clean shutdown
    # -----------------------------------------------------------------
    print("[FlowMini] Shutting down...")
    if core:
        core.stop()
    print("[FlowMini] Goodbye!")


if __name__ == "__main__":
    main()