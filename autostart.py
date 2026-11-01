# -*- coding: utf-8 -*-
"""Day 4: auto-start with Windows.

Manages the user-scope Windows registry entry that launches FlowMini at
logon:

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run  ->  value "FlowMini"

Pure stdlib (``winreg``), user-scope only (HKCU) so it never needs admin
rights, never touches the network, and cleans itself up when the toggle
goes off.  The launch command depends on how FlowMini is running:

    frozen exe (PyInstaller onedir):  ``"<exe path>"``
    from source:                      ``"<pythonw.exe path>" "<flowmini_app.py path>"``

``pythonw.exe`` is preferred for source runs so no console window pops
up at logon; plain ``python.exe`` is only a fallback when pythonw is
missing.  Registry access failures are reported, never raised — a busy
or restricted key must not stop the dictation app from starting.
"""

import os
import sys

try:
    import winreg
except ImportError:                      # non-Windows: every call degrades to a no-op
    winreg = None


RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FlowMini"


def is_windows():
    """True when the real ``winreg`` module is importable."""
    return winreg is not None


def is_frozen():
    """True inside the packaged exe (PyInstaller sets sys.frozen)."""
    return bool(getattr(sys, "frozen", False))


def build_launch_command(frozen=None, python_exe=None, app_path=None):
    """Return the exact command line Windows should run at logon.

    Args:
        frozen:     override the frozen-exe detection (used by tests).
        python_exe: override ``sys.executable`` (used by tests).
        app_path:   path to ``flowmini_app.py`` for source runs (used by
                    tests; the default resolves next to this file).

    Returns:
        A quoted command string, e.g.
        ``'"C:\\\\...\\\\FlowMini.exe"'`` or
        ``'...\\pythonw.exe" "...\\flowmini_app.py"'``.
    """
    frozen = is_frozen() if frozen is None else bool(frozen)
    if frozen:
        exe = python_exe if python_exe is not None else sys.executable
        return f'"{exe}"'
    python_exe = python_exe or sys.executable
    pyw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = python_exe
    if app_path is None:
        app_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "flowmini_app.py")
    return f'"{pyw}" "{app_path}"'


def read_run_entry(root=None, subkey=RUN_SUBKEY, value=VALUE_NAME):
    """Return the stored launch command, or ``None`` when absent/unreadable.

    All arguments are injectable so tests can exercise a scratch key
    instead of the live logon entry.
    """
    if winreg is None:
        return None
    if root is None:
        root = winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_QUERY_VALUE) as key:
            command, _type = winreg.QueryValueEx(key, value)
            return command
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[FlowMini] autostart: could not read the Run key ({exc})")
        return None


def is_enabled(root=None, subkey=RUN_SUBKEY, value=VALUE_NAME):
    """True when a FlowMini auto-start entry exists (regardless of command)."""
    return read_run_entry(root, subkey, value) is not None


def set_run_entry(enable, root=None, subkey=RUN_SUBKEY, value=VALUE_NAME,
                  command=None):
    """Create/refresh (``enable=True``) or delete the Run entry.

    Returns ``True`` when the registry reflects the requested state
    afterwards, ``False`` when the write/delete failed.
    """
    if winreg is None:
        print("[FlowMini] autostart: not on Windows — auto-start unavailable")
        return False
    if root is None:
        root = winreg.HKEY_CURRENT_USER
    try:
        try:
            key = winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            # A fresh profile (or our scratch test key) may not have this
            # subkey at all — create it instead of failing the toggle.
            key = winreg.CreateKey(root, subkey)
        with key:
            if enable:
                entry = command if command is not None else build_launch_command()
                winreg.SetValueEx(key, value, 0, winreg.REG_SZ, entry)
                return True
            try:
                winreg.DeleteValue(key, value)
            except FileNotFoundError:
                pass               # already off — that is what we wanted
            return True
    except OSError as exc:
        print(f"[FlowMini] autostart: registry write failed ({exc})")
        return False


def sync_on_startup(want_on, root=None, subkey=RUN_SUBKEY, value=VALUE_NAME,
                    command=None):
    """Bring the logon entry in line with the user's saved choice.

    Runs once at app start so the machine always matches what the user
    last picked (and a moved exe or a manually deleted entry heals on
    the next launch).

    Returns one of:
        "on"      entry already present, command already current (no write)
        "healed"  entry rewritten (was missing or pointed elsewhere)
        "removed" stale entry deleted because the choice is OFF
        "off"     nothing registered and the choice is OFF
        "failed"  registry error; state unknown, user warned
    """
    want_on = bool(want_on)
    present = is_enabled(root, subkey, value)
    if want_on:
        entry = command if command is not None else build_launch_command()
        current = read_run_entry(root, subkey, value)
        if present and current == entry:
            return "on"
        if set_run_entry(True, root, subkey, value, entry):
            return "healed" if present else "healed"
        return "failed"
    if present:
        return "removed" if set_run_entry(False, root, subkey, value) else "failed"
    return "off"
