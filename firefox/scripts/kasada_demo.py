#!/usr/bin/env python3
"""Kasada demo (Firefox zzbrowser).

PASS only if POST /tl body contains "reload". Never print ct/h.
Needs this kernel's moz:context.setContextOverrides (url+html).
Do not Runtime.enable.

  pip install websocket-client
  KASADA_PROXY=http://user:pass@host:port DISPLAY=:97 \\
    python3 kasada_demo.py /path/to/firefox
"""
import json
import os
import random
import string
import subprocess
import sys
import tempfile
import time
import uuid

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("MOZ_DISABLE_CONTENT_SANDBOX", "1")
os.environ.setdefault("MOZ_DISABLE_GMP_SANDBOX", "1")
os.environ.setdefault("PYTHONUTF8", "1")

from websocket import create_connection

FF = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "FIREFOX", "/root/ff/firefox-152.0.5/obj-release/dist/bin/firefox"
)
PORT = int(os.environ.get("FF_BIDI_PORT", os.environ.get("KASADA_PORT", "19225")))
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
    if "://" in rest:
        _, rest = rest.split("://", 1)
    user = pwd = ""
    if "@" in rest:
        cred, rest = rest.rsplit("@", 1)
        if ":" in cred:
            user, pwd = cred.split(":", 1)
        else:
            user = cred
    if not rest or ":" not in rest:
        raise SystemExit("proxy must be host:port")
    return rest, user, pwd


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


def firefox_fp():
    vendor = "Google Inc. (NVIDIA %s)" % letters()
    renderer = (
        "ANGLE (NVIDIA, NVIDIA GeForce RTX %s Direct3D11 vs_5_0 ps_5_0, D3D11)"
        % letters()
    )
    return {
        "userAgent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
            "Gecko/20100101 Firefox/152.0"
        ),
        "appVersion": (
            "5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
        ),
        "platform": "Win32",
        "oscpu": "Windows NT 10.0; Win64; x64",
        "acceptLanguages": "en-US,en;q=0.5",
        "locale": "en-US",
        "timezone": "America/New_York",
        "hardwareConcurrency": 8,
        "screenWidth": 1400,
        "screenHeight": 1000,
        "availWidth": 1400,
        "availHeight": 960,
        "colorDepth": 24,
        "webglVendor": vendor,
        "webglRenderer": renderer,
        "webRTC": 0,
    }


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
        ws.settimeout(max(left, 0.15))
        r = json.loads(ws.recv())
        if r.get("type") == "event":
            events.append(r)
            continue
        if r.get("id") == mid:
            if r.get("type") == "error":
                raise RuntimeError("%s: %s" % (method, r.get("message")))
            return r.get("result", {})


def drain(ws, seconds=0.3):
    end = time.time() + seconds
    ws.settimeout(0.15)
    while time.time() < end:
        try:
            r = json.loads(ws.recv())
        except Exception:
            continue
        if r.get("type") == "event":
            events.append(r)


def event_url(e):
    p = e.get("params") or {}
    req = p.get("request") or {}
    if isinstance(req, dict) and req.get("url"):
        return req.get("url")
    resp = p.get("response") or {}
    return resp.get("url") or p.get("url") or ""


def event_status(e):
    p = e.get("params") or {}
    resp = p.get("response") or {}
    return resp.get("status")


def event_req_id(e):
    p = e.get("params") or {}
    req = p.get("request") or {}
    if isinstance(req, dict):
        return req.get("request") or req.get("requestId")
    return None


def get_body(ws, request_id):
    try:
        r = cmd(
            ws,
            "network.getData",
            {"request": request_id, "dataType": "response"},
            timeout=10,
        )
        b = r.get("bytes") or {}
        val = b.get("value") or ""
        if b.get("type") == "base64":
            import base64
            return base64.b64decode(val).decode("utf-8", "replace")
        return val
    except Exception:
        return ""


def wait_bidi(port, tries=50):
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
            time.sleep(0.4)
    return False


def main():
    raw_proxy = os.environ.get("KASADA_PROXY") or os.environ.get("PROXY") or ""
    hostport, user, pwd = parse_proxy(raw_proxy)
    print("proxy=%s target=%s" % (proxy_host(raw_proxy), TARGET))
    prof = tempfile.mkdtemp(prefix="kasada-ff-")
    with open(os.path.join(prof, "user.js"), "w", encoding="utf-8") as f:
        f.write(
            "\n".join(
                [
                    'user_pref("toolkit.telemetry.enabled", false);',
                    'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
                    'user_pref("dom.security.https_first", false);',
                    'user_pref("security.sandbox.content.level", 0);',
                    'user_pref("webgl.force-enabled", true);',
                    'user_pref("remote.enabled", true);',
                    "",
                ]
            )
        )
    errf = open(os.path.join(prof, "ff.err"), "w", encoding="utf-8", errors="replace")
    env = os.environ.copy()
    env["HOME"] = prof
    env.setdefault("DISPLAY", ":97")
    proc = subprocess.Popen(
        [
            FF,
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
            print("firefox 未就绪")
            return 1
        ws = create_connection(
            "ws://127.0.0.1:%d/session" % PORT,
            suppress_origin=True,
            max_size=None,
        )
        cmd(ws, "session.new", {"capabilities": {}})
        cmd(
            ws,
            "network.addDataCollector",
            {"dataTypes": ["response"], "maxEncodedDataSize": 200_000},
        )
        cmd(
            ws,
            "session.subscribe",
            {"events": ["network.responseCompleted"]},
        )
        uc = cmd(ws, "browser.createUserContext", {})["userContext"]
        cmd(
            ws,
            "browsingContext.create",
            {"type": "tab", "userContext": uc},
        )
        vid = str(uuid.uuid4())
        cmd(
            ws,
            "moz:context.setContextOverrides",
            {
                "userContexts": [uc],
                "fingerprint": json.dumps(firefox_fp()),
                "proxy": {
                    "endpoint": hostport,
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
            timeout=40,
        )
        pjs = None
        tl = None
        tl_text = ""
        deadline = time.time() + WAIT_S
        while time.time() < deadline:
            drain(ws, 0.3)
            for e in events:
                if e.get("method") != "network.responseCompleted":
                    continue
                u = event_url(e)
                st = event_status(e)
                if u.endswith("/p.js") and KP in u:
                    pjs = st
                if "/tl" in u and KP in u and not tl:
                    rid = event_req_id(e)
                    tl = st
                    tl_text = get_body(ws, rid) if rid else ""
            if tl is not None:
                break
        has_reload = "reload" in (tl_text or "")
        print(
            "kasada pjs=%s tl_status=%s body_len=%s reload=%s"
            % (pjs, tl, len(tl_text or ""), has_reload)
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
