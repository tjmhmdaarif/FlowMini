"""Paste e2e v2: verifies paste lands in the right window without touching
any of the user's apps.

Child = a tiny Tk window (separate PROCESS) with an Entry; it takes the
real foreground with an actual mouse click on itself (the same way a user
focuses their window, no foreground-lock hacks), publishes its own
top-level hwnd + pid, and mirrors its Entry content to a per-run JSON
marker every 200 ms. Parent = real FlowMini core; it pastes with (T1) the
child foreground and (T2) FlowMini's own dummy window foreground (the
resolver must fall back to the child). No Notepad; nothing is killed but
the child PID.
"""
import ctypes
import ctypes.wintypes as wt
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
_k32 = ctypes.windll.kernel32

MARKER = os.path.join(os.environ["TEMP"], "opencode",
                      f"paste_e2e_{os.getpid()}.json")
CHILD_CODE = r"""
import ctypes, json, os, time, tkinter as tk
MARKER = %r
root = tk.Tk()
root.title("FlowMiniPasteTarget")
root.geometry("320x120+420+260")
root.update()
uu = ctypes.windll.user32
uu.GetParent.restype = ctypes.c_void_p
hwnd = int(root.winfo_id())
p = uu.GetParent(hwnd)
while p:
    hwnd = p
    p = uu.GetParent(hwnd)
hwnd = int(hwnd)
var = tk.StringVar()
entry = tk.Entry(root, textvariable=var, width=44, font=("Segoe UI", 12))
entry.pack(padx=10, pady=30)
entry.focus_set()
def flush():
    try:
        with open(MARKER, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "hwnd": hwnd,
                       "focused": uu.GetForegroundWindow() == hwnd,
                       "n_chars": len(var.get()), "text": var.get()}, fh)
    except Exception:
        pass
    root.after(200, flush)
flush()
def self_click_and_focus():
    # Click own title bar, then claim foreground in-process.
    # A real mouse click into our own title bar arrives as user input; a
    # process that just received input may call SetForegroundWindow itself.
    try:
        x = root.winfo_rootx() + 40
        y = root.winfo_rooty() - 14
        uu.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
        uu.mouse_event(0x0002, 0, 0, 0, 0)
        uu.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.08)
        uu.SetForegroundWindow(hwnd)
    except Exception:
        pass
    root.after(1000, self_click_and_focus)


root.after(700, self_click_and_focus)
root.after(120000, root.destroy)
root.mainloop()
""" % MARKER


def read_marker(need_hwnd=True, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(MARKER, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data and (not need_hwnd or data.get("hwnd")):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    return None


def verify_self_reported(marker):
    """Parent-side sanity check of the child's self-reported hwnd."""
    h = marker.get("hwnd", 0)
    buf = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(h, buf, 64)
    cls = buf.value
    buf = ctypes.create_unicode_buffer(64)
    u.GetWindowTextW(h, buf, 64)
    pid_c = ctypes.c_ulong()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid_c))
    if buf.value != "FlowMiniPasteTarget":
        return None, f"reported hwnd {h:#x} has title {buf.value!r}"
    if pid_c.value != marker.get("pid"):
        return None, (f"hwnd {h:#x} owned by pid {pid_c.value} != "
                      f"marker pid {marker.get('pid')} "
                      f"(popen pid {child.pid} is the venv shim)")
    if not u.IsWindowVisible(h):
        return None, f"reported hwnd {h:#x} is not visible"
    return h, cls


def wait_foreground(h, timeout=5.0):
    """Wait until h really is the foreground window."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        fg = u.GetForegroundWindow()
        if fg == h:
            return True
        time.sleep(0.2)
    return False


def guarded_paste(core, text, expected_h):
    """Refuse to inject unless the expected window is foreground RIGHT NOW.

    The paste target on a live desktop can be the user's real app; the test
    must never put text there. Abort (return None, skip the case) instead.
    """
    fg = u.GetForegroundWindow()
    if fg != expected_h:
        print(f"!!! GUARD: fg is {fg:#x}, expected {expected_h:#x} — "
              f"PASTE SKIPPED (would have hit a real window)")
        return "skipped"
    core.paste_into_active_app(text)
    time.sleep(1.2)
    return (read_marker() or {}).get("text", "")


def click_at(x, y):
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)


child = subprocess.Popen([sys.executable, "-c", CHILD_CODE])
print(f"popen pid: {child.pid}")

root = None
target = None
t1 = t2 = False
try:
    marker = read_marker()
    assert marker, "child never published its window handle"
    target, cls = verify_self_reported(marker)
    print(f"child window: {target:#x} class={cls!r}")
    assert target, f"self-reported hwnd failed parent verification: {cls}"
    print(f"initial content: {marker.get('text')!r}")

    # ------------------------------------------------------------- real core
    cfg = fm.load_config()
    core = fm.FlowMini(cfg, fm.init_db(), on_event=lambda e, d=None: None)

    # ---- T1: the child claims the foreground itself (click + self-SFGW)
    ok = wait_foreground(target, 5.0)
    b = read_marker() or {}
    print(f"T1 child self-focused: wait={ok}, child says focused={b.get('focused')}")
    if not ok:
        print(f"!!! ABORT T1: fg is a real window — paste skipped")
    else:
        content = guarded_paste(core, "e2e paste 456", target)
        t1 = content not in (None, "skipped") and "e2e paste 456" in content
        print(f"T1 (child-focused paste lands in child): {t1}  content={content!r}")

    # ---- T2: FlowMini's own dummy window foreground -> must fall back to child
    root = tk.Tk()
    root.title("Dummy FlowMini")
    root.geometry("260x140+40+40")
    root.attributes("-topmost", True)
    root.update()
    own = u.GetAncestor(root.winfo_id(), 2)
    core.own_hwnd = own
    click_at(root.winfo_rootx() + 130, root.winfo_rooty() - 14)
    ok = wait_foreground(own, 3.0)
    print(f"T2 dummy foreground: {ok}")
    if not ok:
        print("!!! ABORT T2: fg is a real window — paste skipped")
    else:
        # control the test environment: make the poller-tracked "last external"
        # the child, not the user's real apps (the poller ignores our own
        # window, so this state holds while the dummy keeps focus)
        core.last_external_hwnd = target
        core.paste_into_active_app("second paste 789")
        time.sleep(1.2)
        content_after = (read_marker() or {}).get("text", "")
        t2 = "second paste 789" in content_after
        print(f"T2 (own-window focus, falls back to child): {t2}  content={content_after!r}")
finally:
    if root is not None:
        root.destroy()
    child.terminate()
    try:
        child.wait(5)
    except subprocess.TimeoutExpired:
        child.kill()
    try:
        os.remove(MARKER)
    except OSError:
        pass

print(f"==== RESULT: T1={'PASS' if t1 else 'FAIL'} T2={'PASS' if t2 else 'FAIL'} ====")
sys.exit(0 if (t1 and t2) else 1)
