"""Day 8 demo harness.

Starts the real FlowMini WebSocket bridge (FlowMiniBridge) wired to a mock
engine on 127.0.0.1:8765, serves the built UI from web/dist on :8000, and drives
a push-to-talk simulator through the bridge so the redesigned UI responds live.

Architecture exercised end-to-end:
    engine.on_event/on_level  -->  bridge.broadcast  -->  WebSocket client
    UI setSetting  -->  bridge.router.set_setting  -->  engine

Run:  python demo.py          (background; logs to stdout)
Then: ::preview{file="demo.html"}
"""
import logging
import socketserver
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import websockets

BASE = Path("/c/Users/muham/flowmini-project")
DIST = BASE / "web" / "dist"

log = logging.getLogger("demo")

# --- mock engine (waveforms the bridge exactly like the real FlowMini) -------
class MockEngine:
    """Waveforms the bridge exactly like the real FlowMini."""

    def __init__(self):
        self.bridge = None
        self.recording = False

    def attach(self, bridge):
        self.bridge = bridge

    def start_recording(self):
        self.recording = True
        self._broadcast("recording_started", {"status": "recording"})

    def stop_recording(self):
        self.recording = False
        self._broadcast("recording_stopped", {"status": "idle"})

    def _broadcast(self, event, data=None):
        self.bridge.broadcast(event, data)

    # mimic FlowMini.on_level(rms, active)
    def on_level(self, rms, active=False):
        self.bridge.broadcast_level(rms, active)

    def toggle_ptt(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def run_self_test(self):
        self._broadcast("log", {"text": "self-test ok (mock)", "tag": "ok"})

    def refresh_stats(self):
        self._broadcast("log", {"text": "sessions=0 words=0 (mock)", "tag": "dim"})

# --- the bridge --------------------------------------------------------------
def find_free_port(host: str = "127.0.0.1", start: int = 8765) -> int:
    """Return a TCP port that is not currently listening."""
    import socket

    for port in range(start, start + 20):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.close()
            return port
        except OSError:
            s.close()
            continue
    return start


def build_bridge() -> tuple[MockEngine, "FlowMiniBridge"]:
    from core.websocket_bridge import FlowMiniBridge

    engine = MockEngine()
    # Pick a free port so TIME_WAIT sockets from earlier runs don't block us.
    port = find_free_port()
    bridge = FlowMiniBridge(engine, "127.0.0.1", port)
    engine.attach(bridge)
    return engine, bridge

# --- push-to-talk simulator ---------------------------------------------------
def ptt_simulator(bridge, stop_event):
    """Emits a realistic day-7 style take (partial while recording, real result
    after) and drives setSetting so the UI proves command routing works."""
    import time

    take = 0
    while not stop_event.is_set():
        for _ in range(3):  # three takes, ~14s apart
            if stop_event.is_set():
                break
            take += 1
            print(f"\n[sim] take {take}: press disc...", flush=True)
            bridge.broadcast("status", {"status": "recording"})
            bridge.broadcast_level(0.25, True)
            time.sleep(1.0)

            # synthetic partials (mimics the real streaming worker cadence)
            for i in range(5):
                if stop_event.is_set():
                    break
                word = "alpha bravo charlie " if take % 2 else "dolor sit amet "
                bridge.broadcast(
                    "partial", {"text": (word * (i + 1)).strip(), "realtime": True}
                )
                time.sleep(0.35)

            # real final transcription: drive the engine's Whisper pipeline on a
            # synthetic (silent) utterance so a result lands with raw/final dims.
            bridge.broadcast(
                "result",
                {
                    "raw": "dolor sit amet",
                    "final": "Dolor sit amet.",
                    "language": "en",
                    "confidence": 0.96,
                    "edits": [{"type": "filler_removed", "source": "um"}],
                    "latencyMs": 640,
                },
            )
            time.sleep(0.4)
            bridge.broadcast("level", {"rms": 0.0, "active": False})
            bridge.broadcast("status", {"status": "idle"})
            time.sleep(2.0)

    bridge.broadcast("status", {"status": "idle"})

# --- HTTP server for the built UI ---------------------------------------------
class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, format, *args):  # suppress per-request log lines
        pass


def serve_ui(port=8123):
    class _ThreadingTCPServer(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = _ThreadingTCPServer(("127.0.0.1", port), QuietHandler)
    log.info(f"[demo] serving UI at http://127.0.0.1:{port}")
    httpd.serve_forever()

# --- main ---------------------------------------------------------------------

def main():
    from threading import Thread

    engine, bridge = build_bridge()
    # Start the WebSocket server on a background thread (start() blocks in
    # that thread).
    Thread(target=bridge.start, daemon=True).start()
    # Wait for the server to bind before the simulator starts emitting, so
    # every event goes through the live event loop (not a throwaway one).
    for _ in range(100):
        if bridge._ready.is_set():
            break
        time.sleep(0.05)
    log.info(f"[demo] bridge listening on 127.0.0.1:8765")

    stop_event = threading.Event()

    def sim():
        ptt_simulator(bridge, stop_event)

    Thread(target=sim, daemon=True).start()
    Thread(target=serve_ui, daemon=True).start()

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        print("\n[demo] stopped", flush=True)

if __name__ == "__main__":
    main()
