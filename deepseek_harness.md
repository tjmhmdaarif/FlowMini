# FlowMini — DeepSeek Harness (DSH) Setup Guide

This document describes how to run FlowMini on the DeepSeek Harness (DSH) with the Everything Codex (ECC) skill ecosystem.

## Prerequisites

- DeepSeek Harness installed and running
- Python 3.10+ with dependencies from `requirements.txt`
- Node.js 18+ for React frontend (`web/`)

## Quick Start

### 1. Install Python Dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Build React Frontend (for pywebview)

```bash
cd web
npm install
npm run build
cd ..
```

### 3. Run FlowMini

**Option A: Tkinter GUI (original)**
```bash
python flowmini_app.py
```

**Option B: pywebview + React UI (Day 8+)**
```bash
python app.py
```

**Option C: CLI mode**
```bash
python flow_mini.py --test
```

## DSH Integration

### Skills Installation

FlowMini uses the following ECC skills (installed in `~/.dsh/skills/`):

| Skill | Purpose |
|-------|---------|
| `ponytail` | Lazy senior dev mode - minimal, correct code |
| `github-ops` | GitHub repository operations |
| `deepseek-harness-setup` | ECC on DSH configuration |
| `search-first` | Research before coding workflow |
| `find-skills` | Discover installable skills |

Install a skill:
```bash
ln -s /path/to/ECC/skills/<skill-name> ~/.dsh/skills/<skill-name>
```

### Hooks Configuration

Generate DSH-format hooks from ECC:
```bash
node scripts/dsh/generate-hooks-config.js --ecc-root /path/to/ECC --out ~/.dsh/ecc/hooks-dsh.json
```

Mount in `~/.dsh/profiles/<profile>/cordis.patch.yml`:
```yaml
- insert:
    - id: ecc-hooks-Codex
      name: "@deepseek-ai/dsh-hooks-Codex"
      config:
        configPath: /absolute/path/to/hooks-dsh.json
```

### Validation

```bash
cd ~/.dsh && dsh --profile web --dump-config > /tmp/dump.yml
grep ecc-hooks /tmp/dump.yml
```

## Project Structure

```
FlowMini/
├── flow_mini.py           # Core engine: audio → ASR → cleanup → paste
├── flowmini_app.py        # Tkinter GUI: control panel, tray, hotkeys
├── app.py                 # pywebview launcher + BridgeAPI
├── core/
│   ├── app_core.py        # Decoupled Python logic (AppCoreManager)
│   ├── bridge_api.py      # pywebview js_api bridge
│   └── websocket_bridge.py # WebSocket bridge for React UI
├── speech_transform.py    # Deterministic post-ASR cleanup engine
├── translit.py            # Offline romanization (13+ languages)
├── auto_learn.py          # Learns from user corrections
├── autostart.py           # Windows HKCU Run-key management
├── snippets.py            # Voice snippets system
├── build.py               # PyInstaller build script (fixed: uses web/)
├── FlowMini.spec          # PyInstaller spec (bundles web/dist)
├── config.json            # User settings (deduplicated)
├── web/                   # React 19 + Tailwind v4 + Motion UI
│   ├── src/
│   │   ├── App.tsx        # Main app (Aperture, TranscriptStage, etc.)
│   │   ├── engine.ts      # UI state store
│   │   ├── adapter.ts     # FlowMiniAdapter (6-method seam)
│   │   └── components/    # Aperture, TranscriptStage, EventStream, SettingsSheet
│   └── package.json
└── tests/                 # 7 test suites (all passing)
```

## Configuration

### config.json (deduplicated)

```json
{
  "trigger_key": "ctrl+alt+d",
  "vad_trigger_key": "ctrl+alt+f",
  "polish_model": "google/gemini-2.5-flash",
  "cleanup_mode": "medium",
  "stt_model": "large-v3-turbo",
  "ui_host": "127.0.0.1",
  "ui_port": 8765,
  "vad_enabled": false,
  "mic_device": ""
}
```

### Environment Variables

Create `.env` from `.env.example`:
```bash
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx
```

Required only for `cleanup_mode: "medium"` (AI polish).

## Build & Release

### PyInstaller Build

```bash
python build.py
```

Produces `dist/FlowMini/FlowMini.exe` (one-dir mode for instant startup).

### Version Numbering

| Build | Version | Notes |
|-------|---------|-------|
| Day 3 | v1.1.0.2 | UI refresh |
| Day 4 | v1.1.0.3 | Auto-start + tray menu |
| Day 5 | v1.1.0.4 | CI auto-build |
| Day 6 | v1.1.0.5 | Winget manifest |
| Day 7 | v1.1.0.6 | Streaming partials |
| Day 8 | v1.1.0.7 | React UI + WebSocket bridge |

Current: `APP_VERSION = "1.1.0.7"` in `flowmini_app.py`

### CI Pipeline

GitHub Actions (`.github/workflows/build.yml`) builds EXE on tag push:
```bash
git tag v1.1.0.8
git push origin v1.1.0.8
```

### Winget

```bash
winget install FlowMini
```

## Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Alt+D` | Push-to-talk dictation |
| `Ctrl+Alt+F` | Hands-free VAD mode |

Change in `config.json` (`trigger_key`, `vad_trigger_key`).

## Testing

```bash
# All test suites
python tests_speech_transform.py     # 47 tests
python tests_translit.py             # 20 tests
python tests_model_progress.py       # 18 tests
python tests_single_instance.py      # 7 tests
python tests_profiles.py             # 58 tests
python tests_autostart.py            # 25 tests
python tests_streaming.py            # 3 tests
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Hotkeys not working | Try different combo in `config.json`; check Windows hotkey policy |
| No audio input | Enable microphone in Windows Sound settings |
| HUD not showing | Ensure `show_hud = true` in `config.json` |
| Model download slow | First run only (~1.5 GB); subsequent runs instant |
| Build fails | Ensure `web/dist` exists (`cd web && npm run build`) |

## DSH Profile Notes

- **CLI/Web profile**: Validated setup target
- **Desktop profile**: Separate runtime; skill discovery must be verified independently
- **Hooks**: 23 command hooks on 5 of 7 bridge events
- **Slash commands**: Not available (Codex mechanism); workflows covered by skills
- **Agents**: Native dispatch unverified; use canonical prompt guidance only after review

## Updating

```bash
# Pull latest skills
git -C ~/.dsh/skills/ponytail pull
git -C ~/.dsh/skills/github-ops pull

# Regenerate hooks config if ECC checkout moved
node scripts/dsh/generate-hooks-config.js --ecc-root /path/to/ECC --out ~/.dsh/ecc/hooks-dsh.json
```

## References

- [FlowMini GitHub](https://github.com/tjmhmdaarif/FlowMini)
- [DeepSeek Harness](https://github.com/deepseek-ai/dsh)
- [Everything Codex (ECC)](https://github.com/everything-codex/ecc)
- [Ponytail Skill](https://github.com/DietrichGebert/ponytail)