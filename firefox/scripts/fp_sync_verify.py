# -*- coding: utf-8 -*-
"""Firefox 三处移植点独立验证（原始 BiDi，不依赖 browser_controller / 外部检测站）：
  1) navigator.languages 剥 q       —— 传 fr-FR,fr;q=0.9,en;q=0.8 应得 [fr-FR,fr,en]
  2) screen.availHeight != height   —— Windows 画像应扣 40px 任务栏
  3) screen.colorDepth 覆盖         —— 传 30 应回读 30
另做跨 userContext 隔离：ctxA(Win) 与 ctxB(Mac) 的 avail 推导互不串。
退出码 0=全通过 / 1=有失败。用法: python ff_verify.py <firefox.exe>
"""
import sys, time, json, os, subprocess, shutil, tempfile
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"): os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"
from websocket import create_connection

FF = sys.argv[1] if len(sys.argv) > 1 else r"E:\ff\obj-release\dist\bin\firefox.exe"
PORT = 9223

_id = 0
def cmd(ws, method, params):
    global _id; _id += 1; mid = _id
    ws.send(json.dumps({"id": mid, "method": method, "params": params}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            if r.get("type") == "error":
                raise RuntimeError("%s: %s" % (method, r.get("message")))
            return r.get("result", {})

def main():
    if os.name == "nt":
        subprocess.run(["taskkill", "/f", "/im", "firefox.exe"], capture_output=True)
        time.sleep(2)
    prof = tempfile.mkdtemp(prefix="ffv-")
    errf = open(os.path.join(prof, "ff.err"), "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [FF, "-headless", "--remote-debugging-port", str(PORT),
         "-profile", prof, "-no-remote", "about:blank"],
        stdout=errf, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(45):
            time.sleep(2)
            try:
                w = create_connection("ws://127.0.0.1:%d/session" % PORT,
                                      suppress_origin=True, timeout=5)
                w.close(); ready = True; break
            except Exception:
                pass
        if not ready:
            errf.flush()
            print("firefox 未就绪，stderr tail:")
            print(open(os.path.join(prof, "ff.err"), encoding="utf-8", errors="replace").read()[-1500:])
            return False

        ws = create_connection("ws://127.0.0.1:%d/session" % PORT,
                               suppress_origin=True, max_size=None)
        ws.settimeout(60)
        cmd(ws, "session.new", {"capabilities": {}})
        cmd(ws, "session.subscribe", {"events": ["browsingContext.load"]})

        def probe(fp):
            """建一个 userContext + tab，下发指纹，回读三处属性。"""
            uc = cmd(ws, "browser.createUserContext", {})["userContext"]
            if fp is not None:
                try:
                    cmd(ws, "moz:context.setContextOverrides",
                        {"fingerprint": json.dumps(fp), "userContexts": [uc]})
                except Exception:
                    cmd(ws, "moz:fingerprint.setContextOverrides",
                        {"fingerprint": json.dumps(fp), "userContexts": [uc]})
            ctx = cmd(ws, "browsingContext.create",
                      {"type": "tab", "userContext": uc})["context"]
            cmd(ws, "browsingContext.navigate",
                {"context": ctx, "url": "about:blank", "wait": "complete"})
            js = ("JSON.stringify({langs:navigator.languages,"
                  "w:screen.width,h:screen.height,aw:screen.availWidth,"
                  "ah:screen.availHeight,cd:screen.colorDepth,pd:screen.pixelDepth,"
                  "plat:navigator.platform})")
            r = cmd(ws, "script.evaluate",
                    {"expression": js, "target": {"context": ctx},
                     "awaitPromise": False})
            return json.loads(r["result"]["value"])

        FP_WIN = {"platform": "Win32",
                  "acceptLanguages": "fr-FR,fr;q=0.9,en;q=0.8",
                  "screenWidth": 1920, "screenHeight": 1080, "colorDepth": 30}
        FP_MAC = {"platform": "MacIntel",
                  "acceptLanguages": "ja-JP,ja",
                  "screenWidth": 2560, "screenHeight": 1440, "colorDepth": 24}

        nat = probe(None)
        win = probe(FP_WIN)
        mac = probe(FP_MAC)

        ok = True
        def check(name, cond, got):
            nonlocal ok
            print("  %-42s %s  %s" % (name, "OK" if cond else "FAIL", got))
            if not cond: ok = False

        print("\n===== native(无指纹) 基线 =====")
        print("  langs=%s screen=%sx%s avail=%sx%s cd=%s" %
              (nat["langs"], nat["w"], nat["h"], nat["aw"], nat["ah"], nat["cd"]))

        print("\n===== ctxWin (fr-FR / 1920x1080 / colorDepth=30) =====")
        check("languages 剥 q 值", win["langs"] == ["fr-FR", "fr", "en"], win["langs"])
        check("screen 尺寸覆盖", (win["w"], win["h"]) == (1920, 1080), (win["w"], win["h"]))
        check("availHeight != height (扣任务栏)",
              win["ah"] != win["h"] and win["ah"] == 1040, "%sx%s" % (win["aw"], win["ah"]))
        check("colorDepth 覆盖=30", win["cd"] == 30, win["cd"])
        check("pixelDepth 跟随=30", win["pd"] == 30, win["pd"])

        print("\n===== ctxMac (ja-JP / 2560x1440 / macOS 菜单栏) =====")
        check("languages(无 q 原样)", mac["langs"] == ["ja-JP", "ja"], mac["langs"])
        check("availHeight 扣菜单栏(25)",
              mac["ah"] == 1440 - 25, "%sx%s" % (mac["aw"], mac["ah"]))
        check("colorDepth=24", mac["cd"] == 24, mac["cd"])

        print("\n===== 跨 userContext 隔离 =====")
        check("Win/Mac avail 互不串",
              win["ah"] == 1040 and mac["ah"] == 1415,
              "win.ah=%s mac.ah=%s" % (win["ah"], mac["ah"]))

        print("\n" + ("ALL PASSED" if ok else "SOME FAILED"))
        return ok
    finally:
        try: proc.terminate()
        except Exception: pass

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
