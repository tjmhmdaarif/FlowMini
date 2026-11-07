"""Test client: connects to the FlowMini bridge and logs every received event.
Usage: python test_client.py <port> [seconds]
"""
import asyncio
import json
import sys
import time

import websockets

port = sys.argv[1] if len(sys.argv) > 1 else "8765"
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

uri = f"ws://127.0.0.1:{port}"
seen = []
started = False
start_time = time.time()


async def main():
    global started
    async with websockets.connect(uri, ping_interval=None) as ws:
        print(f"[client] connected to {uri}", flush=True)
        await ws.send(json.dumps({"cmd": "start"}))
        print("[client] sent cmd=start", flush=True)
        while time.time() - start_time < seconds:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                ev = json.loads(msg)
                seen.append(ev)
                typ = ev.get("type")
                if typ == "status":
                    print(f"[client] status={ev.get('status')}", flush=True)
                elif typ == "partial":
                    print(f"[client] partial={ev.get('text')!r}", flush=True)
                elif typ == "result":
                    print(f"[client] result={ev.get('final')!r} lang={ev.get('language')}",
                          flush=True)
                elif typ == "level":
                    print(f"[client] level={ev.get('level')} active={ev.get('active')}",
                          flush=True)
                elif typ == "connected":
                    print(f"[client] connected={ev.get('value')}", flush=True)
                elif typ == "error":
                    print(f"[client] ERROR={ev.get('message')}", flush=True)
                else:
                    print(f"[client] {typ}", flush=True)
            except asyncio.TimeoutError:
                continue
        print(f"[client] done after {seconds}s; total events={len(seen)}", flush=True)
        print("[client] event types:", sorted({e.get('type') for e in seen}), flush=True)
        missing = [
            t for t in ("status", "level", "partial", "result", "connected", "error")
            if t not in {e.get("type") for e in seen}
        ]
        if missing:
            print(f"[client] MISSING event types: {missing}", flush=True)
            sys.exit(1)
        print("[client] ALL EXPECTED TYPES RECEIVED", flush=True)


asyncio.run(main())
