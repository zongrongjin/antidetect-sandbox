# -*- coding: utf-8 -*-
"""Verify plugins / pdfViewerEnabled / connection / keyboard using BiDi.

CSS dpr already rides overrideDPPX from fp_all; this checks android-surface.

用法: python3 scripts/verify_android_surface.py <firefox>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

from websocket import create_connection  # noqa: E402

FF = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "FIREFOX_BIN", "firefox"
)
PORT = 9224

PROBE_JS = r"""JSON.stringify((function(){
  var mm = function(q){ try { return matchMedia(q).matches; } catch(e){ return null; } };
  var dpr = window.devicePixelRatio;
  var plugins = [];
  try { for (var i=0;i<navigator.plugins.length;i++) plugins.push(navigator.plugins[i].name); } catch(e) {}
  var mimes = [];
  try { for (var i=0;i<navigator.mimeTypes.length;i++) mimes.push(navigator.mimeTypes[i].type); } catch(e) {}
  var kbIn = ('keyboard' in navigator);
  var connIn = ('connection' in navigator);
  var conn = navigator.connection;
  return {
    dpr: dpr,
    res_dppx: mm('(resolution: ' + dpr + 'dppx)'),
    ua: navigator.userAgent,
    platform: navigator.platform,
    plugins: plugins,
    pluginLen: navigator.plugins.length,
    mimes: mimes,
    mimeLen: navigator.mimeTypes.length,
    pdfViewerEnabled: navigator.pdfViewerEnabled,
    keyboardIn: kbIn,
    connectionIn: connIn,
    connectionType: conn && conn.type
  };
})())"""

_id = 0


def cmd(ws, method, params=None):
    global _id
    _id += 1
    mid = _id
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            if r.get("type") == "error":
                raise RuntimeError("%s: %s" % (method, r.get("message")))
            return r.get("result", {})


def android_fp():
    return {
        "userAgent": (
            "Mozilla/5.0 (Android 14; Mobile; rv:152.0) Gecko/152.0 Firefox/152.0"
        ),
        "platform": "Linux armv81",
        "oscpu": "Linux armv81",
        "appVersion": "5.0 (Android 14)",
        "dpr": 2.625,
        "maxTouchPoints": 5,
        "plugins": [],
        "mimeTypes": [],
        "pdfViewerEnabled": True,
        "keyboard": False,
        "connection": {"effectiveType": "4g", "type": "wifi"},
    }


def desktop_fp():
    return {
        "userAgent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
            "Gecko/20100101 Firefox/152.0"
        ),
        "platform": "Win32",
        "oscpu": "Windows NT 10.0; Win64; x64",
        "appVersion": "5.0 (Windows)",
        "dpr": 1,
        "maxTouchPoints": 0,
    }


def probe(ws, fp, tag):
    uc = cmd(ws, "browser.createUserContext", {})["userContext"]
    cmd(
        ws,
        "moz:fingerprint.setContextOverrides",
        {"fingerprint": json.dumps(fp), "userContexts": [uc]},
    )
    ctx = cmd(ws, "browsingContext.create", {"type": "tab", "userContext": uc})[
        "context"
    ]
    cmd(
        ws,
        "browsingContext.navigate",
        {"context": ctx, "url": "about:blank", "wait": "complete"},
    )
    r = cmd(
        ws,
        "script.evaluate",
        {
            "expression": PROBE_JS,
            "target": {"context": ctx},
            "awaitPromise": False,
        },
    )
    data = json.loads(r["result"]["value"])
    print("\n===== %s =====" % tag)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def chk(ok, label, got, want):
    match = got == want
    print("  %-42s %s  want=%r got=%r" % (label, "OK" if match else "FAIL", want, got))
    return ok and match


def main():
    prof = tempfile.mkdtemp(prefix="ff-android-surface-")
    errf = open(os.path.join(prof, "ff.err"), "w", encoding="utf-8", errors="replace")
    args = [
        FF,
        "-headless",
        "--remote-debugging-port",
        str(PORT),
        "-profile",
        prof,
        "-no-remote",
        "about:blank",
    ]
    proc = subprocess.Popen(args, stdout=errf, stderr=subprocess.STDOUT)
    ws = None
    try:
        for _ in range(40):
            time.sleep(1)
            try:
                w = create_connection(
                    "ws://127.0.0.1:%d/session" % PORT,
                    suppress_origin=True,
                    timeout=5,
                )
                w.close()
                ws = create_connection(
                    "ws://127.0.0.1:%d/session" % PORT,
                    suppress_origin=True,
                    max_size=None,
                )
                break
            except Exception:
                pass
        if ws is None:
            errf.flush()
            print("firefox not ready")
            print(open(os.path.join(prof, "ff.err"), encoding="utf-8", errors="replace").read()[-1500:])
            return 1
        ws.settimeout(60)
        cmd(ws, "session.new", {"capabilities": {}})
        cmd(ws, "session.subscribe", {"events": ["browsingContext.load"]})

        ok = True
        d = probe(ws, desktop_fp(), "desktop Win32")
        ok = chk(ok, "desktop pluginLen==5", d["pluginLen"], 5)
        ok = chk(ok, "desktop mimeLen==2", d["mimeLen"], 2)
        ok = chk(ok, "desktop pdfViewerEnabled", d["pdfViewerEnabled"], True)
        ok = chk(ok, "desktop keyboard absent", d["keyboardIn"], False)
        ok = chk(ok, "desktop connection absent", d["connectionIn"], False)
        ok = chk(ok, "desktop dpr==css resolution", d["res_dppx"], True)

        a = probe(ws, android_fp(), "android Firefox")
        ok = chk(ok, "android pluginLen==0", a["pluginLen"], 0)
        ok = chk(ok, "android mimeLen==0", a["mimeLen"], 0)
        ok = chk(ok, "android pdfViewerEnabled", a["pdfViewerEnabled"], True)
        ok = chk(ok, "android keyboard absent", a["keyboardIn"], False)
        ok = chk(ok, "android connection present", a["connectionIn"], True)
        ok = chk(ok, "android connection.type wifi", a["connectionType"], "wifi")
        ok = chk(ok, "android dpr==css resolution", a["res_dppx"], True)

        print("\nRESULT", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main() or 0)
