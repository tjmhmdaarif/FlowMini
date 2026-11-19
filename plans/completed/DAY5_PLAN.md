# FlowMini — Day 5 Build Plan

## 📋 Current Status (Day 4 Complete)

From the repo (https://github.com/tjmhmdaarif/FlowMini):
- ✅ **Day 1:** Floating HUD (status, mic level, text near cursor)
- ✅ **Day 2:** First-run model download progress (live % + MB, resume-safe)
- ✅ **Day 3:** Per-app profiles (code mode in editors, formal style in mail)
- ✅ **Day 4:** Auto-start with Windows (HKCU Run key with self-heal) + tray quick-menu
- [ ] **Day 5:** CI — EXE builds automatically on every tag (THIS IS TODAY)
- [x] **Day 6:** winget manifest (winget install FlowMini) ✅
- [ ] **Day 7:** Streaming partial transcript

---

## 🎯 Day 5 Objective: CI Pipeline (Auto-Build EXE)

**From README Roadmap:**
> `[ ] Day 5 — CI: the EXE builds automatically on every tag`

**Current version:** v1.1.0.3 (Day 4 complete, next: v1.1.0.4)

---

## 🛠️ What Needs to Be Done

### 1. Add `.github/workflows/` directory
- `build.yml` — Auto-build EXE on tag push / release
- Should trigger on: `tags: ['v*']` and `release: published`

### 2. The workflow should:
- Checkout code
- Set up Python 3.10+
- Install requirements
- Install PyInstaller
- Build `.\_internal\` folder structure (already in spec)
- Package as `.zip` (like current `FlowMini-win64.zip`)
- Attach to GitHub Release
- Auto-increment version in `APP_VERSION`

### 3. Update version tracking
- `APP_VERSION` in `flowmini_app.py` is single source of truth
- After Day 5 build: version becomes v1.1.0.4

---

## 📂 Key Source Files to Modify

| File | Purpose | Action Needed |
|------|---------|---------------|
| `flowmini_app.py` | Main GUI, APP_VERSION | Update version to v1.1.0.4 |
| `.github/workflows/build.yml` | CI pipeline (NEW) | Create workflow |
| `README.md` | Documentation | Update roadmap (Day 5 check, version table) |

---

## 🔧 Technical Details

**Build command (from README):**
```powershell
pip install pyinstaller
.venv\Scripts\pyinstaller.exe FlowMini.spec --noconfirm
```

**Output:** `dist\FlowMini\FlowMini.exe` + `_internal\` folder
**Package:** `FlowMini-win64.zip` (current distribution format)

**Release versioning scheme:**
- Every packaged build gets a new 4th segment
- v1.1.0.3 (Day 4) → v1.1.0.4 (Day 5) → ... → v1.1.0.12 → v1.1.1.01

---

## ✅ Verification After Build

- [ ] GitHub releases page has new `.zip` asset
- [ ] `FlowMini.exe` runs (test locally if possible)
- [ ] `README.md` updated with new version in table
- [ ] `APP_VERSION` in `flowmini_app.py` updated to v1.1.0.4
- [ ] `tests_autostart.py` passes (25 checks)

---

## 🔄 Continue From Here Tomorrow

```bash
# Clone if fresh
cd flowmini-project
git pull origin main

# Open the main app file to check current version
grep -i "APP_VERSION" flowmini_app.py

# Check CI status
ls -la .github/workflows/
```

---

**Status:** Ready to implement. The repo has everything needed — just needs `.github/workflows/` created and the version bumped.
