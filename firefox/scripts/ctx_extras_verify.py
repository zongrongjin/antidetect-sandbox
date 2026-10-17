# -*- coding: utf-8 -*-
"""Verify moz:context extras on a compiled Firefox (raw BiDi, no framework).

  1) fingerprint via moz:context (platform + webdriver)
  2) url+html in-memory homepage
  3) cookies on that homepage
  4) cache HIT (no network)
  5) cache block
  6) per-context HTTP proxy
  7) BiDi click isTrusted=true; page JS click/dispatch/new Event stay false

Usage: python3 ctx_extras_verify.py <firefox-bin>
Exit 0 = all passed.
"""
import json
import os
import shutil
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
os.environ.setdefault("MOZ_DISABLE_GMP_SANDBOX", "1")

from websocket import create_connection

FF = sys.argv[1] if len(sys.argv) > 1 else "/root/ff/firefox-152.0.5/obj-release/dist/bin/firefox"
PORT = int(os.environ.get("FF_BIDI_PORT", "19223"))
HIT_MARKER = "CACHE-HIT-BODY-42"
HTML_MARKER = "FAKE-HTML-OK"
PROXY_MARKER = "PROXY-HIT-OK"
COOKIE_NAME = "zzck"
COOKIE_VAL = "ctxok"

_id = 0
ok = True


def check(name, cond, got=""):
    global ok
    print("  %-48s %s  %s" % (name, "OK" if cond else "FAIL", got))
    if not cond:
        ok = False


def cmd(ws, method, params=None, timeout=None):
    global _id
    _id += 1
    mid = _id
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    deadline = time.time() + (timeout or 45)
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise RuntimeError("timeout %s" % method)
        ws.settimeout(max(left, 0.1))
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            if r.get("type") == "error":
                raise RuntimeError("%s: %s" % (method, r.get("message")))
            return r.get("result", {})


def js(ws, ctx, expr):
    r = cmd(
        ws,
        "script.evaluate",
        {
            "expression": expr,
            "target": {"context": ctx},
            "awaitPromise": False,
        },
    )
    val = r.get("result", {})
    t = val.get("type")
    if t in ("string", "number", "boolean"):
        return val.get("value")
    if t in ("null", "undefined"):
        return None
    if t == "object" and "value" in val:
        return val
    return val


def js_json(ws, ctx, expr):
    raw = js(ws, ctx, "JSON.stringify(%s)" % expr)
    if not raw:
        return None
    return json.loads(raw)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class LiveHandler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        LiveHandler.hits.append(self.path)
        if self.path.startswith("/block"):
            body = b"LIVE-BLOCK-SHOULD-NOT-SEE"
        else:
            body = b"LIVE-MISS-BODY"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(b"<html><body>" + body + b"</body></html>")


class ProxyHandler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        ProxyHandler.seen.append(self.path)
        body = ("<html><body>%s</body></html>" % PROXY_MARKER).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self):
        ProxyHandler.seen.append("CONNECT " + self.path)
        self.send_error(405)


def start_httpd(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, httpd.server_address[1]


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


def new_ctx(ws, overrides):
    uc = cmd(ws, "browser.createUserContext", {})["userContext"]
    ctx = cmd(ws, "browsingContext.create", {"type": "tab", "userContext": uc})[
        "context"
    ]
    params = dict(overrides)
    params["userContexts"] = [uc]
    cmd(ws, "moz:context.setContextOverrides", params)
    return uc, ctx


def nav(ws, ctx, url):
    cmd(
        ws,
        "browsingContext.navigate",
        {"context": ctx, "url": url, "wait": "complete"},
        timeout=40,
    )


def wait_body(ws, ctx, needle, tries=40):
    last = None
    for _ in range(tries):
        try:
            body = js(ws, ctx, "document.body && document.body.innerText")
            href = js(ws, ctx, "location.href")
            last = (href, body)
            if body and needle in str(body):
                return body, href
        except Exception as e:
            last = str(e)
        time.sleep(0.25)
    return None, last


def main():
    global ok
    prof = tempfile.mkdtemp(prefix="ff-ctxv-")
    cache_dir = tempfile.mkdtemp(prefix="ff-cache-")
    err_path = os.path.join(prof, "ff.err")
    with open(os.path.join(prof, "user.js"), "w", encoding="utf-8") as f:
        f.write(
            "\n".join(
                [
                    'user_pref("toolkit.telemetry.enabled", false);',
                    'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
                    'user_pref("app.update.enabled", false);',
                    'user_pref("network.proxy.allow_hijacking_localhost", true);',
                    'user_pref("dom.security.https_first", false);',
                    'user_pref("dom.security.https_only_mode", false);',
                    'user_pref("security.sandbox.content.level", 0);',
                    'user_pref("remote.enabled", true);',
                    "",
                ]
            )
        )
    with open(os.path.join(cache_dir, "hit.html"), "w", encoding="utf-8") as f:
        f.write("<html><body>%s</body></html>" % HIT_MARKER)

    live, live_port = start_httpd(LiveHandler)
    proxy, proxy_port = start_httpd(ProxyHandler)
    hit_url = "http://zz-cache-hit.test/hit.html"
    block_url = "http://127.0.0.1:%d/block" % live_port
    html_url = "http://zz-html-probe.test/"
    proxy_url = "http://zz-proxy-probe.test/"

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
            print("firefox 未就绪:")
            print(open(err_path, encoding="utf-8", errors="replace").read()[-2000:])
            return False
        ws = create_connection(
            "ws://127.0.0.1:%d/session" % PORT,
            suppress_origin=True,
            max_size=None,
        )
        cmd(ws, "session.new", {"capabilities": {}})
        cmd(ws, "session.subscribe", {"events": ["browsingContext.load"]})

        print("\n===== moz:context fingerprint =====")
        uc, ctx = new_ctx(
            ws,
            {
                "fingerprint": json.dumps(
                    {
                        "platform": "Win32",
                        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
                    }
                )
            },
        )
        nav(ws, ctx, "about:blank")
        info = js_json(
            ws,
            ctx,
            "{plat:navigator.platform, ua:navigator.userAgent, wd:navigator.webdriver}",
        )
        check("moz:context 命令可调用", True)
        check("platform=Win32", info and info.get("plat") == "Win32", info)
        check("webdriver=false", info and info.get("wd") is False, info)

        print("\n===== url+html + cookies =====")
        _, ctx_h = new_ctx(
            ws,
            {
                "url": html_url,
                "html": (
                    "<!doctype html><html><body>"
                    + HTML_MARKER
                    + "<span id='c'></span>"
                    + "<script>document.getElementById('c').textContent=document.cookie;</script>"
                    + "</body></html>"
                ),
                "cookies": [
                    {
                        "name": COOKIE_NAME,
                        "value": COOKIE_VAL,
                        "domain": "zz-html-probe.test",
                        "path": "/",
                    }
                ],
            },
        )
        body, href = wait_body(ws, ctx_h, HTML_MARKER)
        if body is None:
            try:
                nav(ws, ctx_h, html_url)
                body, href = wait_body(ws, ctx_h, HTML_MARKER, tries=20)
            except Exception as e:
                check("html 导航", False, str(e)[:180])
                body, href = None, None
        check(
            "html 假首页 marker",
            bool(body) and HTML_MARKER in str(body),
            "href=%s body=%r"
            % (
                href[0] if isinstance(href, tuple) else href,
                str(body)[:120] if body else href,
            ),
        )
        cookie = None
        try:
            cookie = js(ws, ctx_h, "document.cookie")
        except Exception as e:
            cookie = str(e)
        expect_ck = "%s=%s" % (COOKIE_NAME, COOKIE_VAL)
        check(
            "cookies 写入 document.cookie",
            bool(cookie) and expect_ck in str(cookie),
            cookie,
        )

        print("\n===== cache HIT / block =====")
        LiveHandler.hits.clear()
        _, ctx_c = new_ctx(
            ws,
            {
                "cache": {
                    "dir": cache_dir,
                    "map": json.dumps(
                        {
                            hit_url: {
                                "file": "hit.html",
                                "status": 200,
                                "headers": {"Content-Type": "text/html"},
                            }
                        }
                    ),
                    "rules": json.dumps({"blocks": [block_url]}),
                }
            },
        )
        try:
            nav(ws, ctx_c, hit_url)
            hit_body = js(ws, ctx_c, "document.body && document.body.innerText")
        except Exception as e:
            hit_body = "NAV-ERR %s" % e
        check(
            "cache HIT 正文",
            isinstance(hit_body, str) and HIT_MARKER in hit_body,
            repr(hit_body)[:160] if hit_body is not None else None,
        )
        check(
            "cache HIT 未打到 live server",
            "/hit.html" not in LiveHandler.hits,
            LiveHandler.hits,
        )
        block_ok = False
        block_got = ""
        try:
            nav(ws, ctx_c, block_url)
            block_got = str(js(ws, ctx_c, "document.body && document.body.innerText"))
            block_ok = "LIVE-BLOCK-SHOULD-NOT-SEE" not in block_got
        except Exception as e:
            block_ok = True
            block_got = "nav-error %s" % e
        check("cache block 未出 live 正文", block_ok, repr(block_got)[:160])

        print("\n===== per-context proxy =====")
        ProxyHandler.seen.clear()
        _, ctx_p = new_ctx(
            ws,
            {
                "proxy": {
                    "endpoint": "127.0.0.1:%d" % proxy_port,
                    "username": "",
                    "password": "",
                }
            },
        )
        try:
            nav(ws, ctx_p, proxy_url)
            proxy_body = js(ws, ctx_p, "document.body && document.body.innerText")
        except Exception as e:
            proxy_body = "NAV-ERR %s" % e
        check(
            "proxy 拦截正文",
            isinstance(proxy_body, str) and PROXY_MARKER in proxy_body,
            "body=%r seen=%s" % (str(proxy_body)[:120], ProxyHandler.seen[:6]),
        )
        check(
            "proxy 服务收到请求",
            len(ProxyHandler.seen) > 0,
            ProxyHandler.seen[:6],
        )

        print("\n===== isTrusted =====")
        trust_html = (
            "data:text/html,"
            "<!doctype html><button id=b style='position:fixed;left:0;top:0;"
            "width:240px;height:240px'>x</button>"
            "<script>window.__ev=[];"
            "document.getElementById('b').addEventListener('click',function(e){"
            "window.__ev.push({trusted:e.isTrusted,syn:e.isSynthesized});});"
            "</script>"
        )
        _, ctx_t = new_ctx(ws, {})
        nav(ws, ctx_t, trust_html)
        js(ws, ctx_t, "window.__ev=[]")
        cmd(
            ws,
            "input.performActions",
            {
                "context": ctx_t,
                "actions": [
                    {
                        "type": "pointer",
                        "id": "mouse",
                        "parameters": {"pointerType": "mouse"},
                        "actions": [
                            {"type": "pointerMove", "x": 40, "y": 40, "duration": 0},
                            {"type": "pointerDown", "button": 0},
                            {"type": "pointerUp", "button": 0},
                        ],
                    }
                ],
            },
        )
        time.sleep(0.4)
        bidi_ev = js_json(ws, ctx_t, "window.__ev")
        js(ws, ctx_t, "window.__ev=[]")
        js(ws, ctx_t, "document.getElementById('b').click()")
        click_ev = js_json(ws, ctx_t, "window.__ev")
        js(ws, ctx_t, "window.__ev=[]")
        js(
            ws,
            ctx_t,
            "document.getElementById('b').dispatchEvent("
            "new MouseEvent('click',{bubbles:true}))",
        )
        disp_ev = js_json(ws, ctx_t, "window.__ev")
        ctor_trusted = js(ws, ctx_t, "(new Event('x')).isTrusted")
        bidi_t = bidi_ev[0]["trusted"] if bidi_ev else None
        bidi_s = bidi_ev[0].get("syn") if bidi_ev else None
        click_t = click_ev[0]["trusted"] if click_ev else None
        disp_t = disp_ev[0]["trusted"] if disp_ev else None
        check(
            "BiDi 点击 isTrusted=true",
            bidi_t is True,
            "ev=%s syn=%s" % (bidi_ev, bidi_s),
        )
        if bidi_s is not None:
            check("BiDi 点击 isSynthesized=false", bidi_s is False, bidi_s)
        check("el.click() isTrusted=false", click_t is False, click_ev)
        check("dispatchEvent isTrusted=false", disp_t is False, disp_ev)
        check("new Event isTrusted=false", ctor_trusted is False, ctor_trusted)

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
        try:
            proxy.shutdown()
        except Exception:
            pass
        shutil.rmtree(prof, ignore_errors=True)
        shutil.rmtree(cache_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
