"""Paste e2e v2: verifies paste lands in the right window without touching
any of the user's apps.

Child = a tiny Tk window (separate PROCESS) with an Entry; it mirrors the
Entry content to a JSON file every 200 ms. Parent = real FlowMini core;
it pastes with (T1) FlowMini's dummy window focused and (T2) the child
focused, then asserts the content file shows both pastes. No Notepad, no
taskkill of anything but our own child PID.
"""
import ctypes
import json
import os
import subprocess
import sys
import time

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

import tkinter as tk

import flow_mini as fm

u = ctypes.windll.user32

MARKER = os.path.join(os.environ["TEMP"], "opencode", "paste_e2e.json")
CHILD_CODE = r"""
import json, os, time, tkinter as tk
MARKER = %r
root = tk.Tk()
root.title("FlowMiniPasteTarget")
root.geometry("320x120+420+260")
var = tk.StringVar()
entry = tk.Entry(root, textvariable=var, width=44, font=("Segoe UI", 12))
entry.pack(padx=10, pady=30)
entry.focus_set()
def flush():
    try:
        with open(MARKER, "w", encoding="utf-8") as fh:
            json.dump({"n_chars": len(var.get()), "text": var.get()}, fh)
    except Exception:
        pass
    root.after(200, flush)
flush()
root.after(90000, root.destroy)
root.mainloop()
""" % MARKER

if os.path.exists(MARKER):
    os.remove(MARKER)

child = subprocess.Popen([sys.executable, "-c", CHILD_CODE])
print(f"child pid: {child.pid}")


def read_content():
    for _ in range(50):
        try:
            with open(MARKER, "r", encoding="utf-8") as fh:
                return json.load(fh).get("text", "")
        except (OSError, json.JSONDecodeError):
            time.sleep(0.2)
    return None


content = read_content()
print(f"initial content: {content!r}")
assert content is not None, "child never reported content"

# find the child window hwnd (belongs to the child process!)
deadline = time.time() + 15
target = 0
while time.time() < deadline and not target:
    fg = u.GetForegroundWindow()
    pid_c = ctypes.c_ulong()
    u.GetWindowThreadProcessId(fg, ctypes.byref(pid_c))
    if pid_c.value == child.pid:
        target = fg
    time.sleep(0.3)
print(f"target hwnd: {target:#x}")
assert target, "child window not found (was it not foreground?)"

# ------------------------------------------------------------- real core
cfg = fm.load_config()
core = fm.FlowMini(cfg, fm.init_db(), on_event=lambda e, d=None: None)
core.last_external_hwnd = target

# dummy FlowMini stand-in window with focus (T1 scenario)
root = tk.Tk()
root.title("Dummy FlowMini")
root.geometry("260x140+40+40")
root.attributes("-topmost", True)
root.update()
root.focus_force()
root.update()
own = u.GetAncestor(root.winfo_id(), 2)
core.own_hwnd = own
ok = fm.force_foreground(own)
time.sleep(0.3)
print(f"dummy focused: {ok}, fg==own: {fm.get_foreground_hwnd() == own}")

# --- T1: paste while OUR window is foreground -> must land in the child
core.paste_into_active_app("e2e paste 456")
time.sleep(1.2)
content = read_content()
t1 = content is not None and "e2e paste 456" in content
print(f"T1 (our-focus paste lands in child): {t1}  content={content!r}")

# --- T2: fresh-foreground path (child gets focus, then paste)
ok = fm.force_foreground(target)
time.sleep(0.4)
core.paste_into_active_app("second paste 789")
time.sleep(1.2)
content = read_content()
t2 = content is not None and "second paste 789" in content
print(f"T2 (fresh-target paste): {t2}  content={content!r}")

# ------------------------------------------------------------- cleanup
root.destroy()
child.terminate()
try:
    child.wait(5)
except subprocess.TimeoutExpired:
    child.kill()
print(f"==== RESULT: T1={'PASS' if t1 else 'FAIL'} T2={'PASS' if t2 else 'FAIL'} ====")
sys.exit(0 if (t1 and t2) else 1)
