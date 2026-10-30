# -*- coding: utf-8 -*-
"""Tests for the Day-2 model download progress bar plumbing.

Script-style: run with `python tests_model_progress.py`.
No network, no HuggingFace, no microphone — pure logic tests.
"""

import time

import flow_mini as fm

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


class FakeBar:
    """Stands in for a huggingface_hub tqdm instance."""

    def __init__(self, desc, total):
        self.desc = desc
        self.total = total
        self.n = 0


def main():
    tracker = fm.ModelDownloadTracker(emit=lambda ev, data: None)

    # T1: two files, both with known totals -> cumulative percent
    tracker.update(FakeBar("model.bin: ", 1_000_000_000))
    b1 = FakeBar("model.bin: ", 1_000_000_000)
    b1.n = 500_000_000
    tracker.update(b1)
    done, total = tracker.tally()
    check("file1 half-done -> 500 MB", abs(done - 500_000_000) < 1_000_000)
    check("total is known", abs(total - 1_000_000_000) < 1_000_000)
    check("percent ~50%", tracker.pct() is not None and 49.0 <= tracker.pct() <= 51.0)
    check("message has percent and MB",
          "50%" in tracker.message() and "MB" in tracker.message())

    # T2: second file opens with known total -> percent still correct
    b2 = FakeBar("tokenizer.json: ", 8_000_000)
    b2.n = 8_000_000
    tracker.update(b2)
    check("two files -> done sums both files", tracker.pct() is not None)
    check("two files pct between file shares",
          tracker.tally()[1] == 1_008_000_000
          and abs(tracker.tally()[0] - 508_000_000) < 1_000_000)

    # T3: bar with unknown total -> pct None, MB-only message
    t3 = fm.ModelDownloadTracker(emit=lambda ev, data: None)
    t3.update(FakeBar("mystery.bin: ", 0))
    m3 = FakeBar("mystery.bin: ", 0)
    m3.n = 123_456_789  # hf sets total=0-sized bars? unknown case
    # a bar with bytes but no total: FakeBar total 0
    t3.update(m3)
    check("unknown total -> pct None", t3.pct() is None)
    check("unknown total -> MB-only message", "%" not in t3.message() and "MB" in t3.message())

    # T4: resume-with-new-bar does not double count (same descriptor)
    t4 = fm.ModelDownloadTracker(emit=lambda ev, data: None)
    r1 = FakeBar("model.bin: ", 1_000_000_000)
    r1.n = 300_000_000
    t4.update(r1)
    r2 = FakeBar("model.bin: ", 1_000_000_000)  # fresh bar after reconnect
    r2.n = 400_000_000
    t4.update(r2)
    check("resume replaces old bar state", t4.pct() is not None and 39.0 <= t4.pct() <= 41.0)

    # T5: rate limiter suppresses rapid notifications, force still emits
    events = []
    t5 = fm.ModelDownloadTracker(emit=lambda ev, data: events.append(data),
                                 min_interval_s=0.5)
    bar = FakeBar("d: ", 100)
    for i in range(1, 21):
        bar.n = i * 5
        t5.update(bar)
    check("rate limit collapses rapid updates", len(events) <= 3)
    t5.notify(force=True)
    check("force emits immediately", len(events) >= 2)
    t5.notify(force=True)
    check("two forced emit twice", len(events) >= 3)
    pct_in_last = events[-1]["pct"]
    check("last event carries pct 100", pct_in_last == 100.0)

    # T6: progress stays monotonic under growing/mixed loads
    t6 = fm.ModelDownloadTracker(emit=lambda ev, data: None)
    seen = []
    for step in range(0, 11):
        b = FakeBar("model.bin: ", 1000)
        b.n = step * 100
        t6.update(b)
        p = t6.pct()
        seen.append(p)
    check("monotonic pct chain", all(a is not None and b_ is not None and a <= b_
                                     for a, b_ in zip(seen, seen[1:])))

    # T7: HfHubTqdm wiring — updates reach the tracker via the class hook
    import io
    seen7 = []
    fm.HfHubTqdm._tracker = fm.ModelDownloadTracker(
        emit=lambda ev, data: seen7.append(data), min_interval_s=0)
    try:
        # disable=False (hf's real mode); noisy output goes to a buffer
        bar7 = fm.HfHubTqdm(total=100, desc="wiring.bin: ",
                            file=io.StringIO())
        bar7.update(40)
        bar7.update(60)
        got = fm.HfHubTqdm._tracker.tally()
        check("first update event saw 40%", len(seen7) >= 1 and seen7[0]["pct"] == 40.0)
        check("final tqdm n=100", got[0] == 100 and got[1] == 100)
        check("wiring event pct == 100", seen7[-1]["pct"] == 100.0)
    finally:
        fm.HfHubTqdm._tracker = None

    # T8: tracker reset clears state
    t8 = fm.ModelDownloadTracker(emit=lambda ev, data: None)
    t8.update(FakeBar("x: ", 1000))
    t8.reset()
    check("reset -> zero tally", t8.tally() == (0, None) and t8.pct() is None)

    print(f"==== RESULT: {PASS} passed, {FAIL} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
