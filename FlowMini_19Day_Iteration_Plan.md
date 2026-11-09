# FlowMini 19-Day Self-Iteration Plan

## 📅 Project Status (v1.1.0.6)

**Current State:** All 5 Days from PROJECT_SUMMARY.md complete ✅
- Day 1: Floating dictation HUD ✅
- Day 2: First-run model download progress ✅
- Day 3: Per-app profiles ✅
- Day 4: Auto-start with Windows + tray menu ✅
- Day 5: CI: auto-build EXE on tag ✅

**Remaining Roadmap:** Days 6-8 pending 🔄
- Day 6: winget manifest
- Day 7: Streaming partial transcript
- Day 8: Frontend redesign (v1.1.0.2 already complete, but Day 8 tasks continue)

**Total Files Examined:** 131+
**Core Technologies:** Python + Faster-Whisper + Tkinter + pystray + React + Vite + BridgeAPI + PyInstaller + CI/CD

---

## 📋 19-Day Implementation Plan

### Days 1-3: Missing from Original Roadmap

| Day | Task | Status | Deliverable |
|---|---|---|---|
| **1** | **winget manifest** | ⬜ Not Started | `winget/pkgs/tjmhmdaarif.FlowMini/FlowMini.yaml` with proper metadata |
| **2** | **Streaming partial transcript** | ⬜ Not Started | Real-time word output during VAD dictation, `on_partial_transcript` events |
| **3** | **Frontend redesign v2** | ⬜ Not Started | Enhanced glassmorphism, animations, responsive grid, dark/light modes |

### Days 4-6: Quality & Testing

| Day | Task | Priority | Impact |
|---|---|---|
| **4** | **Extend test suite** | High | Add 20+ profile test cases, LLM-polish integration tests |
| **5** | **CI pipeline caching** | Medium | Add action/cache, parallel tests, PR triggers |
| **6** | **Build optimization** | High | Reduce PyInstaller build time, ≤30% faster |

### Days 7-9: Feature Enhancements

| Day | Task | Complexity | New UX Features |
|---|---|---|
| **7** | **Auto-learn improvements** | Medium | Promotion threshold, export/import, stats endpoint |
| **8** | **Voice snippets v2** | High | Variables (`${cursor_pos}`, `${date}`), categories UI |
| **9** | **Multi-mic support** | Medium | Device selection UI, per-profile device memory |

### Days 10-12: Polish & UX

| Day | Task | User Value | Implementation |
|---|---|---|
| **10** | **HUD enhancements** | High | Partial transcript replay, sensitivity level, auto-hide timer |
| **11** | **Hotkey manager** | Medium | UI configurable hotkeys, conflict detection |
| **12** | **Settings export/import** | Medium | JSON backup, merge strategy, QR sharing |

### Days 13-15: Backend & Architecture

| Day | Task | System Impact | Integration Points |
|---|---|---|
| **13** | **BridgeAPI enhancements** | Critical | `get_learn_stats()`, `get_snippets()` new methods |
| **14** | **Per-app profile rule editor** | High | Regex matching UI, preview buttons |
| **15** | **Logging & diagnostics** | Medium | Enhanced database schema, diagnostic tools |

### Days 16-18: Build & Distribution

| Day | Task | Production Ready | Release Impact |
|---|---|---|
| **16** | **Portable mode** | High | `--portable` flag, "Extract and Run" feature |
| **17** | **Changelog generator** | Medium | Git tag → CHANGELOG.md automation |
| **18** | **Backup & restore** | High | Config/database auto-backup |

### Day 19: Release & Wrap-up

| Focus | Expected Outcome |
|---|---|
| **v1.1.1.0 release** | Complete build, GitHub Release, winget manifest update, release notes |

---

## 📊 Success Metrics

### Must-Have ✅ (Current Status)
- [x] FlowMini v1.1.0.6 complete (Days 1-5)
- [x] 47 test checks in speech_transform.py
- [x] CI pipeline working (GitHub Actions)
- [x] PyInstaller builds EXE
- [x] Basic per-app profiles working
- [x] Auto-start with Windows

### Goal ✅ (Remaining Implementation)
- [ ] `winget install --id tjmhmdaarif.FlowMini` works
- [ ] Streaming transcript shows words appearing in real-time
- [ ] All 6 test suites pass (currently ~168 tests)
- [ ] Build time reduced ≤30% vs current
- [ ] EXE size ≤100MB
- [ ] HUD shows partial transcript during VAD dictation
- [ ] Carries forward all existing functionality

---

## 🔧 Daily Development Rhythm

Each day follows this pattern:
1. **Morning:** Read relevant source files, create specific plan for day
2. **Mid-day:** Implement changes + write tests
3. **Evening:** Build EXE, verify functionality, commit changes
4. **End of day:** Update PROJECT_SUMMARY.md, prepare next day's work

### Example for Day 2 (Streaming Transcript):
1. Read `flow_mini.py`, `speech_transform.py`, `bridge_api.py`, `web/src/App.tsx`
2. Implement `on_partial_transcript` callback in WhisperEngine
3. Add streaming display in React EventStream component
4. Test by speaking with VAD mode active
5. Update PROJECT_SUMMARY.md with streaming feature status

---

## 🏗️ Implementation Priority Order

**Critical Path (must work before testing):**
1. winget manifest (needed for Windows Store distribution)
2. Streaming partial transcript (core UX improvement)
3. BridgeAPI enhancements (backend APIs needed for frontend features)

**High Priority (enhancements):**
4. Voice snippets v2 (power-user feature)
5. Multi-mic support (accessibility/performance)
6. Build optimization (developer experience)

**Medium Priority (Polish):**
7. HUD enhancements
8. Settings export/import
9. Per-app profile rule editor

**Release Preparation:**
10. Portable mode
11. Changelog generator
12. Backup & restore

---

## 🔍 What to Implement Today (Current Status)

Since this is Day 2 in the FlowMini iteration, the current focus should be:

**Today:** Begin **streaming partial transcript** implementation
- [ ] Add `on_partial_transcript` callback to WhisperEngine in `flow_mini.py`
- [ ] Emit partial events from `flowmini_app.py`
- [ ] Update BridgeAPI in `bridge_api.py` with new method
- [ ] Implement streaming display in React `web/src/App.tsx`
- [ ] Add visual indicator for streaming words
- [ ] Update tests to verify streaming behavior

**Tomorrow:** Complete streaming implementation, start **auto-learn improvements**

---

## 📁 File Structure for Implementation

```
FlowMini/
├── FlowMini_19Day_Iteration_Plan.md          # This plan document
├── FlowMini_Analysis.md                       # Previous comprehensive analysis
├── PROJECT_SUMMARY.md                         # Daily progress tracking
├── winget/                                       # Will contain Day 1 deliverable
│   └── pkgs/tjmhmdaarif.FlowMini/FlowMini.yaml
├── web/                                          # Day 2-8 frontend work
│   ├── src/                                     # React frontend
│   │   ├── App.tsx                             # Root component
│   │   ├── engine.ts                           # State management
│   │   └── bridgeAdapter.ts                    # BridgeAPI adapter
│   └── src/components/EventStream.tsx          # Streaming display
├── core/                                         # Backend work (Days 13-15)
│   ├── bridge_api.py                            # New BridgeAPI methods
│   └── websocket_bridge.py                      # Enhanced WebSocket support
└── tests/                                        # Enhanced test suites (Days 4-5)
    ├── tests_profiles.py                        # New profile tests
    └── tests_speech_transform.py               # Enhanced integration tests
```

---

## 🔄 GitHub Integration Plan

1. **Branch strategy:** Create feature branches for each 3-day phase
2. **Review process:** PR for each completed phase before starting next
3. **Documentation:** Update `PROJECT_SUMMARY.md` after each day
4. **Testing:** Run all test suites before each build
5. **Release:** Automatic CI/CD on v* tags with full build chain

### Phase 1 (Days 1-3):
- Branch: `feature/19-day-plan-1`
- Focus: Complete remaining original roadmap (winget, streaming, frontend v2)
- PR: Merge after successful integration testing

### Phase 2 (Days 4-6):
- Branch: `feature/19-day-plan-2`
- Focus: Quality improvements, test suite expansion, build optimization
- PR: Merge after CI passes with parallel test execution

### Phase 3 (Days 7-9):
- Branch: `feature/19-day-plan-3`
- Focus: Auto-learn, snippets, multi-mic features
- PR: Merge after feature testing complete

### Phase 4 (Days 10-12):
- Branch: `feature/19-day-plan-4`
- Focus: UX enhancements, settings, hotkey manager
- PR: Merge after user testing phase

### Phase 5 (Days 13-15):
- Branch: `feature/19-day-plan-5`
- Focus: Backend APIs, profile rules, enhanced diagnostics
- PR: Merge after integration testing

### Phase 6 (Days 16-18):
- Branch: `feature/19-day-plan-6`
- Focus: Portable mode, changelog, backup system
- PR: Merge after build testing

### Release (Day 19):
- Merge all feature branches to `main`
- Build EXE with full CI/CD pipeline
- Create GitHub Release v1.1.1.0
- Update winget manifest if required

---

## 📝 Notes & References

- **Current version:** v1.1.0.6 (from `APP_VERSION` in `flowmini_app.py`)
- **Next version:** v1.1.1.0 (19-day iteration plan)
- **Base commit:** All work builds on top of existing v1.1.0.6 code
- **Test coverage:** Currently ~168 tests, target 200+ after this iteration
- **EXE size:** Currently ~80MB, target ≤100MB with optimizations
- **Build time:** Currently ~15 minutes, target ≤10 minutes with caching

This 19-day plan extends the successful v1.1.0.6 release with the remaining original roadmap items (winget, streaming, frontend redesign), quality improvements, and new features while maintaining backward compatibility and following the project's established patterns.