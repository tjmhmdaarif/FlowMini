"""FlowMini — WebSocket bridge.

Connects a :class:`FlowMini` engine instance to a web UI (or any WebSocket
client) over a local TCP socket. Bidirectional:

  Engine -> UI  : status, level, partial, result, log, settings, connected, error
  UI -> Engine  : start, stop, setting, self_test, stats, undo

The engine talks to its UI through callbacks (``on_event``, ``on_level``);
the bridge is one implementation of those callbacks and replays the events on
WebSockets for the browser-controlled UI. A separate in-process test bridge
(:class:`TestBridge`) lets the UI reducer be unit-tested without a socket.

Run the server::

    from flow_mini import load_config, init_db
    from core.websocket_bridge import FlowMiniBridge
    cfg = load_config()
    bridge = FlowMiniBridge(cfg, "127.0.0.1", 8765)
    bridge.start()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

import websockets

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Engine -> client event mapping
# --------------------------------------------------------------------------
# FlowMini "engine event" -> flow event type + payload extractor.
# The engine's FlowMini.on_event fires with (event, data).
_STATUS_MAP = {
    "idle": "idle",
    "recording_started": "recording",
    "recording_stopped": "idle",
    "processing": "processing",
    "vad_on": "vad",
    "vad_off": "idle",
    "busy": "processing",
    "whisper_loading": "processing",
    "whisper_ready": "idle",
    "profile": "profile",
}

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "language": "en-US",
    "cleanup": "light",
    "style": "casual",
    "translate": False,
    "developer": False,
    "vad": False,
}


def _engine_to_flow(event: str, data: Optional[dict]) -> Dict[str, Any]:
    """Translate a *raw* engine emit into a ``FlowEvent`` payload dict."""
    payload: Dict[str, Any] = {"type": event}
    if not data:
        return payload
    if event == "level":
        # ``on_level(rms, active)`` is called positionally by the engine; the
        # bridge wrapper normalises to a dict. Accept both forms.
        if isinstance(data, dict):
            rms = float(data.get("rms", 0.0) or 0.0)
            active = bool(data.get("active", False))
        else:
            rms = float(data[0]) if data else 0.0
            active = bool(data[1]) if len(data) > 1 else False
        payload.update(
            {
                "level": round(min(1.0, max(0.0, rms / 3000.0)), 3),
                "active": active,
            }
        )
    elif event == "partial_transcript":
        payload.update({"text": data.get("text", "")})
    elif event == "asr_text":
        payload.update({"raw": data.get("raw", ""), "language": data.get("lang")})
    elif event == "pasted":
        payload.update(
            {
                "final": data.get("text", ""),
                "raw": data.get("raw", ""),
                "language": data.get("lang"),
                "confidence": float(data.get("confidence", 0.0) or 0.0),
                "edits": data.get("edits", []),
                "latencyMs": int(data.get("latency_ms", 0) or 0),
            }
        )
    elif event == "log":
        payload.update({"text": data.get("text", ""), "tag": data.get("tag", "dim")})
    elif event == "settings":
        payload.update({"patch": data.get("patch", {})})
    elif event == "status":
        payload.update({"status": data.get("status", "")})
    elif event == "connected":
        payload.update({"value": bool(data.get("value", False))})
    elif event == "error":
        payload.update({"message": str(data.get("message", ""))})
    return payload


def engine_status_to_flow(engine_event: str) -> Optional[str]:
    """Map a FlowMini ``_emit`` status event to a UI ``status`` value."""
    return _STATUS_MAP.get(engine_event)


# --------------------------------------------------------------------------
# Client message routing (UI -> engine)
# --------------------------------------------------------------------------
class BridgeRouter:
    """Dispatches client commands onto the core engine."""

    def __init__(self, engine: Any):
        self.engine = engine
        self._pending_stats: Dict[str, Any] = {}

    # -- engine API ---------------------------------------------------------

    def start(self) -> None:
        try:
            self.engine.start_recording()
        except Exception as exc:  # pragma: no cover - best effort
            log.exception("bridge start failed: %s", exc)

    def stop(self) -> None:
        try:
            self.engine.stop_recording()
        except Exception as exc:  # pragma: no cover - best effort
            log.exception("bridge stop failed: %s", exc)

    def set_setting(self, key: str, value: Any) -> None:
        try:
            if hasattr(self.engine, key):
                setattr(self.engine, key, value)
            elif key in self.engine.cfg:
                self.engine.cfg[key] = value
            else:
                log.warning("bridge: unknown setting %r", key)
        except Exception as exc:  # pragma: no cover - best effort
            log.exception("bridge set_setting failed: %s", exc)

    def self_test(self) -> None:
        if hasattr(self.engine, "run_self_test"):
            try:
                self.engine.run_self_test()
            except Exception as exc:  # pragma: no cover - best effort
                log.exception("bridge self_test failed: %s", exc)

    def refresh_stats(self) -> None:
        try:
            from flow_mini import print_stats

            conn = self.engine.db
            if conn is not None:
                print_stats(conn)
        except Exception as exc:  # pragma: no cover - best effort
            log.exception("bridge stats failed: %s", exc)

    def undo(self) -> None:
        # No engine-level undo; the UI retains the last raw transcript and
        # restores it locally when the user clicks Undo.
        log.debug("bridge.undo: no engine undo (UI restores raw locally)")


# --------------------------------------------------------------------------
# Test bridge (no sockets) used by the UI reducer unit tests
# --------------------------------------------------------------------------
class TestBridge:
    """In-process stand-in for the WebSocket bridge. Stores the last event
    and offers the same command shape as :class:`BridgeRouter`."""

    def __init__(self):
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []
        self.last_event: Dict[str, Any] = {}
        self.router = BridgeRouter(None)

    def attach(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        self.listeners.append(listener)

    def broadcast(self, event: str, data: Optional[dict]) -> None:
        payload = _engine_to_flow(event, data)
        self.last_event = payload
        for listener in self.listeners:
            try:
                listener(payload)
            except Exception:
                log.exception("TestBridge listener failed")

    def start(self) -> None:
        self.router.start()

    def stop(self) -> None:
        self.router.stop()

    def set_setting(self, key: str, value: Any) -> None:
        self.router.set_setting(key, value)

    def self_test(self) -> None:
        self.router.self_test()

    def refresh_stats(self) -> None:
        self.router.refresh_stats()

    def undo(self) -> None:
        self.router.undo()


# --------------------------------------------------------------------------
# Real WebSocket bridge
# --------------------------------------------------------------------------
class FlowMiniBridge:
    """WebSocket bridge between a FlowMini engine and the web UI."""

    def __init__(
        self,
        engine: Any,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        broadcaster: Optional["FlowMiniBridge"] = None,
    ):
        self.engine = engine
        self.host = host
        self.port = port
        self.router = BridgeRouter(engine)
        self._clients: List[websockets.ServerConnection] = []
        self._lock = asyncio.Lock()
        self._runner: Optional[asyncio.AbstractEventLoop] = None
        self._ready = asyncio.Event()

    # -- public API -------------------------------------------------------

    def start(self) -> None:
        """Start the server on a background thread (blocking in that thread)."""
        self._runner = asyncio.new_event_loop()
        asyncio.set_event_loop(self._runner)
        try:
            self._runner.run_until_complete(self._serve())
        except Exception:
            log.exception("bridge server crashed")
            raise
        finally:
            self._runner.close()
            self._runner = None

    async def _serve(self) -> None:
        """Set up the server and run forever until cancelled."""
        self._server = await websockets.serve(
            self._client_handler, self.host, self.port
        )
        self._ready.set()
        try:
            await asyncio.Future()  # run forever until cancellation
        finally:
            self._server.close()
            await self._server.wait_closed()

    def stop(self) -> None:
        if self._runner is not None and self._runner.is_running():
            self._runner.call_soon_threadsafe(self._runner.stop)
        self._close_all()

    def broadcast(self, event: str, data: Optional[dict] = None) -> None:
        """Push an engine event to every connected client (thread-safe)."""
        payload = _engine_to_flow(event, data)
        if not payload:
            return
        if self._runner is not None and self._runner.is_running():
            # Schedule the send coroutine on the server loop from the
            # simulator/UI thread.
            asyncio.run_coroutine_threadsafe(self._send_to_clients(payload), self._runner)
        else:
            # Server not running (e.g. unit test): queue for the test bridge.
            asyncio.run_coroutine_threadsafe(self._send_to_clients(payload), asyncio.new_event_loop())

    def broadcast_level(self, rms: float, active: bool = False) -> None:
        self.broadcast("level", {"rms": rms, "active": active})

    def on_client_connect(self) -> None:
        """Announce to clients that the adapter is live."""
        self.broadcast("connected", {"value": True})

    # -- WebSocket handler ------------------------------------------------

    async def _client_handler(self, websocket: websockets.ServerConnection) -> None:
        self._add_client(websocket)
        self.on_client_connect()
        try:
            async for message in websocket:
                await self._route_client_message(websocket, message)
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            self._remove_client(websocket)

    async def _route_client_message(self, websocket, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        cmd = payload.get("cmd")
        if cmd == "start":
            self.router.start()
        elif cmd == "stop":
            self.router.stop()
        elif cmd == "setting":
            self.router.set_setting(payload.get("key"), payload.get("value"))
        elif cmd == "self_test":
            self.router.self_test()
        elif cmd == "stats":
            self.router.refresh_stats()
        elif cmd == "undo":
            self.router.undo()
        else:
            log.warning("bridge: unknown command %r", cmd)

    # -- internal ---------------------------------------------------------

    async def _send_to_clients(self, payload: Dict[str, Any]) -> None:
        if not self._clients:
            return
        dead: List[websockets.ServerConnection] = []
        for ws in self._clients:
            try:
                await ws.send(json.dumps(payload))
            except (websockets.ConnectionClosed, OSError):
                dead.append(ws)
        for ws in dead:
            self._remove_client(ws)

    def _add_client(self, ws: websockets.ServerConnection) -> None:
        self._clients.append(ws)

    def _remove_client(self, ws: websockets.ServerConnection) -> None:
        try:
            self._clients.remove(ws)
        except ValueError:
            pass

    def _close_all(self) -> None:
        for ws in list(self._clients):
            try:
                ws.close()
            except Exception:
                pass
        self._clients.clear()


# -- convenience ----------------------------------------------------------------

def start_bridge(engine: Any, host: str = "127.0.0.1", port: int = 8765) -> FlowMiniBridge:
    """Create the bridge and start the server. Blocks the caller until the
    server stops (normally at process exit)."""
    bridge = FlowMiniBridge(engine, host, port)
    bridge.start()
    return bridge
