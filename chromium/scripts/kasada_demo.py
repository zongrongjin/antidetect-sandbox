#!/usr/bin/env python3
"""Kasada demo (Chromium zzbrowser).

PASS only if POST /tl body contains "reload". Never print ct/h.
Needs this kernel's Context.setContextOverrides (url+html, not Fetch).
Do not Runtime.enable. Do not Fetch.enable *.

  pip install websocket-client
  KASADA_PROXY=http://user:pass@host:port \\
    python3 kasada_demo.py [--headed] /path/to/chrome

Default is headed (Kasada). Proxy from KASADA_PROXY or PROXY.
"""
import json
import os
import random
import string
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("PYTHONUTF8", "1")

from websocket import create_connection

HEADED = "--headed" in sys.argv or "--headless" not in sys.argv
args = [a for a in sys.argv[1:] if a not in ("--headed", "--headless")]
CHROME = args[0] if args else os.environ.get("CHROME", "chrome")
DBG = int(os.environ.get("KASADA_PORT", "9224"))
HOST = "arcteryx.com"
TARGET = os.environ.get(
    "KASADA_URL", "https://arcteryx.com/ca/en/shop/mens/rush-bib-pant-9904"
)
KP = "149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3"
PJS = "https://%s/%s/p.js" % (HOST, KP)
WAIT_S = int(os.environ.get("KASADA_WAIT", "45"))

_id = 0
events = []


def letters(n=6):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def parse_proxy(raw):
    rest = (raw or "").strip()
    if not rest:
        raise SystemExit("export KASADA_PROXY=http://user:pass@host:port")
    scheme = "http"
    if "://" in rest:
        scheme, rest = rest.split("://", 1)
    user = pwd = ""
    if "@" in rest:
        cred, rest = rest.rsplit("@", 1)
        if ":" in cred:
            user, pwd = cred.split(":", 1)
        else:
            user = cred
    if not rest or ":" not in rest:
        raise SystemExit("proxy must be host:port")
    return scheme, rest, user, pwd


def proxy_host(raw):
    rest = (raw or "").split("://", 1)[-1]
    return rest.rsplit("@", 1)[-1]


def kasada_html():
    return (
        "<html><head><meta charset=\"utf-8\"/><title>"
        + TARGET
        + "</title></head><body><script>"
        "document.addEventListener(\"kpsdk-load\",function(){"
        "  window.KPSDK.configure([{protocol:\"https\",method:\"*\","
        "    domain:\"arcteryx.com\",path:\"/search\"}]);"
        "});"
        "function createKPSDK(){"
        "  var s=document.createElement(\"script\");"
        "  s.src=" + json.dumps(PJS) + ";"
        "  document.body.appendChild(s);"
        "}"
        "createKPSDK();"
        "</script>"
        "<button id=\"myButton\" onclick=\"createKPSDK()\">Click me</button>"
        "</body></html>"
    )


def cmd(ws, method, params=None, sess=None, timeout=40):
    global _id
    _id += 1
    mid = _id
    msg = {"id": mid, "method": method, "params": params or {}}
    if sess:
        msg["sessionId"] = sess
    ws.send(json.dumps(msg))
    deadline = time.time() + timeout
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise RuntimeError("timeout %s" % method)
        ws.settimeout(max(left, 0.15))
        r = json.loads(ws.recv())
        if r.get("method"):
            events.append(r)
            continue
        if r.get("id") == mid:
            if "error" in r:
                raise RuntimeError("%s: %s" % (method, r["error"]))
            return r.get("result", {})


def drain(ws, seconds=0.25):
    end = time.time() + seconds
    ws.settimeout(0.15)
    while time.time() < end:
        try:
            r = json.loads(ws.recv())
        except Exception:
            continue
        if r.get("method"):
            events.append(r)


def decode_body(raw):
    body = raw.get("body") or ""
    if raw.get("base64Encoded"):
        import base64
        return base64.b64decode(body).decode("utf-8", "replace")
    return body if isinstance(body, str) else ""


def chrome_fp():
    vendor = "Google Inc. (NVIDIA %s)" % letters()
    renderer = (
        "ANGLE (NVIDIA, NVIDIA GeForce RTX %s Direct3D11 vs_5_0 ps_5_0, D3D11)"
        % letters()
    )
    return {
        "userAgent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        ),
        "platform": "Win32",
        "uaPlatform": "Windows",
        "acceptLanguages": "en-US,en;q=0.9",
        "locale": "en-US",
        "timezone": "America/New_York",
        "hardwareConcurrency": 8,
        "screenWidth": 1400,
        "screenHeight": 1000,
        "colorDepth": 24,
        "mobile": False,
        "webglVendor": vendor,
        "webglRenderer": renderer,
        "webRTC": 0,
    }


def main():
    raw_proxy = os.environ.get("KASADA_PROXY") or os.environ.get("PROXY") or ""
    scheme, hostport, user, pwd = parse_proxy(raw_proxy)
    print("proxy=%s headed=%s target=%s" % (proxy_host(raw_proxy), int(HEADED), TARGET))
    profile = tempfile.mkdtemp(prefix="kasada-cr-")
    chrome_args = [CHROME]
    if not HEADED:
        chrome_args.append("--headless=new")
    chrome_args += [
        "--no-sandbox",
        "--disable-gpu-sandbox",
        "--password-store=basic",
        "--no-first-run",
        "--disable-extensions",
        "--disable-features=ReduceAcceptLanguage",
        "--remote-allow-origins=*",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=%d" % DBG,
        "--user-data-dir=%s" % profile,
        "about:blank",
    ]
    proc = subprocess.Popen(
        chrome_args,
        cwd=os.path.dirname(os.path.abspath(CHROME)) or None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        bws = None
        for _ in range(50):
            try:
                v = json.load(
                    urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/version" % DBG, timeout=1
                    )
                )
                bws = v["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.3)
        if not bws:
            raise RuntimeError("chrome debug port not ready")
        ws = create_connection(bws, max_size=None)
        ctx = cmd(ws, "Target.createBrowserContext")["browserContextId"]
        tgt = cmd(
            ws,
            "Target.createTarget",
            {"url": "about:blank", "browserContextId": ctx},
        )["targetId"]
        sess = cmd(
            ws, "Target.attachToTarget", {"targetId": tgt, "flatten": True}
        )["sessionId"]
        cmd(ws, "Network.enable", {}, sess=sess)
        cmd(ws, "Page.enable", {}, sess=sess)
        vid = str(uuid.uuid4())
        cmd(
            ws,
            "Context.setContextOverrides",
            {
                "fingerprint": json.dumps(chrome_fp()),
                "proxy": {
                    "endpoint": "%s://%s" % (scheme, hostport),
                    "username": user,
                    "password": pwd,
                },
                "cookies": [
                    {
                        "name": "enableClickAndCollectCA",
                        "value": "true",
                        "domain": ".arcteryx.com",
                        "path": "/",
                        "secure": True,
                    },
                    {
                        "name": "enableClickAndCollectUS",
                        "value": "true",
                        "domain": ".arcteryx.com",
                        "path": "/",
                        "secure": True,
                    },
                    {
                        "name": "_vid",
                        "value": vid,
                        "domain": ".arcteryx.com",
                        "path": "/",
                        "secure": True,
                    },
                ],
                "cache": {
                    "dir": "",
                    "map": "{}",
                    "rules": json.dumps(
                        {
                            "blocks": [
                                "*" + KP + "/r*",
                                "*cdndex.io*",
                                "*://reporting.cdndex.io/*",
                            ]
                        }
                    ),
                },
                "url": TARGET,
                "html": kasada_html(),
            },
            sess=sess,
            timeout=40,
        )
        pjs = None
        tl_status = None
        tl_rid = None
        tl_text = ""
        seen = set()
        finished = set()
        body_tries = 0
        deadline = time.time() + WAIT_S
        while time.time() < deadline and not tl_text:
            drain(ws, 0.2)
            for e in events:
                method = e.get("method")
                p = e.get("params") or {}
                rid = p.get("requestId")
                if method == "Network.loadingFinished" and rid:
                    finished.add(rid)
                    continue
                if method != "Network.responseReceived":
                    continue
                if not rid or rid in seen:
                    continue
                resp = p.get("response") or {}
                u = resp.get("url") or ""
                st = resp.get("status")
                if u.endswith("/p.js") and KP in u:
                    pjs = st
                    seen.add(rid)
                if "/tl" in u and KP in u:
                    seen.add(rid)
                    tl_status = st
                    tl_rid = rid
            if tl_rid and tl_rid in finished and not tl_text and body_tries < 8:
                body_tries += 1
                try:
                    raw = cmd(
                        ws,
                        "Network.getResponseBody",
                        {"requestId": tl_rid},
                        sess=sess,
                        timeout=10,
                    )
                    tl_text = decode_body(raw)
                except Exception as ex:
                    print("getResponseBody_err=%s" % type(ex).__name__)
                    time.sleep(0.3)
        has_reload = "reload" in (tl_text or "")
        print(
            "kasada pjs=%s tl_status=%s body_len=%s reload=%s"
            % (pjs, tl_status, len(tl_text or ""), has_reload)
        )
        if has_reload:
            print("KASADA PASS")
            return 0
        print("KASADA FAIL")
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
