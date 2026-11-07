# FlowMini — Day 8 Complete Build Plan

**Date:** 2026-11-07
**Objective:** Replace the placeholder React control panel with the editorial
"instrument" UI and wire it to the Python engine through a real-time local
WebSocket bridge — no online hosting, everything runs natively.

---

## 1. Context
- Days 1–7 already complete (Day 7 = true real-time streaming, `v1.1.0.6`).
- `web/` was originally a *visual + interaction demo placeholder* — it did **not**
  call `flow_mini.py`.
- Redesign spec: `design-template/` (extracted from `design-template.zip`), an
  adapter-seam UI with no engine/mic/transcript of its own.

---

## 2. Goal
1. Adopt `design-template/` as the FlowMini frontend (today: `web/`).
2. Wire engine ↔ UI via a local WebSocket bridge (engine is the single source of
   truth for audio/ASR/partial/transcript — the UI never synthesises them).
3. Add the new capabilities the template leaves open (mic level, model/device
   picker, mic enumeration, undo, telemetry footer, self-test, PWA).

## 3. Deliverables — completed (this session)

| # | Deliverable | Path | Verify |
|---|---|---|---|
| 1 | Adopt `design-template` as UI | `web/` | ✅ `cd web && npm run build` → exit 0, `dist/` (374 kB) |
| 2 | Bridge module (engine → UI) | `core/websocket_bridge.py` | ✅ bridge emits `connected/status/level/partial/result` to clients |
| 3 | Config for the bridge | `config.json` (ui address/port) | ❌ **STILL MISSING** |
| 4 | New faceted UI ideas | `web/src/`, `core/websocket_bridge.py` | ✅ markup + mock verified |
| 5 | `web/README.md` updated | `web/README.md` | ✅ updated to Day 8 spec |
| 6 | Version bump | `flowmini_app.py` → `v1.1.0.7` | ❌ **STILL MISSING** |

## 4. Files updated (by the agents)

- `core/websocket_bridge.py` — `FlowMiniBridge`, `BridgeRouter`, `TestBridge`.
- `flowmini_app.py` — bridge wired into the desktop app init.
- `requirements.txt` — added `websockets>=15.0`.
- `web/` — redesigned instrument UI (React 19 + Tailwind v4 + motion + custom fonts).
  - `web/src/adapter.ts` (the six-method seam + `createSocketAdapter`/`createPreviewAdapter`)
  - `web/src/engine.ts` (UI state store)
  - `web/src/App.tsx` (masthead + 4 stages)
  - `web/src/components/Aperture.tsx`, `TranscriptStage.tsx`, `EventStream.tsx`,
    `SettingsSheet.tsx` (model/device/mic selects)
  - `web/src/main.tsx` (adapter boot), `web/src/index.css` (tokens/atmosphere)
  - `web/src/vite-env.d.ts`, `web/tsconfig*.json`, `web/vite.config.ts`
- `demo.py` — demo harness (mock engine + bridge + HTTP server + PTT simulator).
- `test_client.py` — WebSocket client for verifying bridge emission.
- `kill_port.py` — port-liveness helper.
- `old-web-scaffold/` — backup of the original placeholder.
- `DAY8_PLAN.md`, `doc_modules_updated.md`.

## 5. Features implemented (§7 additions)

| # | Feature | UI / engine change | Verify |
|---|---|---|---|
| 1 | Real-time mic level | Engine emits `level` (0–1); `Aperture` lens + HUD signal arc + status bar | ✅ mock engine + bridge emit `level` |
| 2 | Model / device picker | `SettingsSheet` adds StylePreset, STT model/device, mic device | ✅ type + UI fields |
| 3 | Mic device enumeration | `engine.ts` `MICS` list placeholder; bridge exposes via settings | ✅ placeholder wired |
| 4 | Undo / raw recall | `SettingsSheet` Undo button → `undo()` command | ✅ command mapped |
| 5 | Session telemetry footer | Footer numerals (sessions/words/latency/conf) | ✅ footer wired |
| 6 | Self-test panel | `selfTest()` in adapter; results in `EventStream` | ✅ command mapped |
| 7 | PWA / headless packaging | `vite build` + PyInstaller embed (pending) | ❌ not yet built |

## 6. Live verification (this session)

- `cd web && npm run build` → **exit 0**, `dist/` built (374 kB, 437 modules).
- `python demo.py` → bridge on `127.0.0.1:8765`, UI server on `8123`.
- `test_client.py` → **31 events** received: `connected`, `status`, `level`,
  `partial`, `result` (no UI-side transcript synthesis — engine is source of truth).
- Both ports LISTENING (8765 bridge / 8123 UI); built `index.html` served from
  `web/dist/` (`/assets/index-*.js`).

## 7. Still missing (left to the team)

| # | Item | Status | How to verify |
|---|---|---|---|
| 1 | `config.json` bridge config + parser | ❌ missing | read `config.json`; bridge honours `ui_address`/`ui_port` |
| 2 | Version bump `v1.1.0.7` in `flowmini_app.py` | ❌ missing | `grep APP_VERSION` → `v1.1.0.7` |
| 3 | Engine integration test (real `flow_mini` engine, not mock) | ❌ missing | run real engine + bridge; `test_client` receives engine events |
| 4 | Mic device enumeration → real engine | ❌ placeholder | list input devices; bridge exposes `mic_device` setting |
| 5 | `undo()` / raw recall wired to real engine | ❌ mock only | real engine supports `undo` |
| 6 | PyInstaller packaging to embed UI | ❌ not started | build `flowmini_ui` + test desktop run |
| 7 | `v1.1.0.7` release tag / changelog | ❌ missing | `git tag v1.1.0.7` + CHANGELOG entry |

## 8. Quick re-run checklist (for the next agents)

```bash
cd /c/Users/muham/flowmini-project

# 1) rebuild UI (should be clean)
cd web && npm run build   # exit 0

# 2) run the live demo harness
python demo.py   # bridge on 127.0.0.1:8765, UI on 127.0.0.1:8123

# 3) verify event emission from the bridge
python test_client.py 127.0.0.1:8765 20   # expect connected/status/level/partial/result

# 4) confirm the built UI is what the server serves
curl -s http://127.0.0.1:8123/ | head -5
```

## 9. Open questions (left for the team)

- Should `config.json` live next to `flowmini_app.py` or in the user's AppData
  profile? (Default: project root, overridden by `FLOWMINI_CONFIG` env var.)
- Does `mic_device` need a full enumeration callback, or is the placeholder
  acceptable for `v1.1.0.7`?
- Should `undo()` be a real engine call or UI-side raw restore? (Plan chose UI-side.)

---

**Everything above is the complete Day 8 build plan.** The build is done
natively; the only open items are the 7 listed in §7 (plus any small items the
team finds by re-reading the diff).
