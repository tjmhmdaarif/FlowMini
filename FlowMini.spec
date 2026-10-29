# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FlowMini.

Build from the repo root inside your virtualenv:

    .venv\Scripts\pyinstaller.exe FlowMini.spec --noconfirm

Produces dist\\FlowMini\\ (onedir build):
    dist\\FlowMini\\FlowMini.exe  + _internal\\ (libs, faster_whisper assets)

One-dir instead of one-file on purpose: the onefile bootloader spawns a
child process that hung forever whenever a second copy was launched
while the first was still running (and startup cost is ~15 s of temp
extraction on every launch in one-file mode). One-dir starts instantly.
"""
import os

from PyInstaller.utils.hooks import collect_all

# faster_whisper needs its tokenizer/asset files at runtime.
try:
    import faster_whisper

    _fw_assets = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
    datas = [(_fw_assets, "faster_whisper/assets")] if os.path.isdir(_fw_assets) else []
except ImportError:  # pragma: no cover - build env without ASR deps
    datas = []

binaries = []
hiddenimports = []

# Lazy imports PyInstaller's static analysis cannot see.
hiddenimports += ["faster_whisper", "pynput", "pynput.keyboard"]

tmp_ret = collect_all("unidecode")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ["flowmini_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["flowmini.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FlowMini",
)

