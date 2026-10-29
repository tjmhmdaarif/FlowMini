"""Focus-restore e2e: verify paste lands in the right app even when FlowMini
itself has focus — the exact scenario the user hit ("only ever pastes into
Notepad that was clicked last")."""
import ctypes
import os
import subprocess
import sys
import time

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

import tkinter as tk

import flow_mini as fm

u = ctypes.windll.user32
subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
time.sleep(0.5)


def _find_notepad(timeout=20):
    """Locate a fresh Notepad window: by title first, then by window class."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = (u.FindWindowW(None, "Untitled - Notepad")
                or u.FindWindowW("Notepad", None)
                or u.FindWindowW(None, "Notepad"))
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return 0


def _class_of(hwnd):
    return fm._edit_class_of(hwnd)


# ---------------------------------------------------------------- target app
subprocess.Popen(["notepad.exe"], shell=False)
notepad = _find_notepad()
print(f"Notepad hwnd: {notepad:#x} class: {_class_of(notepad)}")
assert notepad, "notepad not found"
time.sleep(1.5)  # let the editor control settle

# ---------------------------------------------------- real FlowMini core
cfg = fm.load_config()
core = fm.FlowMini(cfg, fm.init_db(), on_event=lambda e, d=None: print(f"EVENT: {e}"))

# ------------------------------------- our own focused window (FlowMini stand-in)
root = tk.Tk()
root.title("Dummy FlowMini")
root.geometry("280x160+40+40")
root.attributes("-topmost", True)
root.update()
root.focus_force()
root.update()
own = u.GetAncestor(root.winfo_id(), 2)
core.own_hwnd = own
core.last_external_hwnd = notepad          # the poller would have found this
ok = fm.force_foreground(own)
time.sleep(0.4)
fg = fm.get_foreground_hwnd()
classes = {_class_of(fg)}
print(f"Foreground: {fg:#x} class={classes} — dummy focused: {ok and fg == own}")

# ------------------------------------------------- T1: stale-target capture fix
t = core._capture_target()
t_class = _class_of(t)
t_pid_c = ctypes.c_ulong()
notepad_pid_c = ctypes.c_ulong()
u.GetWindowThreadProcessId(t, ctypes.byref(t_pid_c))
u.GetWindowThreadProcessId(notepad, ctypes.byref(notepad_pid_c))
print(f"T1 target {t:#x} class={t_class!r} pid_eq={t_pid_c.value == notepad_pid_c.value}")
assert (t_pid_c.value == notepad_pid_c.value) or t_class == "notepad", "capture stale!"

# -------------------------------------- T2: paste while our window has focus
core.paste_into_active_app("Focus-restore test 123")
time.sleep(1.0)

# verify text INSIDE notepad through its focus/caret child if it is Edit-class
tid = u.GetWindowThreadProcessId(t, None)
gti = fm._GUITHREADINFO()
gti.cbSize = ctypes.sizeof(fm._GUITHREADINFO)
u.GetGUIThreadInfo(tid, ctypes.byref(gti))
candidates = [gti.hwndFocus, gti.hwndCaret, t]
buf = ctypes.create_unicode_buffer(256)
got = None
for cand in candidates:
    if not cand:
        continue
    if _class_of(cand) in fm.EDIT_CLASSES:
        u.SendMessageW(cand, 0x000D, 256, ctypes.cast(buf, ctypes.c_void_p))  # WM_GETTEXT
        got = buf.value
        break
print(f"T2 text inside Notepad: {got!r}")
if got is not None:
    print(f"T2 PASSED: {got == 'Focus-restore test 123'}")

# ------------------------------------------------- T3: caret insert WITHOUT focus
ok = fm.force_foreground(own)
time.sleep(0.4)
print(f"T3 stole focus back to dummy: {ok}, foreground now: {fm.get_foreground_hwnd() == own:#x}")
done = fm._insert_text_at_caret(t, " no-focus-insert")
print(f"T3 _insert_text_at_caret ok: {done}")
time.sleep(0.3)
if got is not None:
    u.SendMessageW(candidates[0], 0x000E + 8, 256, ctypes.cast(buf, ctypes.c_void_p))
    print(f"T3 Notepad content: {buf.value!r}")

# ----------------------------------------------------- T4: force_foreground API
ok = fm.force_foreground(notepad)
print(f"T4 force_foreground(notepad) while dummy focused: {ok}")

root.destroy()
subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
print("E2E DONE")
