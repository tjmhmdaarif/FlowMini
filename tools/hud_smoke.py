"""HUD smoke test: drive DictationHud through its states, then exit.

Run with the venv python from the repo root:

    .venv\\Scripts\\python.exe tools\\hud_smoke.py

The HUD appears near the cursor: RECORDING (~6s) -> THINKING (~3s) -> PASTED (~5s).
Useful for visual checks without a microphone.
"""
import math
import os
import sys
import time

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

import tkinter as tk
import flowmini_app as fa


def main():
    """Drive the HUD through every state with simulated mic levels."""
    root = tk.Tk()
    root.withdraw()
    hud = fa.DictationHud()

    # RECORDING with a simulated pulsing mic level (~6s)
    hud.show("recording", "")
    t0 = time.time()
    while time.time() - t0 < 6:
        hud.set_level(900 + 1600 * abs(math.sin(time.time() * 3)))
        hud.draw_meter()
        root.update()
        time.sleep(0.03)

    # THINKING with a partial transcript
    hud.show("processing", "transcribing…")
    t0 = time.time()
    while time.time() - t0 < 3:
        hud.draw_meter()
        root.update()
        time.sleep(0.05)

    # PASTED with the polished text
    hud.show("pasted", "Hello, hello. Mic testing. This is the one here. Hello.")
    t0 = time.time()
    while time.time() - t0 < 5:
        hud.draw_meter()
        root.update()
        time.sleep(0.05)

    hud.hide()
    print("HUD SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
