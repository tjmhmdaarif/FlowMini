# FlowMini — front end

**Redesigned for Day 8** as a real-time streaming "instrument" UI, adopted from
`design-template/`. This is the UI driven by the core engine through the
WebSocket bridge (`core/websocket_bridge.py`), implementing the adapter contract
below.

## Not a demo

The previous `web/` was a placeholder that did not call `flow_mini.py`.
`design-template/` is the real, engine-ready UI. The old placeholder is preserved
in `old-web-scaffold/`.

## Run

```powershell
cd web
npm install        # first time only (React 19, Tailwind v4, motion, fonts)
npm run dev        # -> http://localhost:3000
npm run build      # production build (tsc -b && vite build)
```

`vite.config.ts` binds `0.0.0.0:3000` so the UI can run standalone or beside the
exe. The built static files ship with `flowmini_app.py` as the desktop surface.

## The adapter seam

Everything on screen is driven by an adapter that implements
`FlowMiniAdapter` — the bridge is the only place that talks to the engine. The UI
never invents transcripts.

```ts
type FlowMiniAdapter = {
  attach(listener: (event: FlowEvent) => void): () => void;
  startPushToTalk(): void;
  stopPushToTalk(): void;
  setSetting<K extends keyof Settings>(key: K, value: Settings[K]): void;
  selfTest(): void;
  refreshStats(): void;
  undo(): void;
};

type FlowEvent =
  | { type: "status"; status: Status }
  | { type: "level"; level: number }
  | { type: "partial"; text: string }
  | { type: "result"; raw: string; final: string; language?; confidence?; edits?; latencyMs? }
  | { type: "undo"; text: string }
  | { type: "log"; text: string; tag?: Tag }
  | { type: "settings"; patch: Partial<Settings> }
  | { type: "connected"; value: boolean }
  | { type: "error"; message: string };
```

### Transport sketches

**WebSocket bridge** (recommended)

```ts
export function createSocketAdapter(url = "ws://127.0.0.1:8765"): FlowMiniAdapter {
  let listener: ((e: FlowEvent) => void) | null = null;
  let socket: WebSocket | null = null;
  const send = (payload: unknown) => socket?.readyState === 1 && socket.send(JSON.stringify(payload));
  return {
    attach(next) {
      listener = next;
      socket = new WebSocket(url);
      socket.onmessage = (message) => listener?.(JSON.parse(message.data) as FlowEvent);
      socket.onopen = () => listener?.({ type: "connected", value: true });
      socket.onclose = () => listener?.({ type: "connected", value: false });
      return () => socket?.close();
    },
    startPushToTalk: () => send({ cmd: "start" }),
    stopPushToTalk: () => send({ cmd: "stop" }),
    setSetting: (key, value) => send({ cmd: "setting", key, value }),
    selfTest: () => send({ cmd: "self_test" }),
    refreshStats: () => send({ cmd: "stats" }),
    undo: () => send({ cmd: "undo" }),
  };
}
```

**Tauri / Electron** (same contract, IPC transport)

```ts
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

const adapter: FlowMiniAdapter = {
  attach(next) {
    const unlisten = listen<FlowEvent>("flowmini://event", (e) => next(e.payload));
    return () => void unlisten.then((off) => off());
  },
  startPushToTalk: () => void invoke("start_ptt"),
  stopPushToTalk: () => void invoke("stop_ptt"),
  setSetting: (key, value) => void invoke("set_setting", { key, value }),
  selfTest: () => void invoke("self_test"),
  refreshStats: () => void invoke("refresh_stats"),
  undo: () => void invoke("undo"),
};
```

## Design tokens

| token | value | use |
|---|---|---|
| `--color-shell` | `#05060a` | page |
| `--color-ink` | `#f5f7fc` | committed transcript, figures |
| `--color-body` | `#a4aec2` | hints, secondary rows |
| `--color-mute` | `#5a6478` | micro-labels, log |
| `--color-accent` | `#ff3b4e` | recording tone, caret |
| `--color-ok` | `#4ade9b` | idle, adapter live |
| `--color-warn` | `#ffb02e` | processing, preview |
| `--color-bad` | `#ff6b7d` | fault |
| `--color-info` | `#6aa8ff` | hands-free |

Hairlines are `rgb(255 255 255 / 0.06–0.10)`. Type: **Instrument Serif** for the
committed transcript (`clamp(2rem, 4.4vw, 3.9rem)`, `1.02` leading, `-0.015em`),
**Outfit Variable** light for the state word (`clamp(2.1rem, 3.4vw, 3rem)`), and
**IBM Plex Mono** 9px at `0.3em` tracking for every label, 14px tabular for
figures.

`--tone` is set on the frame from `STATUS_META`; the aura, spotlight, lens, arc
and trigger all read it, so one state change re-tints the whole composition.

## Components

- `App.tsx` — masthead, ruler, 01 state / 02 signal, 03 transcript, 04 event
  stream, footer, keyboard short-cuts (Ctrl+Alt+D take, Ctrl+Alt+F hands-free).
- `Aperture.tsx` — harmonic lens + 96px disc trigger; drives the signal arc and
  status tint.
- `TranscriptStage.tsx` — editorial serif hero, live caret, edit annotations.
- `EventStream.tsx` — chronological runtime log.
- `SettingsSheet.tsx` — hairline controls deck (voice, cleanup, session).
- `engine.ts` — UI state store (reducer, `STATUS_META`, `LANGUAGES`,
  `initialState`). Local UI state only; the engine owns audio/ASR/sessions.

## Day 8 status

- ✅ Design template adopted into `web/`
- ✅ Old placeholder backed up to `old-web-scaffold/`
- ⏳ Bridge module (`core/websocket_bridge.py`) — inbound
- ⏳ Adapter implementation + `main.tsx` wiring — outbound
- ⏳ New UI ideas (mic-level streaming, model/device picker, mic selection,
      undo, telemetry footer, self-test, PWA option) — outbound
- ⏳ Unit + mock UI tests — outbound

See `DAY8_PLAN.md` for the full plan.
