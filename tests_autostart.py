# -*- coding: utf-8 -*-
"""Tests for Day 4 auto-start (HKCU Run key) — no GUI, no microphone, no network.

Script-style: run with `python tests_autostart.py`.
Windows-only like the rest of FlowMini. Every call drills a TEMPORARY
HKCU subkey (Software\\FlowMini_Test_Autostart_<pid>), which is removed
again — the real Windows logon entry is never touched by these tests.
"""

import os
import sys

import autostart

PASS, FAIL = 0, 0

TEST_SUBKEY = rf"Software\FlowMini_Test_Autostart_{os.getpid()}"

FAKE_APP = r"C:\tmp_dir\flowmini_app.py"
FAKE_PY = r"C:\tmp_dir\python.exe"
FAKE_PYW = r"C:\tmp_dir\pythonw.exe"


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def cleanup():
    """Remove the scratch key even when assertions fail mid-suite."""
    import winreg
    if autostart.winreg is None or sys.platform != "win32":
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_SUBKEY, 0,
                            winreg.KEY_ALL_ACCESS) as key:
            try:
                winreg.DeleteValue(key, "FlowMini")
            except OSError:
                pass
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_SUBKEY)
    except OSError:
        pass


def _value_type_is_sz():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_SUBKEY, 0,
                            winreg.KEY_QUERY_VALUE) as key:
            _, t = winreg.QueryValueEx(key, "FlowMini")
            return t == winreg.REG_SZ
    except OSError:
        return False


def main():
    if autostart.winreg is None or sys.platform != "win32":
        print("autostart needs Windows winreg — suite is Windows-only, skipping")
        return 1
    import winreg
    check("winreg import real", winreg is not None and autostart.winreg is winreg)

    # T1: frozen builds launch the exe itself, fully quoted, no trailing args
    cmd = autostart.build_launch_command(frozen=True, python_exe=r"C:\App\FlowMini.exe")
    check("frozen command quotes the exe",
          cmd == '"' + r"C:\App\FlowMini.exe" + '"')

    # T2: source runs prefer pythonw.exe (no console window at logon)
    real_exists = os.path.exists
    try:
        os.path.exists = lambda _p: True                      # noqa: F811
        cmd = autostart.build_launch_command(frozen=False, python_exe=FAKE_PY,
                                             app_path=FAKE_APP)
        check("source command uses pythonw + quoted app path",
              cmd == '"' + FAKE_PYW + '" "' + FAKE_APP + '"')
    finally:
        os.path.exists = real_exists

    # T3: missing pythonw.exe falls back to the given interpreter untouched
    real_exists = os.path.exists
    try:
        os.path.exists = lambda _p: False                     # noqa: F811
        cmd = autostart.build_launch_command(frozen=False, python_exe=FAKE_PY,
                                             app_path=FAKE_APP)
        check("missing pythonw falls back to python.exe",
              cmd == '"' + FAKE_PY + '" "' + FAKE_APP + '"')
    finally:
        os.path.exists = real_exists

    # T4: frozen detection default comes from sys.frozen (unset here)
    check("is_frozen() reflects sys.frozen", autostart.is_frozen() is False)

    # T5: fresh scratch key -> no entry, not enabled
    check("fresh key has no entry",
          autostart.read_run_entry(subkey=TEST_SUBKEY) is None)
    check("fresh key is not enabled", not autostart.is_enabled(subkey=TEST_SUBKEY))

    # T6: enabling writes the built command verbatim as REG_SZ
    want_cmd = autostart.build_launch_command(frozen=False, python_exe=FAKE_PY,
                                              app_path=FAKE_APP)
    ok = autostart.set_run_entry(True, subkey=TEST_SUBKEY, command=want_cmd)
    check("set_run_entry(True) succeeds", ok)
    check("entry stores the exact command",
          autostart.read_run_entry(subkey=TEST_SUBKEY) == want_cmd)
    check("value type is REG_SZ", _value_type_is_sz())

    # T7: enabling is idempotent — second write keeps a readable entry
    ok = autostart.set_run_entry(True, subkey=TEST_SUBKEY, command=want_cmd)
    check("re-enable succeeds", ok)
    check("entry still readable", autostart.read_run_entry(subkey=TEST_SUBKEY) == want_cmd)

    # T8: sync in agreement is a quiet no-op ("on")
    res = autostart.sync_on_startup(True, subkey=TEST_SUBKEY, command=want_cmd)
    check("sync with matching entry reports on", res == "on")

    # T9: sync heals a stale path (moved exe / edited value):
    # store an outdated command first, then sync towards the real one.
    stale_cmd = '"' + r"C:\Old\Place\FlowMini.exe" + '"'
    autostart.set_run_entry(True, subkey=TEST_SUBKEY, command=stale_cmd)
    res = autostart.sync_on_startup(True, subkey=TEST_SUBKEY, command=want_cmd)
    check("sync heals a mismatched entry", res == "healed")
    check("healed entry now carries the current command",
          autostart.read_run_entry(subkey=TEST_SUBKEY) == want_cmd)

    # T10: sync re-creates a deleted entry when the choice is ON
    autostart.set_run_entry(False, subkey=TEST_SUBKEY)
    check("manual delete works", autostart.read_run_entry(subkey=TEST_SUBKEY) is None)
    res = autostart.sync_on_startup(True, subkey=TEST_SUBKEY, command=want_cmd)
    check("sync recreates a missing entry", res == "healed")
    check("recreated entry correct", autostart.read_run_entry(subkey=TEST_SUBKEY) == want_cmd)

    # T11: sync removes the entry when the choice is OFF
    res = autostart.sync_on_startup(False, subkey=TEST_SUBKEY)
    check("sync removes entry for OFF", res == "removed")
    check("removed means absent", autostart.read_run_entry(subkey=TEST_SUBKEY) is None)

    # T12: repeated turn-off is a quiet no-op ("off")
    res = autostart.sync_on_startup(False, subkey=TEST_SUBKEY)
    check("repeated OFF is a no-off 'off'", res == "off")

    # T13: unicode/space paths survive the registry round-trip
    spaced = r"C:\Muhammads Folder\FlowMini.exe"
    wanted = '"' + spaced + '"'
    ok = autostart.set_run_entry(True, subkey=TEST_SUBKEY, command=wanted)
    check("spaced path stores ok", ok)
    check("spaced path reads back verbatim",
          autostart.read_run_entry(subkey=TEST_SUBKEY) == wanted)

    # T14: disabling an absent entry still reports success (idempotent delete)
    autostart.set_run_entry(False, subkey=TEST_SUBKEY)
    ok = autostart.set_run_entry(False, subkey=TEST_SUBKEY)
    check("disabled-again succeeds", ok)

    cleanup()
    check("scratch key cleaned up",
          autostart.read_run_entry(subkey=TEST_SUBKEY) is None)
    print()
    print(f"==== RESULT: {PASS} passed, {FAIL} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
