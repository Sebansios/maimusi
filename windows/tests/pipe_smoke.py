"""Smoke test of the engine server's named-pipe mode (windows/build_engine.ps1 output).

Usage: python windows/tests/pipe_smoke.py [path to MaimusiEngine.exe]
Starts a private server, checks space/candidates/ping replies and that a second
copy with the same mutex exits at once, then stops it.
"""
import json
import subprocess
import sys
import time
from multiprocessing.connection import Client
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
exe = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "build/windows/engine/dist/MaimusiEngine/MaimusiEngine.exe")
name = "\\\\.\\pipe\\Maimusi.Test." + str(time.time_ns())
mutex = "Local\\Maimusi.Test." + str(time.time_ns())
proc = subprocess.Popen([exe, "--pipe", name, "--mutex", mutex, "--idle-minutes", "1"])
start = time.time()
while True:
    try:
        conn = Client(name, family="AF_PIPE")
        break
    except OSError:
        if time.time() - start > 90 or proc.poll() is not None:
            sys.exit(f"no pipe (engine exit {proc.poll()})")
        time.sleep(0.2)
print(f"ready after {time.time() - start:.1f}s")
failed = False
for req, check in [
    ({"id": 1, "op": "space", "text": "아버지가방에들어가신다"}, lambda r: r.get("text") == "아버지가 방에 들어가신다"),
    ({"id": 2, "op": "candidates", "word": "학교"}, lambda r: "學校" in r.get("items", [])),
    ({"id": 3, "op": "ping"}, lambda r: r.get("ok")),
]:
    t = time.time()
    conn.send_bytes(json.dumps(req, ensure_ascii=False).encode("utf-8"))
    reply = json.loads(conn.recv_bytes().decode("utf-8"))
    ok = reply.get("id") == req["id"] and check(reply)
    failed |= not ok
    print(f"{'PASS' if ok else 'FAIL'} {req['op']:<10} {1000 * (time.time() - t):.0f}ms")
second = subprocess.run([exe, "--pipe", name, "--mutex", mutex], timeout=60)
print(f"{'PASS' if second.returncode == 0 else 'FAIL'} second instance exits ({second.returncode})")
failed |= second.returncode != 0
conn.close()
proc.kill()
sys.exit(1 if failed else 0)
