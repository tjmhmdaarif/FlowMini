# FlowMini — Day 8 Updated Module / File Index

This document tells any agent where each Day 8 updated file lives and what it does.
Use it to self-review or to hand off verification tasks.

Repo root: `/c/Users/muham/flowmini-project/`

---

## 1. WebSocket bridge (engine ↔ UI transport)

| Path | What it is | Status |
|---|---|---|
| `core/websocket_bridge.py` | `FlowMiniBridge` + `BridgeRouter` + `TestBridge`. Engine → client events (status/level/partial/result/log/connected/error), client → engine commands (start/stop/setting/selfTest/stats/undo). Thread-safe broadcast. | ✅ Updated |
| `flowmini_app.py` | Main desktop app. Creates `FlowMiniBridge` on a daemon thread; wires engine `on_event`/`on_level` → bridge; reads bridge events for the UI. | ✅ Modified |
| `requirements.txt` | Added `websockets>=15.0`. | ✅ Modified |
| `demo.py` | Demo harness: mock engine + `FlowMiniBridge` on `127.0.0.1:8765`, HTTP server on `8123` serving `web/dist`, push-to-talk simulator. | ✅ New |

---

## 2. React frontend (design template → redesigned instrument UI)

| Path | What it is | Status |
|---|---|---|
| `web/package.json` | Dependencies: `motion`, `@fontsource-variable/outfit`, `@fontsource/ibm-plex-mono`, `@fontsource/instrument-serif`, Tailwind v4 plugin. | ✅ Modified |
| `web/package-lock.json` | Locked dependency tree. | ✅ New |
| `web/vite.config.ts` | Binds `0.0.0.0:3000` (dev); Tailwind Vite plugin enabled. | ✅ Modified |
| `web/tsconfig.app.json`, `tsconfig.json`, `tsconfig.node.json` | TypeScript config. | ✅ Modified |
| `web/src/main.tsx` | Mounts `<App adapter={createWebSocketAdapter()} />`. | ✅ Modified |
| `web/src/vite-env.d.ts` | CSS module declaration fix. | ✅ Modified |
| `web/src/engine.ts` | UI state store (reducer), status meta, languages, extended `Settings`. | ✅ Modified |
| `web/src/adapter.ts` | `FlowMiniAdapter` implementation (`createWebSocketAdapter` + `createPreviewAdapter`). | ✅ Modified |
| `web/src/App.tsx` | Layout: masthead, ruler, 01/02/03/04 stages, footer. | ✅ Modified |
| `web/src/components/Aperture.tsx` | Harmonic lens + trigger. | ✅ New |
| `web/src/components/EventStream.tsx` | Runtime log. | ✅ New |
| `web/src/components/TranscriptStage.tsx` | Editorial serif transcript. | ✅ New |
| `web/src/components/SettingsSheet.tsx` | Hairline controls deck (added model/device/mic selects). | ✅ Modified |
| `web/src/index.css` | Tokens, atmosphere, keyframes. | ✅ Modified |
| `web/src/components/SettingsSheet.tsx` | Updated with model/device/mic selects. | ✅ Modified |

---

## 3. Documentation & plan

| Path | What it is | Status |
|---|---|---|
| `DAY8_PLAN.md` | Full Day 8 plan (architecture, features, testing, versioning). | ✅ New |
| `web/README.md` | Day 8 spec for the redesigned frontend. | ✅ Modified |

---

## 4. Excluded / backup (NOT part of the repo build)

| Path | Why it exists |
|---|---|
| `old-web-scaffold/` | Backup of the original placeholder `web/` before replacement. |
| `kill_port.py` | Dev utility to free a TCP port. |
| `test_client.py` | WebSocket client to verify bridge emission. |

---

## Verify / test quick list

- `cd web && npm run build` → exit 0, `dist/` built (374 kB).
- `python demo.py` → bridge on `127.0.0.1:8765` + UI server on `8123`.
- Test client (`test_client.py`) connects to `ws://127.0.0.1:8765`, receives
  `connected`, `status`, `level`, `partial`, `result` events.
