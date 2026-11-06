# FlowMini — Day 7 Build Plan: Real-Time Streaming Partial Transcript

## 📋 Context & Roadmap

- ✅ **Day 1:** Floating HUD (status, mic level, text near cursor)
- ✅ **Day 2:** First-run model download progress (live % and MB in HUD & window)
- ✅ **Day 3:** Per-app profiles (code mode in editors, formal style in mail)
- ✅ **v1.1.0.2:** UI refresh (crimson design system, responsive layout)
- ✅ **Day 4:** Auto-start with Windows + tray quick-menu
- ✅ **Day 5:** CI auto-build EXE on every tag
- ✅ **Day 6:** Winget manifest (`winget install FlowMini`)
- ✅ **Day 7 (Today):** Streaming partial transcript (words appear while you speak)

---

## 🎯 Day 7 Goal

Transform FlowMini from **batch transcription** (where text only appears after you release the hotkey and stop recording) into **true real-time streaming dictation** (words appear dynamically in the floating HUD and main window **WHILE** you speak).

---

## 🏗️ Architecture: Dual-Model Hybrid Streaming

Real-time streaming speech-to-text requires sub-second latency (< 300ms) on consumer hardware:

1. **Live Streaming Worker (Background Thread):**
   - Runs concurrently while recording is active (`self.recording` or active VAD speech).
   - Uses an ultra-lightweight, local Whisper model (`tiny`, 39MB) with greedy decoding (`beam_size=1`, no VAD delay).
   - Evaluates accumulated utterance audio every ~350ms.
   - Emits `partial_transcript` events with the live text.

2. **Floating HUD & Main UI Updates:**
   - Listens for `partial_transcript` events.
   - Updates the cursor HUD text in real time with high visibility (`TEXT_PRIMARY`).
   - Updates the main application window without jarring typewriter resets.

3. **Final Polish & Injection Pipeline:**
   - Once the user stops recording, the full utterance is processed by the configured model/engine (`large-v3-turbo` / offline Whisper / Google fallback).
   - Deterministic Speech Transform Engine cleans up fillers, symbols, and corrections.
   - Polished text is pasted into the active target application.

4. **Hardware-Resilient CUDA Detection:**
   - Verified that `_pick_device()` checks for required Windows CUDA runtime libraries (`cublas64_12.dll`).
   - Falls back gracefully to optimized INT8 CPU inference if CUDA runtime libraries are absent, preventing runtime inference crashes.

---

## 🧪 Verification & Test Suite

- `tests_streaming.py`:
  - `test_streaming_model_loads_fast`: Verifies local offline model initialization.
  - `test_transcribe_partial_runs_fast`: Verifies partial transcription runs in < 1s.
  - `test_streaming_worker_emits_partial_transcript`: Simulates speech input and verifies real-time `partial_transcript` event generation during recording.
