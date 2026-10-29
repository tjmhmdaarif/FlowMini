# -*- coding: utf-8 -*-
"""Tests for the single-instance mutex guard (no GUI, no microphone).

Script-style: run with `python tests_single_instance.py`.
Uses unique mutex names so the tests stay valid even while a real
FlowMini instance is running on this machine.
"""

import os
import sys

import flowmini_app

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def main():
    k32 = flowmini_app._kernel32_lib()

    # T1: non-Windows platforms never block the app (no mutex attempted)
    real_platform = sys.platform
    try:
        sys.platform = "linux"
        check("non-win32 returns None", flowmini_app._acquire_single_instance_mutex("FlowMini_Test_T1") is None)
    finally:
        sys.platform = real_platform

    # T2: fresh unique name yields a real OS handle
    tname = f"FlowMini_Test_Mutex_{os.getpid()}"
    h = flowmini_app._acquire_single_instance_mutex(tname)
    check("fresh acquire returns a handle", isinstance(h, int) and h != 0)

    # T3: same name again while the handle is still held -> "exists"
    check("second acquire sees exists", flowmini_app._acquire_single_instance_mutex(tname) == "exists")

    # T4: the real app-mutex name also reports "exists" when held
    # (held here by our own probe; a running FlowMini would hold it too)
    probe = k32.CreateMutexW(None, False, flowmini_app._SINGLE_INSTANCE_MUTEX_NAME)
    check("real-name probe created", bool(probe))
    check("real name reports exists",
          flowmini_app._acquire_single_instance_mutex() == "exists")
    if probe:
        k32.CloseHandle(probe)

    # T5: releasing the holding handle lets the same name be re-acquired
    if isinstance(h, int) and h:
        k32.CloseHandle(h)
        h2 = flowmini_app._acquire_single_instance_mutex(tname)
        check("name re-acquirable after release", isinstance(h2, int) and h2 != 0)
        if isinstance(h2, int) and h2:
            k32.CloseHandle(h2)
    else:
        check("name re-acquirable after release", False)

    print(f"==== RESULT: {PASS} passed, {FAIL} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
