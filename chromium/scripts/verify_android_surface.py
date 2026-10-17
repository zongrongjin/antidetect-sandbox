#!/usr/bin/env python3
"""Verify CSS resolution / plugins / keyboard / connection using profile.py.

用法: python3 scripts/verify_android_surface.py <chrome路径>
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import http.server
import socketserver
import tempfile
import subprocess
import urllib.request

from websocket import create_connection

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fp_profile import Profile  # noqa: E402

CHROME = sys.argv[1] if len(sys.argv) > 1 else "out/Default/chrome"
PORT, DBG = 8141, 9333

PROBE_JS = r"""JSON.stringify((function(){
  var mm = function(q){ try { return matchMedia(q).matches; } catch(e){ return null; } };
  var dpr = window.devicePixelRatio;
  var plugins = [];
  try { for (var i=0;i<navigator.plugins.length;i++) plugins.push(navigator.plugins[i].name); } catch(e) {}
  var mimes = [];
  try { for (var i=0;i<navigator.mimeTypes.length;i++) mimes.push(navigator.mimeTypes[i].type); } catch(e) {}
  var kbIn = ('keyboard' in navigator);
  var kb = navigator.keyboard;
  var connIn = ('connection' in navigator);
  var conn = navigator.connection;
  return {
    dpr: dpr,
    res_dppx: mm('(resolution: ' + dpr + 'dppx)'),
    webkit_dpr: mm('(-webkit-device-pixel-ratio: ' + dpr + ')'),
    ua: navigator.userAgent,
    uaPlatform: (navigator.userAgentData && navigator.userAgentData.platform) || null,
    mobile: (navigator.userAgentData && navigator.userAgentData.mobile) || null,
    plugins: plugins,
    pluginLen: navigator.plugins.length,
    pluginProto: Object.prototype.toString.call(navigator.plugins),
    mimes: mimes,
    mimeLen: navigator.mimeTypes.length,
    pdfViewerEnabled: navigator.pdfViewerEnabled,
    keyboardIn: kbIn,
    keyboardType: (kb === null) ? 'null' : (kb === undefined ? 'undefined' : typeof kb),
    connectionIn: connIn,
    connectionType: (conn === null) ? 'null' : (conn === undefined ? 'undefined' : typeof conn),
    effectiveType: conn && conn.effectiveType,
    downlink: conn && conn.downlink,
    rtt: conn && conn.rtt,
    saveData: conn && conn.saveData
  };
})())"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<!doctype html><title>fp</title>ok")

    def log_message(self, *a):
        pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve():
    with _Server(("127.0.0.1", PORT), H) as httpd:
        httpd.serve_forever()


_id = 0


def cmd(ws, method, params=None, sess=None):
    global _id
    _id += 1
    mid = _id
    m = {"id": mid, "method": method, "params": params or {}}
    if sess:
        m["sessionId"] = sess
    ws.send(json.dumps(m))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            if "error" in r:
                raise RuntimeError("%s: %s" % (method, r["error"]))
            return r.get("result", {})


def probe(ws, fp, tag):
    ctx = cmd(ws, "Target.createBrowserContext")["browserContextId"]
    tgt = cmd(ws, "Target.createTarget",
              {"url": "about:blank", "browserContextId": ctx})["targetId"]
    sess = cmd(ws, "Target.attachToTarget",
               {"targetId": tgt, "flatten": True})["sessionId"]
    cmd(ws, "Fingerprint.setContextOverrides",
        {"fingerprint": json.dumps(fp)}, sess=sess)
    cmd(ws, "Page.enable", sess=sess)
    cmd(ws, "Page.navigate", {"url": "http://127.0.0.1:%d/" % PORT}, sess=sess)
    time.sleep(0.8)
    r = json.loads(cmd(ws, "Runtime.evaluate",
                       {"expression": PROBE_JS, "returnByValue": True},
                       sess=sess)["result"]["value"])
    cmd(ws, "Target.closeTarget", {"targetId": tgt})
    print("\n===== %s =====" % tag)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return r


def chk(ok, label, got, want):
    m = got == want
    print("  %-40s %s  want=%r got=%r" % (label, "OK" if m else "FAIL", want, got))
    return ok and m


def android_fp():
    p = Profile("chrome", "us", os="android", version="151")
    fp = p.fingerprint.to_cdp()
    fp.pop("connection", None)
    fp.pop("keyboard", None)
    return fp


def desktop_fp():
    p = Profile("chrome", "us", os="windows", version="151")
    fp = p.fingerprint.to_cdp()
    fp.pop("plugins", None)
    fp.pop("mimeTypes", None)
    fp.pop("pdfViewerEnabled", None)
    fp.pop("keyboard", None)
    fp.pop("connection", None)
    return fp


def main():
    threading.Thread(target=serve, daemon=True).start()
    user = tempfile.mkdtemp(prefix="fp-verify-")
    proc = subprocess.Popen(
        [
            CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage", "--remote-allow-origins=*",
            "--remote-debugging-port=%d" % DBG,
            "--user-data-dir=%s" % user, "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws = None
    last_err = None
    for _ in range(40):
        try:
            version = json.load(urllib.request.urlopen(
                "http://127.0.0.1:%d/json/version" % DBG, timeout=1))
            ws = create_connection(version["webSocketDebuggerUrl"])
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    if ws is None:
        raise RuntimeError("chrome debug port not ready: %r" % last_err)
    ver = cmd(ws, "Browser.getVersion")
    print("browser", ver.get("product"), ver.get("userAgent", "")[:80])

    ok = True
    d = probe(ws, desktop_fp(), "desktop Profile(chrome,us)")
    ok = chk(ok, "desktop dpr==css resolution", d["res_dppx"], True)
    ok = chk(ok, "desktop pluginLen==5", d["pluginLen"], 5)
    ok = chk(ok, "desktop pdfViewerEnabled", d["pdfViewerEnabled"], True)
    ok = chk(ok, "desktop keyboard present", d["keyboardType"] in ("object", "function"), True)
    ok = chk(ok, "desktop connection present", d["connectionType"], "object")

    a = probe(ws, android_fp(), "android Profile(chrome,us,os=android)")
    ok = chk(ok, "android dpr==css resolution", a["res_dppx"], True)
    ok = chk(ok, "android pluginLen==0", a["pluginLen"], 0)
    ok = chk(ok, "android mimeLen==0", a["mimeLen"], 0)
    ok = chk(ok, "android pdfViewerEnabled", a["pdfViewerEnabled"], False)
    ok = chk(ok, "android keyboard present", a["keyboardType"] in ("object", "function"), True)
    ok = chk(ok, "android connection present", a["connectionType"], "object")
    ok = chk(ok, "android uaPlatform", a["uaPlatform"], "Android")

    ws.close()
    proc.terminate()
    print("\nRESULT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
