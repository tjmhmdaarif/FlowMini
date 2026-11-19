# Next Session Work Plan — FlowMini

**Date:** 2026-11-20
**Current Version:** v1.1.0.7
**Goal:** Close Day 8 gaps + fix critical architecture issues

---

## 🔴 CRITICAL (Do First — Blockers for v1.1.0.7 Release)

| # | Task | Source | Acceptance Criteria |
|---|------|--------|---------------------|
| 1 | **Engine integration test** — run real `flow_mini` + bridge, verify `test_client.py` receives engine events | Day 8 §7 #3 | `python demo.py` → `python test_client.py` shows real engine events (not mock) |
| 2 | **Mic device enumeration → real engine** — `sounddevice.query_devices()` → bridge → `SettingsSheet` dropdown | Day 8 §7 #4 + Analysis #8 | Dropdown shows real input devices; selection persists in config |
| 3 | **Implement `undo()` in bridge** — `BridgeRouter.undo()` → `engine.paste_into_active_app(_last_raw)` | Day 8 §7 #5 + Analysis #9 | Undo button in UI restores raw transcript |
| 4 | **PyInstaller packaging with UI embed** — `python build.py` produces working `dist/FlowMini/FlowMini.exe` | Day 8 §7 #6 + Analysis #6 | EXE runs standalone; React UI loads from `sys._MEIPASS/web/dist` |
| 5 | **Release tag + changelog** — `git tag v1.1.0.7` + `CHANGELOG.md` entry | Day 8 §7 #7 | Tag pushed; CHANGELOG.md documents v1.1.0.7 changes |

---

## 🟡 HIGH PRIORITY (Architecture Fixes)

| # | Task | Source | Acceptance Criteria |
|---|------|--------|---------------------|
| 6 | **Unify config loader** — single `load_config()` in `flowmini_core/config.py`; update all entry points | Analysis #5, #10 | One source of truth; `flow_mini.py`, `core/app_core.py`, `snippets.py` all import it |
| 7 | **Consolidate PyInstaller spec** — remove inline spec from `build.py`; use `FlowMini.spec` only | Analysis #6 | `build.py` calls `pyinstaller FlowMini.spec`; no duplicate spec generation |
| 8 | **Add React frontend CI** — `.github/workflows/frontend.yml` (lint, typecheck, build) | Analysis #7 | PR checks run on `web/` changes |
| 9 | **Structured logging** — replace `print()` with `logging` + JSON formatter across codebase | Analysis #22 | All logs have `level`, `timestamp`, `component`, `event` |

---

## 🟢 MEDIUM PRIORITY (Reliability)

| # | Task | Source | Acceptance Criteria |
|---|------|--------|---------------------|
| 10 | Thread-safe audio buffer — `queue.Queue(maxsize=100)` with backpressure | Analysis #12 | No unbounded memory growth in streaming worker |
| 11 | Atomic state flags — `threading.Event` for `recording`/`vad_mode` | Analysis #11 | No race conditions on boolean state |
| 12 | Model download timeout + retry — 300s timeout, 3 retries with backoff | Analysis #2.2 | No indefinite hangs on first run |
| 13 | Clipboard paste retry — exponential backoff (100ms→500ms→1s) | Analysis #2.3 | Transient failures recovered |
| 14 | Bridge error handling — await `run_coroutine_threadsafe`, log failures | Analysis #13 | No silent event drops |

---

## 📋 QUICK START CHECKLIST (Next Session)

```bash
# 1. Clone/verify repo
cd FlowMini-repo

# 2. Verify current state
grep APP_VERSION flowmini_app.py          # should show v1.1.0.7
cat config.json | jq .                    # should be clean (no duplicates)

# 3. Start with CRITICAL #1
python demo.py                            # bridge on :8765
# In another terminal:
python test_client.py 8765 30             # should show REAL engine events

# 4. If mock only → fix engine integration (CRITICAL #1)
# 5. Then mic enumeration (CRITICAL #2)
# 6. Then undo (CRITICAL #3)
# 7. Then build test (CRITICAL #4)
# 8. Then tag release (CRITICAL #5)
```

---

## 🎯 DEFINITION OF DONE FOR THIS SESSION

- [ ] All 5 CRITICAL items complete
- [ ] At least 2 HIGH PRIORITY items started
- [ ] `python build.py` succeeds end-to-end
- [ ] `git tag v1.1.0.7` pushed
- [ ] `CHANGELOG.md` created with v1.1.0.7 entry

---

## 📝 NOTES

- **Day 8 Build Plan items 1 & 2** appear as ✅ in one table but ❌ in another — verify actual state:
  - `config.json` has `ui_host`/`ui_port` ✅
  - `flowmini_app.py` has `APP_VERSION = "1.1.0.7"` ✅
- **PWA/headless packaging** (Day 8 §7 #7) — defer to post-v1.1.0.7
- **Open questions** (Day 8 §9) — decide during implementation:
  - Config location: project root (current) vs AppData
  - `mic_device` callback: full enum vs placeholder
  - `undo()`: engine call vs UI-side restore

---

## 🔗 RELATED FILES

- `plans/completed/DAY8_BUILD_PLAN.md` — source of Day 8 gaps
- `plans/completed/DAY8_PLAN.md` — full Day 8 architecture
- `deepseek_harness.md` — DSH integration guide
- `build.py` — fixed to use `web/` not `frontend/`
- `config.json` — deduplicated