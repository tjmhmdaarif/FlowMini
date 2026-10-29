@echo off
cd /d "%~dp0"
echo Starting FlowMini Voice Dictation...
echo   Ctrl+Alt+D  = push-to-talk dictation
echo   Ctrl+Alt+F  = hands-free VAD mode
echo ---------------------------------------
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "flowmini_app.py"
) else (
    start "" pythonw "flowmini_app.py"
)
