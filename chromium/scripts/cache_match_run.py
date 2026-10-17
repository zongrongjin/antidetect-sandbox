#!/usr/bin/env python3
"""Run shipped Context match tests; print CACHE MATCH PASS."""
import os
import subprocess
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cdpyz"))
env = os.environ.copy()
env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
cmd = [sys.executable, "-m", "unittest",
       "tests.test_context_match", "tests.test_interceptor_no_star"]
print("PYTHONPATH", root, flush=True)
r = subprocess.run(cmd, cwd=root, env=env)
if r.returncode != 0:
    sys.exit(r.returncode)
nav = os.path.join(os.path.dirname(__file__), "cache_hit_nav.py")
chrome = os.environ.get("CHROME", r"D:\src\src\out\Default\chrome.exe")
if os.path.isfile(chrome) and os.path.isfile(nav):
    r2 = subprocess.run([sys.executable, nav, "--headed", chrome], env=env)
    if r2.returncode != 0:
        sys.exit(r2.returncode)
    print("CACHE MATCH PASS", flush=True)
    sys.exit(0)
print("CACHE MATCH PASS (unit only; no chrome)", flush=True)
sys.exit(0)
