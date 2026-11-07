#!/usr/bin/env python
"""FlowMini PyInstaller Build Script.

Builds a single-file offline executable that bundles:
  - The Python backend (AppCoreManager + BridgeAPI)
  - The React frontend (Vite-built static files)
  - Whisper model files and dependencies
  - All native binaries (sounddevice, etc.)

Run: python build.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    # When running from PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS)
else:
    # Development mode — project root
    BASE_DIR = Path(__file__).parent.parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"
WEB_DIR = BASE_DIR / "web"  # existing web/ dir (old UI)
DIST_DIR = FRONTEND_DIR / "dist"
BUILD_DIR = FRONTEND_DIR / "build"
SPEC_FILE = Path(__file__).parent / "flowmini.spec"


# ---------------------------------------------------------------------------
# Step 1: Build the React Frontend (Vite)
# ---------------------------------------------------------------------------

def build_frontend():
    """Run npm run build inside the frontend directory."""
    print("[Build] Step 1: Building React frontend with Vite...")
    frontend_dir = FRONTEND_DIR
    if not frontend_dir.exists():
        print(f"[Error] Frontend directory not found: {frontend_dir}")
        return False

    # Change to frontend dir and run build
    original_dir = os.getcwd()
    try:
        os.chdir(frontend_dir)
        result = subprocess.run(
            ["npm", "run", "build"],
            capture_output=True,
            text=True,
            timeout=120,  # 2 min timeout
        )
        if result.returncode != 0:
            print(f"[Error] npm build failed:")
            print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
            return False
        print("[Build] Frontend built successfully.")
        return True
    except subprocess.TimeoutExpired:
        print("[Error] npm build timed out after 120 seconds.")
        return False
    finally:
        os.chdir(original_dir)


# ---------------------------------------------------------------------------
# Step 2: Prepare PyInstaller Spec
# ---------------------------------------------------------------------------

def prepare_spec():
    """Create or update the PyInstaller .spec file to bundle the frontend."""
    print("[Build] Step 2: Preparing PyInstaller spec...")

    # Ensure dist exists and has content
    if not DIST_DIR.exists():
        print(f"[Error] Frontend dist not found: {DIST_DIR}")
        return False

    # Check what's in dist
    dist_items = list(DIST_DIR.iterdir())
    print(f"[Build] Frontend dist contains {len(dist_items)} items")

    # Create a custom .spec file that bundles the frontend dist
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cimport = True

import PyInstaller.candidates.raw
import PyInstaller.runner.cui

a = Analysis(
    ['app.py'],
    pathex=[{BASE_DIR!r}],
    binaries=[],
    datas=[
        # Bundle the entire frontend dist directory
        ('{DIST_DIR}', '{DIST_DIR}'),
        # Include config.json if it exists alongside app.py
        ('{CONFIG_PATH if False else ""}', '{CONFIG_PATH}' if CONFIG_PATH.exists() else ""),
    ],
    hiddenimports=[
        'faster_whisper',
        'sounddevice',
        'numpy',
        'pyperclip',
        'pyautogui',
        'pynput',
        'pystray',
        'PIL',
        'keyboard',
        'asyncio',
        'json',
        'threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    win_no_cache=True,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlowMini",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,  # Windowed (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FlowMini",
    # Bundle frontend dist into the executable
    {DIST_DIR}: f'./{DIST_DIR.name}',
    here={BASE_DIR!r},
)
'''

    spec_path = SPEC_FILE
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(spec_content)

    print(f"[Build] PyInstaller spec written to {spec_path}")
    return True


# ---------------------------------------------------------------------------
# Step 3: Build the Executable
# ---------------------------------------------------------------------------

def build_executable():
    """Run PyInstaller to build the single-file executable."""
    print("[Build] Step 3: Building PyInstaller executable...")

    if not SPEC_FILE.exists():
        print(f"[Error] Spec file not found: {SPEC_FILE}")
        return False

    try:
        result = subprocess.run(
            ["pyinstaller", str(SPEC_FILE), "--noconfirm"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )
        if result.returncode != 0:
            print(f"[Error] PyInstaller failed:")
            print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
            print(result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr)
            return False
        print("[Build] PyInstaller build completed successfully.")
        return True
    except subprocess.TimeoutExpired:
        print("[Error] PyInstaller timed out after 300 seconds.")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("FlowMini PyInstaller Build Script")
    print("=" * 60)

    steps = [
        ("Build React Frontend", build_frontend),
        ("Prepare PyInstaller Spec", prepare_spec),
        ("Build Executable", build_executable),
    ]

    for step_name, step_func in steps:
        print(f"\n{step_name}...")
        success = step_func()
        if not success:
            print(f"[FAILED] {step_name} — stopping build pipeline.")
            sys.exit(1)
        print(f"[OK] {step_name} completed.")

    print("\n" + "=" * 60)
    print("Build complete!")
    print(f"Executable location: dist/FlowMini.exe (or dist/FlowMini in directory mode)")
    print("=" * 60)


if __name__ == "__main__":
    main()