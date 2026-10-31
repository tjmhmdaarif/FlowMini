# -*- coding: utf-8 -*-
"""Tests for Day-3 per-app profiles (matching, effective settings, dev output).

Script-style: run with `python tests_profiles.py`.
No microphone, no network, no GUI — pure logic plus safe Win32 identity
lookups (process name / window title of the current foreground window).
"""

import sqlite3
import sys

import flow_mini as fm
import speech_transform as st

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def make_core(**overrides):
    """A real FlowMini wired to an in-memory DB with captured events."""
    cfg = dict(fm.DEFAULT_CONFIG)
    cfg["api_key"] = ""
    cfg.update(overrides)
    events = []
    core = fm.FlowMini(cfg, sqlite3.connect(":memory:"),
                       on_event=lambda e, d=None: events.append((e, d)))
    return core, events


def test_normalize():
    print("-- normalize_profiles --")
    defaults = fm.normalize_profiles(None)
    check("None -> built-in defaults (code + mail)",
          [p["name"] for p in defaults] == ["code", "mail"])
    check("defaults carry developer_mode for code",
          defaults[0]["overrides"].get("developer_mode") is True)
    check("defaults carry formal style for mail",
          defaults[1]["overrides"].get("style_preset") == "formal")
    defaults[0]["apps"].append("mutated.exe")
    check("defaults are copies, not shared references",
          all("mutated.exe" not in p["apps"] for p in fm.DEFAULT_APP_PROFILES))

    check("[] stays empty (explicit opt-out)", fm.normalize_profiles([]) == [])
    check("non-list falls back to defaults",
          [p["name"] for p in fm.normalize_profiles({"name": "x"})] == ["code", "mail"])

    messy = [
        "not-a-dict",
        {"apps": ["ghost.exe"]},                       # no name
        {"name": "no-patterns", "developer_mode": True},  # no apps/title
        {"name": "no-overrides", "apps": ["a.exe"]},      # overrides nothing
        {"name": "good", "apps": ["a.exe"], "developer_mode": True,
         "frobnicate": 123},                            # unknown key dropped
    ]
    clean = fm.normalize_profiles(messy)
    check("bad entries skipped, good one kept",
          [p["name"] for p in clean] == ["good"])
    check("unknown override keys never survive",
          clean and list(clean[0]["overrides"]) == ["developer_mode"])
    check("unlisted keys never survive",
          clean and "frobnicate" not in clean[0])

    str_case = fm.normalize_profiles(
        [{"name": "t", "apps": "Only.EXE", "developer_mode": True}])
    check("string apps coerced to a list", str_case[0]["apps"] == ["only.exe"])
    case = fm.normalize_profiles(
        [{"name": "t", "apps": ["UPPER.EXE"], "style_preset": "FORMAL"}])
    check("patterns + values lowercased",
          case[0]["apps"] == ["upper.exe"]
          and case[0]["overrides"]["style_preset"] == "formal")
    bad_style = fm.normalize_profiles(
        [{"name": "s", "apps": ["a.exe"], "style_preset": "banana"},
         {"name": "c", "apps": ["b.exe"], "cleanup_mode": "turbo"}])
    check("invalid style falls back to casual",
          bad_style[0]["overrides"]["style_preset"] == "casual")
    check("invalid cleanup falls back to light",
          bad_style[1]["overrides"]["cleanup_mode"] == "light")


def test_select():
    print("-- select_profile --")
    defaults = fm.normalize_profiles(None)

    got = fm.select_profile("CODE.EXE", "", defaults)
    check("case-insensitive exe match hits code profile",
          got and got["name"] == "code")
    got = fm.select_profile("OUTLOOK.EXE", "", defaults)
    check("case-insensitive exe match hits mail profile",
          got and got["name"] == "mail")
    check("no match returns None",
          fm.select_profile("chrome.exe", "some page", defaults) is None)
    check("None process + None title never crashes",
          fm.select_profile(None, None, defaults) is None)

    wild = [{"name": "wild", "apps": ["*studio*", "cursor*", "*env*"],
             "title": [], "overrides": {"developer_mode": True}}]
    check("wildcard infix pattern matches (*env* ~ devenv.exe)",
          fm.select_profile("devenv.exe", "", wild) is not None)
    check("wildcard prefix pattern matches (cursor* ~ cursor.exe)",
          fm.select_profile("cursor.exe", "", wild) is not None)
    check("wildcards do not over-match",
          fm.select_profile("notepad.exe", "", wild) is None)

    web = [{"name": "gmail", "apps": [], "title": ["*gmail*"],
            "overrides": {"style_preset": "formal"}}]
    hit = fm.select_profile("chrome.exe", "Inbox (3) - Gmail - Google Chrome", web)
    check("title pattern matches browser tabs", hit is not None)
    check("title match works without a process name",
          fm.select_profile(None, "Gmail", web) is not None)
    check("title mismatch does not fire",
          fm.select_profile(None, "Docs - Google Chrome", web) is None)

    ordered = [{"name": "first", "apps": ["a.exe"], "title": [],
                "overrides": {"developer_mode": True}},
               {"name": "second", "apps": ["a.exe"], "title": [],
                "overrides": {"style_preset": "formal"}}]
    check("first matching rule wins",
          fm.select_profile("a.exe", "", ordered)["name"] == "first")
    check("rule without patterns never fires",
          fm.select_profile("a.exe", "", [{"name": "empty", "apps": [],
                                           "title": [], "overrides": {}}]) is None)


def test_win32_identity():
    print("-- window identity (Win32) --")
    check("no handle -> no process", fm.get_window_process_name(None) is None)
    check("invalid handle -> no process",
          fm.get_window_process_name(0) is None)
    check("no handle -> empty title", fm.get_window_title(None) == "")

    fg = fm.get_foreground_hwnd()
    name = fm.get_window_process_name(fg)
    title = fm.get_window_title(fg)
    check("process name is a lowercase .exe or None (never raises)",
          name is None or (name == name.lower() and name.endswith(".exe")))
    check("window title is a string", isinstance(title, str))


def test_effective_and_resolve():
    print("-- effective settings + resolve_profile --")
    core, events = make_core()
    check("profile defaults to off-active state", core.active_profile is None)
    check("global settings are the effective ones by default",
          core._effective("cleanup_mode") == core.cleanup_mode
          and core._effective("developer_mode") == core.developer_mode
          and core._effective("style_preset") == core.style_preset)

    core.active_profile = {"name": "code", "app": "code.exe",
                           "overrides": {"developer_mode": True}}
    check("profile override wins for this dictation",
          core._effective("developer_mode") is True)
    check("global developer_mode stays untouched",
          core.developer_mode is False)
    check("unrelated settings still come from global config",
          core._effective("cleanup_mode") == core.cleanup_mode
          and core._effective("style_preset") == core.style_preset)

    check("invalid hwnd resolves to no profile", core.resolve_profile(0) is None)
    check("resolve cleared the stale profile", core.active_profile is None)
    prof_events = [d for e, d in events if e == "profile"]
    check("profile change emitted an event",
          prof_events and prof_events[-1]["name"] is None)
    before = len(prof_events)
    core.resolve_profile(0)
    check("no event when the profile did not change",
          len([d for e, d in events if e == "profile"]) == before)

    core.profiles = fm.normalize_profiles(
        [{"name": "mail", "apps": ["whatever.exe"],
          "style_preset": "formal"}])
    core.set_profiles_enabled(True)
    fg = fm.get_foreground_hwnd()
    proc = fm.get_window_process_name(fg)
    if proc and fg:
        core.profiles = fm.normalize_profiles(
            [{"name": "selfwin", "apps": [proc], "developer_mode": True}])
        got = core.resolve_profile(fg)
        check("real window resolves to the matching rule",
              got is not None and got["name"] == "selfwin"
              and got["app"] == proc)
        check("resolved overrides are effective",
              core._effective("developer_mode") is True)
        events.clear()
        core.resolve_profile(fg)
        check("same rule re-resolves silently",
              not [e for e, d in events if e == "profile"])
    else:
        print("  SKIP  foreground process unavailable in this session")

    core.set_profiles_enabled(False)
    check("disabling clears the active profile", core.active_profile is None)
    core.profiles = fm.normalize_profiles([{"name": "z", "apps": ["z.exe"],
                                            "developer_mode": True}])
    core.set_profiles_enabled(False)
    check("disabled profiles never fire",
          core.resolve_profile(fg or 0) is None)


def test_developer_transform():
    print("-- developer_mode output (Speech Transform) --")
    kw = dict(asr_language="en", asr_confidence=0.99)
    check("light: caps + terminal period",
          st.transform_transcript("import os", **kw).finalText == "Import os.")
    check("developer: code stays verbatim",
          st.transform_transcript("import os", developer_mode=True,
                                  **kw).finalText == "import os")
    check("developer still removes fillers",
          st.transform_transcript("um import os please", developer_mode=True,
                                  **kw).finalText == "import os please")
    check("light turns a trailing comma into a period",
          st.transform_transcript("foo bar,", **kw).finalText == "Foo bar.")
    check("developer keeps a dictated trailing comma",
          st.transform_transcript("foo bar,", developer_mode=True,
                                  **kw).finalText == "foo bar,")
    check("developer still maps spoken symbols",
          st.transform_transcript("open paren x close paren",
                                  developer_mode=True,
                                  **kw).finalText == "(x)")
    check("cleanup off bypasses everything regardless of developer mode",
          st.transform_transcript("foo bar,", cleanup_mode="off",
                                  developer_mode=True,
                                  **kw).finalText == "foo bar,")

    req = st.transform_request({"transcript": "import os", "asrLanguage": "en",
                                "asrConfidence": 0.99, "developerMode": True})
    check("transform_request passes developerMode through",
          req.finalText == "import os")
    req2 = st.transform_request({"transcript": "import os", "asrLanguage": "en",
                                 "asrConfidence": 0.99})
    check("transform_request defaults developerMode to off",
          req2.finalText == "Import os.")


def test_gui_wiring():
    print("-- GUI wiring --")
    import flowmini_app
    check("per-app profile toggle handler exists",
          hasattr(flowmini_app.FlowMiniApp, "_on_profiles_toggle"))
    check("profile event handler exists",
          hasattr(flowmini_app.FlowMiniApp, "_handle_profile_event"))
    check("HUD profile chip helper exists",
          hasattr(flowmini_app.FlowMiniApp, "_hud_profile_chip"))
    check("profiles are enabled by default in DEFAULT_CONFIG",
          fm.DEFAULT_CONFIG.get("app_profiles_enabled") is True)
    core, _ = make_core(app_profiles_enabled=False)
    check("app_profiles_enabled config reaches the core",
          core.app_profiles_enabled is False)


def main():
    test_normalize()
    test_select()
    test_win32_identity()
    test_effective_and_resolve()
    test_developer_transform()
    test_gui_wiring()
    print(f"==== RESULT: {PASS} passed, {FAIL} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
