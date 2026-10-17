# -*- coding: utf-8 -*-
"""Check url+html fake document runs a real load lifecycle (not DOM inject).

Compares fake html vs a live HTTP page:
  parser-head readyState == loading
  readystatechange interactive + complete
  DOMContentLoaded, window load, pageshow
  Navigation Timing loadEventEnd / domContentLoadedEventEnd
  BiDi browsingContext.navigationStarted / domContentLoaded / load
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("MOZ_DISABLE_CONTENT_SANDBOX", "1")

from websocket import create_connection

FF = sys.argv[1] if len(sys.argv) > 1 else "/root/ff/firefox-152.0.5/obj-release/dist/bin/firefox"
PORT = int(os.environ.get("FF_BIDI_PORT", "19224"))
FAKE_URL = "http://zz-html-life.test/"

PROBE_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>life</title>
<script>
(function(){
  window.__life = [{ev:'parser-head', rs: document.readyState, href: location.href}];
  document.addEventListener('readystatechange', function(){
    window.__life.push({ev:'readystatechange', rs: document.readyState});
  });
  document.addEventListener('DOMContentLoaded', function(){
    window.__life.push({ev:'DOMContentLoaded', rs: document.readyState});
  });
  window.addEventListener('load', function(){
    window.__life.push({ev:'load', rs: document.readyState});
  });
  window.addEventListener('pageshow', function(e){
    window.__life.push({ev:'pageshow', rs: document.readyState, persisted: !!e.persisted});
  });
})();
</script>
</head>
<body>
<div id="x">LIFE-OK</div>
<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" width="1" height="1">
</body>
</html>
"""

_id = 0
ok = True
events = []


def check(name, cond, got=""):
    global ok
    print("  %-52s %s  %s" % (name, "OK" if cond else "FAIL", got))
    if not cond:
        ok = False


def cmd(ws, method, params=None, timeout=40):
    global _id
    _id += 1
    mid = _id
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise RuntimeError("timeout %s" % method)
        ws.settimeout(max(left, 0.1))
        r = json.loads(ws.recv())
        if r.get("type") == "event":
            events.append(r)
            continue
        if r.get("id") == mid:
            if r.get("type") == "error":
                raise RuntimeError("%s: %s" % (method, r.get("message")))
            return r.get("result", {})


def js(ws, ctx, expr):
    r = cmd(
        ws,
        "script.evaluate",
        {"expression": expr, "target": {"context": ctx}, "awaitPromise": False},
    )
    val = r.get("result", {})
    t = val.get("type")
    if t in ("string", "number", "boolean"):
        return val.get("value")
    if t in ("null", "undefined"):
        return None
    return val


def js_json(ws, ctx, expr):
    raw = js(ws, ctx, "JSON.stringify(%s)" % expr)
    return json.loads(raw) if raw else None


def wait_bidi(port, tries=40):
    for _ in range(tries):
        try:
            w = create_connection(
                "ws://127.0.0.1:%d/session" % port,
                suppress_origin=True,
                timeout=2,
            )
            w.close()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def drain(ws, seconds=0.8):
    end = time.time() + seconds
    ws.settimeout(0.2)
    while time.time() < end:
        try:
            r = json.loads(ws.recv())
            if r.get("type") == "event":
                events.append(r)
        except Exception:
            pass


class Live(BaseHTTPRequestHandler):
    hits = 0

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        Live.hits += 1
        body = PROBE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_live():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Live)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def bidi_names(ctx=None):
    names = []
    for e in events:
        method = e.get("method")
        params = e.get("params") or {}
        if ctx and params.get("context") not in (None, ctx):
            continue
        names.append(method)
    return names


def assess(tag, life, nav, names):
    print("\n===== %s =====" % tag)
    print("  life=%s" % life)
    print("  nav=%s" % nav)
    print("  bidi=%s" % names)
    evs = [x.get("ev") for x in (life or [])]
    rss = {x.get("ev"): x.get("rs") for x in (life or [])}
    rsc_states = [x.get("rs") for x in (life or []) if x.get("ev") == "readystatechange"]
    head = (life or [{}])[0] if life else {}
    check("%s parser-head readyState=loading" % tag, head.get("rs") == "loading", head)
    check("%s DOMContentLoaded" % tag, "DOMContentLoaded" in evs, evs)
    check("%s window load" % tag, "load" in evs, evs)
    check("%s pageshow" % tag, "pageshow" in evs, evs)
    check(
        "%s readystatechange has interactive" % tag,
        "interactive" in rsc_states,
        rsc_states,
    )
    check(
        "%s readystatechange has complete" % tag,
        "complete" in rsc_states,
        rsc_states,
    )
    check("%s final readyState complete" % tag, rss.get("load") == "complete", rss)
    dcl_end = (nav or {}).get("domContentLoadedEventEnd")
    load_end = (nav or {}).get("loadEventEnd")
    ntype = (nav or {}).get("type")
    check(
        "%s navigation timing DCL>0" % tag,
        dcl_end not in (None, 0),
        dcl_end,
    )
    check(
        "%s navigation timing load>0" % tag,
        load_end not in (None, 0),
        load_end,
    )
    check("%s navigation type=navigate" % tag, ntype == "navigate", ntype)
    check(
        "%s BiDi navigationStarted" % tag,
        "browsingContext.navigationStarted" in names,
        names,
    )
    check(
        "%s BiDi domContentLoaded" % tag,
        "browsingContext.domContentLoaded" in names,
        names,
    )
    check(
        "%s BiDi load" % tag,
        "browsingContext.load" in names,
        names,
    )


def read_page(ws, ctx):
    drain(ws, 0.6)
    life = js_json(ws, ctx, "window.__life||[]")
    nav = js_json(
        ws,
        ctx,
        "(performance.getEntriesByType('navigation')[0]"
        "?{type:performance.getEntriesByType('navigation')[0].type,"
        "dcl:performance.getEntriesByType('navigation')[0].domContentLoadedEventStart,"
        "domContentLoadedEventEnd:performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd,"
        "loadEventStart:performance.getEntriesByType('navigation')[0].loadEventStart,"
        "loadEventEnd:performance.getEntriesByType('navigation')[0].loadEventEnd,"
        "responseStart:performance.getEntriesByType('navigation')[0].responseStart,"
        "domInteractive:performance.getEntriesByType('navigation')[0].domInteractive}"
        ":null)",
    )
    rs = js(ws, ctx, "document.readyState")
    href = js(ws, ctx, "location.href")
    text = js(ws, ctx, "document.body && document.body.innerText")
    return life, nav, rs, href, text


def main():
    live, live_port = start_live()
    live_url = "http://127.0.0.1:%d/page" % live_port
    prof = tempfile.mkdtemp(prefix="ff-life-")
    err_path = os.path.join(prof, "ff.err")
    with open(os.path.join(prof, "user.js"), "w", encoding="utf-8") as f:
        f.write(
            "\n".join(
                [
                    'user_pref("toolkit.telemetry.enabled", false);',
                    'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
                    'user_pref("dom.security.https_first", false);',
                    'user_pref("dom.security.https_only_mode", false);',
                    'user_pref("security.sandbox.content.level", 0);',
                    'user_pref("remote.enabled", true);',
                    "",
                ]
            )
        )
    errf = open(err_path, "w", encoding="utf-8", errors="replace")
    env = os.environ.copy()
    env["HOME"] = prof
    proc = subprocess.Popen(
        [
            FF,
            "-headless",
            "--remote-debugging-port",
            str(PORT),
            "-profile",
            prof,
            "-no-remote",
            "about:blank",
        ],
        stdout=errf,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=os.path.dirname(os.path.abspath(FF)) or None,
    )
    try:
        if not wait_bidi(PORT):
            errf.flush()
            print(open(err_path, encoding="utf-8", errors="replace").read()[-2000:])
            return False
        ws = create_connection(
            "ws://127.0.0.1:%d/session" % PORT,
            suppress_origin=True,
            max_size=None,
        )
        cmd(ws, "session.new", {"capabilities": {}})
        cmd(
            ws,
            "session.subscribe",
            {
                "events": [
                    "browsingContext.navigationStarted",
                    "browsingContext.fragmentNavigated",
                    "browsingContext.domContentLoaded",
                    "browsingContext.load",
                    "browsingContext.navigationFailed",
                ]
            },
        )

        print("\n===== live HTTP control =====")
        uc0 = cmd(ws, "browser.createUserContext", {})["userContext"]
        ctx0 = cmd(ws, "browsingContext.create", {"type": "tab", "userContext": uc0})[
            "context"
        ]
        events.clear()
        cmd(
            ws,
            "browsingContext.navigate",
            {"context": ctx0, "url": live_url, "wait": "complete"},
        )
        life0, nav0, rs0, href0, text0 = read_page(ws, ctx0)
        print("  href=%s rs=%s text=%r live_hits=%s" % (href0, rs0, text0, Live.hits))
        assess("live", life0, nav0, bidi_names(ctx0))

        print("\n===== fake html via moz:context url+html =====")
        uc1 = cmd(ws, "browser.createUserContext", {})["userContext"]
        ctx1 = cmd(ws, "browsingContext.create", {"type": "tab", "userContext": uc1})[
            "context"
        ]
        events.clear()
        cmd(
            ws,
            "moz:context.setContextOverrides",
            {
                "userContexts": [uc1],
                "url": FAKE_URL,
                "html": PROBE_HTML,
            },
        )
        # Auto-nav from setContextOverrides; wait for load like a real page.
        deadline = time.time() + 15
        while time.time() < deadline:
            drain(ws, 0.3)
            if "browsingContext.load" in bidi_names(ctx1):
                break
        life1, nav1, rs1, href1, text1 = read_page(ws, ctx1)
        print("  href=%s rs=%s text=%r" % (href1, rs1, text1))
        assess("fake-autonav", life1, nav1, bidi_names(ctx1))

        print("\n===== fake html via browsingContext.navigate =====")
        uc2 = cmd(ws, "browser.createUserContext", {})["userContext"]
        ctx2 = cmd(ws, "browsingContext.create", {"type": "tab", "userContext": uc2})[
            "context"
        ]
        cmd(
            ws,
            "moz:context.setContextOverrides",
            {
                "userContexts": [uc2],
                "url": FAKE_URL,
                "html": PROBE_HTML,
            },
        )
        events.clear()
        cmd(
            ws,
            "browsingContext.navigate",
            {"context": ctx2, "url": FAKE_URL, "wait": "complete"},
        )
        life2, nav2, rs2, href2, text2 = read_page(ws, ctx2)
        print("  href=%s rs=%s text=%r" % (href2, rs2, text2))
        assess("fake-navigate", life2, nav2, bidi_names(ctx2))

        print("\n" + ("ALL PASSED" if ok else "SOME FAILED"))
        return ok
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            live.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
