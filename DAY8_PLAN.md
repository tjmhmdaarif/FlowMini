# FlowMini — Day 8 Plan: Real-time Streaming UI (Redesigned)

**Date drafted:** 2026-11-07
**Objective:** Replace the placeholder React control panel (`web/`) with the
editorial "instrument"-style UI from `design-template/`, then wire it to the core
engine through a real-time bridge. Plus a set of new capabilities the design
template leaves open.

---

## 1. Context

- **No Day 8 plan existed.** Days 1–7 are complete (Day 7 = true real-time
  streaming partial transcript, `v1.1.0.6`, merged to `main` and
  `day7-streaming-transcript`).
- The repo's `web/` was explicitly a *visual + interaction demo* that did **not**
  call `flow_mini.py`.
- `design-template/` (extracted from `Downloads/design-template.zip`) is the
  redesign spec: a full editorial instrument UI, an adapter seam, and a
  reducer-based UI state store.

---

## 2. Goal

1. Adopt `design-template/` as the FlowMini frontend.
2. Bridge the Python core engine and the React UI so they talk over a local
   WebSocket (no UI-side transcript synthesis — the engine is the only source of
   truth for audio/ASR).
3. Add new capabilities the template leaves unimplemented (see §7).

---

## 3. Guiding principles (from the design template)

- **Never synthesise transcripts.** The UI renders what the engine emits.
- Engine calls live **only** in the adapter/bridge. Components render state and
  call the adapter's six methods.
- **Respect `prefers-reduced-motion`** (provided via `useReducedMotion` + CSS).
- **One source of truth:** the engine (Python) owns audio, ASR, cleanup, and
  sessions; `engine.ts` is the UI state store, not the source of truth.

---

## 4. Deliverables

| # | Deliverable | Path | Verify |
|---|-------------|------|--------|
| 1 | Adopt design-template as the UI | `web/` | `cd web && npm run build` succeeds |
| 2 | Bridge module (engine → UI) | `core/websocket_bridge.py` | new unit tests pass |
| 3 | Config for the bridge | `config.json` (ui address/port) | `python flowmini_app.py` reads it |
| 4 | New faceted UI ideas (§7) | `web/src/`, `core/websocket_bridge.py` | manual + mock tests |
| 5 | `web/README.md` updated | `web/README.md` | describes wired UI |
| 6 | Version bump | `APP_VERSION` → `v1.1.0.7` | `flowmini_app.py` constant |

---

## 5. Architecture

```
┌─ Core engine (Python) ─────────────────────────────┐
│ flow_mini.py  flowmini_app.py  SQLite sessions     │
│ (audio → ASR → cleanup → paste)                     │
└──────┬─────────────────────────────────────────────┘
       │ WebSocket (JSON) — optional stdlib HTTP static for built UI
┌──────▼─────────────────────────────────────────────┐
│ core/websocket_bridge.py                            │
│  • accept WS clients   • route client commands     │
│  • broadcast engine events to all clients          │
│  • in-process bridge for tests                     │
└──────┬─────────────────────────────────────────────┘
       │ FlowEvent (json)
┌──────▼─────────────────────────────────────────────┐
│ React UI (design-template → web/)                  │
│  • adapter.ts  (the seam)   • engine.ts (UI state) │
│  • Aperture, TranscriptStage, EventStream,        │
│    SettingsSheet, App.tsx                         │
└────────────────────────────────────────────────────┘
```

### The adapter seam (already in the design template)

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

### Event mapping (engine → UI)

| Engine emit | `FlowEvent` |
|---|---|
| recording active / VAD speech / stop | `status` |
| mic peak/RMS (live streaming) | `level` |
| partial transcription while speaking | `partial` |
| final + raw + language + confidence + edits + latency | `result` |
| raw transcript restored | `undo` |
| log line (ok/warn/err/dim) | `log` |
| setting change | `settings` |
| session stats | `settings` + footer numerals |
| error | `error` |

---

## 6. The bridge (new module: `core/websocket_bridge.py`)

A **stdlib-friendly** layer so the engine never depends on a heavy framework.

- **Transport:** `websockets` (or a thin stdlib `socket` fallback) on a
  configurable host/port (default `127.0.0.1:8765`, read from `config.json`).
- **Client commands** (from `adapter.ts` / `createSocketAdapter`):
  - `{ cmd: "start" }` → engine `start_recording`
  - `{ cmd: "stop" }` → engine `stop_recording`
  - `{ cmd: "setting", key, value }` → engine config writer
  - `{ cmd: "self_test" }` → engine self-test
  - `{ cmd: "stats" }` → engine session stats
  - `{ cmd: "undo" }` → engine raw-restore
- **Server pushes** (engine → client) the `FlowEvent` set in §5.
- **In-process test bridge** (no sockets) so the UI reducer can be unit-tested
  without a real WebSocket, and an end-to-end mock test can simulate `PTT →
  partial → result`.

### Why a bridge?
- Decouples the Python engine (Tkinter + ASR) from the JS UI
  (React + Tailwind). They can ship, run, and version independently.
- Makes the UI **portable**: it can also be opened from a second device on the
  LAN (privacy note: voice data stays local; the bridge binds `127.0.0.1` by
  default, LAN exposure only if the user explicitly relaxes it).

---

## 7. New features (my ideas, not in the design template)

| # | Idea | UI / engine change | Why it's in scope |
|---|------|--------------------|-------------------|
| 1 | **Real-time mic level** | Engine emits `level` (0–1) per ~100 ms while recording; `Aperture` lens + HUD signal arc + status bar drive off it | Day 7's streaming did not stream raw level continuously; the HUD's mic level should reflect it |
| 2 | **Model / device picker** | UI SettingsSheet adds *live model* (tiny/live vs large-v3-turbo/final) + *device* (auto/GPU/CPU int8) | Day 7's dual-model design is real but only reachable via `config.json`; exposing it in the UI closes the loop |
| 3 | **Mic device enumeration + selection** | Engine lists available input devices; SettingsSheet dropdown; on device error, rebuild stream automatically (already implemented in `flow_mini.py`) | Users on Windows frequently have multiple mics; keyboard-only hotkeys are a barrier |
| 4 | **Undo / raw transcript recall** | `canUndo` flag + engine returns `raw`; `SettingsSheet` "Undo raw" button | The template's `undo` event exists; Day 7's flow needs raw↔final comparison |
| 5 | **Session telemetry footer** | Footer numerals: sessions count, word count, last-take latency, confidence | The template already renders these; the engine's SQLite log feeds them |
| 6 | **Self-test panel** | `selfTest()` exercises mic path, model load (warm), and ASR stub; results appear in `EventStream` as log lines | Makes the app debuggable without the user opening logs |
| 7 | **PWA / headless bundling option** | Build the UI (`vite build`) and optionally serve it from the exe as a local page, or install as a desktop PWA | The design template is a real app, not a live demo; needs a run target |

---

## 8. React UI (design-template)

- Source of truth: `design-template/` (already extracted to the repo).
- Drop its `src/` into `web/` (replacing the old scaffold), keeping
  `design-template/` as the canonical spec.
- **Do not change** `engine.ts` / `App.tsx` semantics — they are the UI store.
- Only change: `adapter.ts` → implement `FlowMiniAdapter` against
  `core/websocket_bridge.py`; `main.tsx` → mount with the real adapter.
- Keep the design tokens exactly as specified (`--color-*`, fonts, `--tone`
  driven by `STATUS_META`).

---

## 9. Testing & validation

| Suite | What it proves |
|---|---|
| Bridge unit tests | Event mapping, command routing, error handling, in-process bridge |
| Mock UI test | `PTT → partial while recording → result → restore` through the bridge |
| Engine integration test | Bridge receives real engine events; no transcript synthesised by the UI |
| Regression | All existing suites still pass (`tests_speech_transform`, `tests_translit`, `tests_model_progress`, `tests_single_instance`, `tests_profiles`, `tests_autostart`, `tests_streaming`) |

### Success criteria
- [ ] The design-template UI greys out / boots and the disc state changes on
      `startPushToTalk`.
- [ ] While holding PTT the HUD shows `partial` (streaming) text and a live
      signal arc + mic level.
- [ ] Releasing PTT shows the `result` (final, cleaned, with language + confidence + edits).
- [ ] Changing settings in the UI changes engine behaviour (model/device,
      language, cleanup, translate, developer, vad).
- [ ] Undo returns raw transcript; footer numerals update.
- [ ] `npm run build` (production) for the UI succeeds.

---

## 10. Build & release

- **UI build:** `cd web && npm run build` → static files.
- **Embedding:** PyInstaller spec copied to include the built UI as static
  files; the app ships a local page served by the UI process at
  `127.0.0.1:<ui_port>` (or a separate `flowmini_ui` launcher), so the user
  gets a real desktop interface, not a headless console.
- **Versioning:** bump `APP_VERSION` to `v1.1.0.7`; per-build 4th segment rule
  continues (`v1.1.0.8 … v1.1.0.12`, then `v1.1.1.01`).

---

## 11. Risks & open questions

- **Scaffold coexistence.** Old `web/` is a placeholder; the plan replaces it.
  Confirm the user is OK with dropping it rather than merging.
- **Firewall.** A `127.0.0.1` loopback WebSocket rarely triggers Windows
  Defender SmartScreen; LAN exposure only on explicit opt-in.
- **Fonts.** `fontsource` packages are self-hosted (no network needed after
  install) — offline-first is preserved.
- **Streaming latency.** The engine's `partial` emission cadence must stay
  sub-second (Day 7 target: ~350 ms for `tiny`). The UI must not "catch up"
  on the final result.

---

## 12. Immediate next actions

1. Copy `design-template/` into `web/` (replace the placeholder scaffold).
2. Implement the WebSocket bridge + in-process test bridge.
3. Implement adapter in `web/src/adapter.ts`; wire `main.tsx`.
4. Add §7 items (mic level streaming, model/device picker, mic selection,
   undo, telemetry footer, self-test, PWA option).
5. Write bridge + mock UI tests; run the full suite.
6. Bump to `v1.1.0.7`; build the UI; package.
