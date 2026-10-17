#!/usr/bin/env python3
"""Headed: Context.setContextOverrides cache HIT on a real navigation.

A capture glob wins over HIT. Fetch.enable is never issued.
Usage: python cache_hit_nav.py --headed <chrome.exe>
"""
import json, os, subprocess, sys, tempfile, time, urllib.request

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("PYTHONUTF8", "1")

from websocket import create_connection

HEADED = "--headed" in sys.argv
args = [a for a in sys.argv[1:] if a != "--headed"]
CHROME = args[0] if args else r"D:\src\src\out\Default\chrome.exe"
DBG = 9344
HIT_URL = "https://zzbrowser.cache.test/hit.html"
CAPTURE_URL = "https://zzbrowser.cache.test/cap.html"
BODY = b"CACHE-HIT-BODY-42"

_id = [0]


def cmd(ws, method, params=None, sess=None):
    _id[0] += 1
    msg = {"id": _id[0], "method": method, "params": params or {}}
    if sess:
        msg["sessionId"] = sess
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id[0]:
            if "error" in r:
                raise RuntimeError("%s %s" % (method, r["error"]))
            return r.get("result", {})


def open_ctx(ws, cache):
    c = cmd(ws, "Target.createBrowserContext")["browserContextId"]
    t = cmd(ws, "Target.createTarget", {"url": "about:blank", "browserContextId": c})["targetId"]
    s = cmd(ws, "Target.attachToTarget", {"targetId": t, "flatten": True})["sessionId"]
    cmd(ws, "Context.setContextOverrides", {"cache": cache}, s)
    return s


def page_text(ws, sess, url):
    cmd(ws, "Page.enable", None, sess)
    cmd(ws, "Runtime.enable", None, sess)
    cmd(ws, "Network.enable", None, sess)
    nav = cmd(ws, "Page.navigate", {"url": url}, sess)
    print("navigate", url, nav, flush=True)
    last = ""
    for _ in range(40):
        time.sleep(0.25)
        try:
            v = cmd(
                ws,
                "Runtime.evaluate",
                {
                    "expression": "(document.body && document.body.innerText) || ''",
                    "returnByValue": True,
                },
                sess,
            )["result"]["value"]
            href = cmd(
                ws,
                "Runtime.evaluate",
                {"expression": "location.href", "returnByValue": True},
                sess,
            )["result"]["value"]
            last = ("%s | %s" % (href, v or ""))[:240]
            if v and BODY.decode() in v:
                return v
            if href and "chrome-error" in href and last:
                return last
        except Exception as e:
            last = str(e)[:160]
    return last


def main():
    methods = []
    events = []
    orig = cmd

    def wrapped(ws, method, params=None, sess=None):
        methods.append(method)
        return orig(ws, method, params, sess)

    globals()["cmd"] = wrapped

    cache_dir = tempfile.mkdtemp(prefix="ctx-hit-")
    with open(os.path.join(cache_dir, "hit.html"), "wb") as f:
        f.write(b"<html><body>" + BODY + b"</body></html>")
    with open(os.path.join(cache_dir, "cap.html"), "wb") as f:
        f.write(b"<html><body>SHOULD-NOT-SEE</body></html>")
    index = {
        HIT_URL: {
            "file": "hit.html",
            "status": 200,
            "headers": {
                "Content-Type": "text/html",
                "Content-Encoding": "gzip",
                "Set-Cookie": "sid=secret",
                "Cache-Control": "max-age=9",
            },
        },
        CAPTURE_URL: {
            "file": "cap.html",
            "status": 200,
            "headers": {"Content-Type": "text/html"},
        },
    }
    rules = {
        "captures": [CAPTURE_URL],
        "callbacks": [],
        "blocks": [],
        "allowMiss": [],
        "observe": [],
    }
    cache = {
        "dir": cache_dir,
        "map": json.dumps(index),
        "rules": json.dumps(rules),
    }

    subprocess.call("taskkill /F /IM chrome.exe /T", shell=True)
    time.sleep(1)
    prof = os.path.join(tempfile.gettempdir(), "cache-hit-profile")
    os.makedirs(prof, exist_ok=True)
    chrome_args = [CHROME]
    if not HEADED:
        chrome_args.append("--headless=new")
    chrome_args += [
        "--no-sandbox",
        "--password-store=basic",
        "--no-first-run",
        "--disable-extensions",
        "--disable-gpu",
        "--remote-allow-origins=*",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=%d" % DBG,
        "--user-data-dir=%s" % prof,
        "about:blank",
    ]
    cwd = os.path.dirname(os.path.abspath(CHROME)) or None
    print("launch headed=%s chrome=%s" % (HEADED, CHROME), flush=True)
    proc = subprocess.Popen(chrome_args, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        bws = None
        for _ in range(60):
            try:
                bws = json.load(urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/version" % DBG, timeout=1))["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.4)
        if not bws:
            print("FAIL no debug port", flush=True)
            return 1
        print("OK debug port", flush=True)
        ws = create_connection(bws, max_size=None)
        ws.settimeout(30)
        sess = open_ctx(ws, cache)
        cmd(ws, "Context.setContextOverrides", {"cache": cache}, sess)
        hit_text = page_text(ws, sess, HIT_URL)
        print("hit_text", repr(hit_text)[:180], flush=True)
        cap_text = page_text(ws, sess, CAPTURE_URL)
        print("capture_text", repr(cap_text)[:180], flush=True)
        fetch = [m for m in methods if m.startswith("Fetch.")]
        ctxm = [m for m in methods if m.startswith("Context.")]
        print("fetch_methods", fetch, flush=True)
        print("context_methods", ctxm, flush=True)
        if fetch:
            print("FAIL Fetch used", fetch, flush=True)
            return 1
        if "Context.setContextOverrides" not in methods:
            print("FAIL no Context.setContextOverrides", flush=True)
            return 1
        if BODY.decode() not in (hit_text or ""):
            print("FAIL missing HIT body", flush=True)
            return 1
        if "SHOULD-NOT-SEE" in (cap_text or ""):
            print("FAIL capture served HIT", flush=True)
            return 1
        print("CACHE MATCH PASS", flush=True)
        return 0
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        subprocess.call("taskkill /F /IM chrome.exe /T", shell=True)


if __name__ == "__main__":
    sys.exit(main())
