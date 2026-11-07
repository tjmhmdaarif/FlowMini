# FlowMini — front end template

An editorial, instrument-style interface for voice dictation. This folder is a
**design template**: presentation only. It contains no engine, no microphone and no
transcripts of its own — everything on screen is driven by an adapter you provide.

Snapshot of `web/src` at the point of export. Copy it into your project, or run it
standalone with the included Vite config.

## Files

```
design/
├── index.html            entry
├── package.json          deps (optional — use your own)
├── tsconfig*.json        optional
├── vite.config.ts        port 3000, host 0.0.0.0
└── src/
    ├── main.tsx          mounts <App />
    ├── App.tsx           layout: masthead, ruler, 01 state / 02 signal, 03 transcript, 04 event stream, footer
    ├── adapter.ts        THE SEAM — contract + inert + preview implementations
    ├── engine.ts         UI-only state, reducer, status meta, languages
    ├── index.css         tokens, atmosphere (aura/spotlight/grain/pointer light), keyframes
    └── components/
        ├── Aperture.tsx       96-line harmonic lens + 96px trigger
        ├── TranscriptStage.tsx editorial serif hero, live caret, edit annotations
        ├── EventStream.tsx     chronological runtime log
        └── SettingsSheet.tsx   hairline controls deck
```

## Requirements

React 19, Tailwind v4 via `@tailwindcss/vite`, `motion`, and the font packages:

```bash
npm i motion
npm i @fontsource-variable/outfit @fontsource/ibm-plex-mono @fontsource/instrument-serif
npm i -D tailwindcss @tailwindcss/vite
```

`index.css` imports the fonts and starts with `@import "tailwindcss";`, so the app
must be built with the Tailwind Vite plugin (see `vite.config.ts`).

## Integrate in three steps

1. Copy `src/` into your app (or keep `design/` as a package and import from it).
2. Implement the adapter — `src/adapter.ts` is the only file that needs to know how
   you talk to your engine.
3. Render `<App adapter={yourAdapter} />`. When an adapter is injected the preview
   switch disappears.

```tsx
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(<App adapter={myAdapter} />);
```

## The adapter contract

```ts
type FlowMiniAdapter = {
  attach(listener: (event: FlowEvent) => void): () => void; // return unsubscribe
  startPushToTalk(): void;
  stopPushToTalk(): void;
  setSetting<K extends keyof Settings>(key: K, value: Settings[K]): void;
  selfTest(): void;
  refreshStats(): void;
  undo(): void;
};
```

| event | payload | UI effect |
|---|---|---|
| `status` | `idle` \| `recording` \| `processing` \| `vad` \| `error` | state word, `--tone`, aura, lens |
| `level` | `0…1` | lens line lengths, level arc, signal hairline |
| `partial` | text | streaming serif text + caret at 55% ink |
| `result` | raw, final, language, confidence, edits, latencyMs | committed gradient text, figures, annotations |
| `undo` | text | restores a raw transcript |
| `log` | text, tag (`ok`/`warn`/`err`/`dim`) | event stream line |
| `settings` | partial Settings | pushes engine-side settings back into the UI |
| `connected` | boolean | adapter chip + footer dot |
| `error` | message | red log line + fault state |

Settings shape: `{ language, cleanup: "off"|"light"|"medium", style:
"formal"|"casual"|"very_casual"|"excited", translate, developer, vad }`.

### Transport sketches

WebSocket bridge

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

Tauri / Electron

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
transcript (`clamp(2rem, 4.4vw, 3.9rem)`, `1.02` leading, `-0.015em`), **Outfit
Variable** light for the state word (`clamp(2.1rem, 3.4vw, 3rem)`), **IBM Plex Mono**
9px at `0.3em` tracking for every label, 14px tabular for figures.

`--tone` is set on the frame from `STATUS_META`; the aura, spotlight, lens, arc and
trigger all read it, so one state change re-tints the whole composition.

## Ground rules

- **Never synthesise transcripts.** The default adapter is inert on purpose; the
  preview adapter is opt-in and labels every line it emits.
- Keep engine calls inside the adapter. Components only render state and call the
  six adapter methods.
- Respect `prefers-reduced-motion` — provided via `useReducedMotion` and a CSS block.
