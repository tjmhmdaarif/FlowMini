import subprocess
import time

# Find PIDs listening on 8765 / 8123 via netstat, then kill them.
for port in (8765, 8123):
    out = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            # netstat -ano: Proto Local Address Foreign Address State PID
            pid = parts[-1]
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
            print(f"killed {pid} holding port {port}")
    time.sleep(1)

# Confirm ports are free.
for port in (8765, 8123):
    s = subprocess.run(["python", "-c",
        "import socket; s=socket.socket(); s.settimeout(1); "
        f"print('PORT {port}: ' + ('LISTENING' if s.connect_ex(('127.0.0.1', port)) == 0 else 'FREE'))"],
        capture_output=True, text=True)
    print(s.stdout.strip())
