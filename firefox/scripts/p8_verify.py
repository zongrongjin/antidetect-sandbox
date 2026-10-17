# -*- coding: utf-8 -*-
"""P8 verify: per-context 隔离 + 未来上下文继承(SessionData) + 不破坏(主线程+dedicated worker)。

用 ~/browser_controller 框架 + 自编 FF152（moz:fingerprint 走 _configuration/SessionData）。
"""
import sys, os, json, tempfile
sys.path.insert(0, "/home/ubuntu")

os.environ["MOZ_HEADLESS"] = "1"
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"

import browser_controller as bc

FF = "/home/ubuntu/firefox-152.0.5/obj-release/dist/bin/firefox"
PAGE = "data:text/html,<title>p8</title><h1>p8</h1>"

RESULTS = []
def ck(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name, ("  " + extra) if extra else ""))
    return bool(cond)

def make_prof():
    prof = tempfile.mkdtemp(prefix="bc-p8-")
    with open(os.path.join(prof, "user.js"), "w") as f:
        f.write('\n'.join([
            'user_pref("webgl.force-enabled", true);',
            'user_pref("gfx.webrender.software", true);',
            'user_pref("dom.webaudio.enabled", true);',
            '',
        ]))
    return prof

def read_in(browser, ctx_id, expr):
    """在指定 browsing context id 里求值（用于读“新建的未来 tab”）。"""
    r = browser.run("script.evaluate", {
        "expression": expr, "target": {"context": ctx_id},
        "awaitPromise": False, "resultOwnership": "none"}, timeout=20)
    if isinstance(r, dict) and r.get("type") == "exception":
        return "EXC:" + str(r.get("exceptionDetails"))
    return r.get("result", {}).get("value") if isinstance(r, dict) else r

def profile_of(browser):
    """读一个 Browser 门面当前 context 的关键维度。"""
    return {
        "platform": browser.run_js("navigator.platform", timeout=20),
        "tz": browser.run_js("Intl.DateTimeFormat().resolvedOptions().timeZone", timeout=20),
        "lang": browser.run_js("navigator.language", timeout=20),
        "locale": browser.run_js("Intl.DateTimeFormat().resolvedOptions().locale", timeout=20),
    }

FP_A = {"platform": "Win32", "timezone": "Asia/Tokyo", "locale": "ja-JP",
        "acceptLanguages": "ja-JP,ja,en", "readbackSeed": 11111}
FP_B = {"platform": "MacIntel", "timezone": "Europe/Paris", "locale": "fr-FR",
        "acceptLanguages": "fr-FR,fr,en", "readbackSeed": 22222}

# ==================================================================== #
# 组 1：per-context 隔离 + per-userContext 未来上下文继承
# ==================================================================== #
print("=== 组1：per-context 隔离（new_context(fingerprint=) BiDi 分支）===")
b1 = bc.launch(FF, port=9222, extra_args=["-headless"], timeout=120)
cA = cB = None
try:
    b1.get(PAGE, timeout=30)
    native = profile_of(b1)          # 主/默认 context：无指纹
    print("  native default ctx:", native)

    cA = b1.new_context(fingerprint=FP_A)
    cB = b1.new_context(fingerprint=FP_B)
    cA.get(PAGE, timeout=30)
    cB.get(PAGE, timeout=30)
    pA = profile_of(cA)
    pB = profile_of(cB)
    print("  ctxA:", pA)
    print("  ctxB:", pB)

    ck("A.platform==Win32", pA["platform"] == "Win32", repr(pA["platform"]))
    ck("B.platform==MacIntel", pB["platform"] == "MacIntel", repr(pB["platform"]))
    ck("A/B platform 互不串", pA["platform"] != pB["platform"])
    ck("A.tz==Asia/Tokyo", pA["tz"] == "Asia/Tokyo", repr(pA["tz"]))
    ck("B.tz==Europe/Paris", pB["tz"] == "Europe/Paris", repr(pB["tz"]))
    ck("A/B tz 互不串", pA["tz"] != pB["tz"])
    ck("A.lang==ja-JP", pA["lang"] == "ja-JP", repr(pA["lang"]))
    ck("B.lang==fr-FR", pB["lang"] == "fr-FR", repr(pB["lang"]))
    ck("A.locale startswith ja", str(pA["locale"]).startswith("ja"), repr(pA["locale"]))
    ck("B.locale startswith fr", str(pB["locale"]).startswith("fr"), repr(pB["locale"]))
    ck("默认 context 不受影响（platform 非 Win32/MacIntel）",
       native["platform"] not in ("Win32", "MacIntel"), repr(native["platform"]))

    print("=== 组2a：per-userContext 未来上下文继承（设指纹后在同 user context 内新开 tab）===")
    uc_a = cA._driver._user_context
    res = cA.run("browsingContext.create", {"type": "tab", "userContext": uc_a}, timeout=20)
    future_ctx = res.get("context")
    cA.run("browsingContext.navigate",
           {"context": future_ctx, "url": PAGE, "wait": "complete"}, timeout=30)
    f_plat = read_in(cA, future_ctx, "navigator.platform")
    f_tz = read_in(cA, future_ctx, "Intl.DateTimeFormat().resolvedOptions().timeZone")
    print("  future tab in userContextA: platform=%r tz=%r" % (f_plat, f_tz))
    ck("未来 tab(同 userContextA) 继承 platform=Win32", f_plat == "Win32", repr(f_plat))
    ck("未来 tab(同 userContextA) 继承 tz=Asia/Tokyo", f_tz == "Asia/Tokyo", repr(f_tz))
finally:
    for c in (cA, cB):
        if c is not None:
            try: c.close()
            except Exception: pass
    b1.close()

# ==================================================================== #
# 组 2b：全局下发（不带 contexts/userContexts）+ 未来上下文继承（SessionData 主路径）
# ==================================================================== #
print("=== 组2b：全局下发 + 未来上下文继承（SessionData 主路径）===")
b2 = bc.launch(FF, port=9223, extra_args=["-headless"], timeout=120)
try:
    b2.get(PAGE, timeout=30)
    # 全局下发（无 contexts/userContexts）
    b2.run("moz:fingerprint.setContextOverrides", {"fingerprint": json.dumps(FP_A)}, timeout=20)
    # 现有默认 context 立即生效
    b2.get(PAGE, timeout=30)
    cur = profile_of(b2)
    print("  现有默认 context（全局下发后）:", cur)
    ck("全局下发对现有 context 生效 platform=Win32", cur["platform"] == "Win32", repr(cur["platform"]))
    ck("全局下发对现有 context 生效 tz=Asia/Tokyo", cur["tz"] == "Asia/Tokyo", repr(cur["tz"]))
    # 未来上下文：下发后新建 top BC
    res = b2.run("browsingContext.create", {"type": "tab"}, timeout=20)
    fctx = res.get("context")
    b2.run("browsingContext.navigate",
           {"context": fctx, "url": PAGE, "wait": "complete"}, timeout=30)
    g_plat = read_in(b2, fctx, "navigator.platform")
    g_tz = read_in(b2, fctx, "Intl.DateTimeFormat().resolvedOptions().timeZone")
    print("  未来新建 top BC: platform=%r tz=%r" % (g_plat, g_tz))
    ck("未来上下文继承全局 platform=Win32 (SessionData)", g_plat == "Win32", repr(g_plat))
    ck("未来上下文继承全局 tz=Asia/Tokyo (SessionData)", g_tz == "Asia/Tokyo", repr(g_tz))
finally:
    b2.close()

# ==================================================================== #
# 组 3：不破坏——主线程原有维度 + dedicated worker 抽查
# ==================================================================== #
print("=== 组3：不破坏（主线程 + dedicated worker + canvas 噪声）===")
WORKER_BODY = r"""
self.onmessage = async () => {
  const out = {};
  out.platform = navigator.platform;
  try { out.tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e){ out.tz='ERR'; }
  try {
    const c = new OffscreenCanvas(120,40); const x=c.getContext('2d');
    x.textBaseline='top'; x.font='14px Arial';
    x.fillStyle='#069'; x.fillText('FP-CJK-Test', 2, 12);
    const d=x.getImageData(0,0,120,40).data; let h=0;
    for(let i=0;i<d.length;i++){h=(h*31+d[i])>>>0;} out.canvasHash=h;
  } catch(e){ out.canvasHash='ERR:'+e; }
  postMessage(out);
};
"""
def worker_js():
    body = json.dumps(WORKER_BODY)
    return ("(function(){return new Promise((resolve)=>{"
            "var code=" + body + ";"
            "var b=new Blob([code],{type:'application/javascript'});"
            "var w=new Worker(URL.createObjectURL(b));"
            "w.onmessage=function(e){resolve(JSON.stringify(e.data));};"
            "w.onerror=function(e){resolve('WORKER_ERR:'+(e.message||e.filename||'?'));};"
            "w.postMessage('go');"
            "setTimeout(function(){resolve('TIMEOUT');},9000);});})()")
MAIN_CANVAS_JS = r"""(function(){var c=document.createElement('canvas');c.width=120;c.height=40;
var x=c.getContext('2d');x.textBaseline='top';x.font='14px Arial';x.fillStyle='#069';x.fillText('FP-CJK-Test',2,12);
var d=x.getImageData(0,0,120,40).data;var h=0;for(var i=0;i<d.length;i++){h=(h*31+d[i])>>>0;}return h;})()"""

b3 = bc.launch(FF, port=9224, extra_args=["-headless"], timeout=120)
try:
    b3.get(PAGE, timeout=30)
    base_worker = json.loads(b3.run_js_async(worker_js(), timeout=30))
    base_canvas = b3.run_js(MAIN_CANVAS_JS, timeout=30)
    b3.run("moz:fingerprint.setContextOverrides", {"fingerprint": json.dumps(FP_A)}, timeout=20)
    b3.get(PAGE, timeout=30)
    m = profile_of(b3)
    m_canvas = b3.run_js(MAIN_CANVAS_JS, timeout=30)
    w = json.loads(b3.run_js_async(worker_js(), timeout=30))
    print("  main:", m, "canvasHash=%r" % m_canvas)
    print("  worker:", w)
    ck("主线程 platform=Win32", m["platform"] == "Win32", repr(m["platform"]))
    ck("主线程 tz=Asia/Tokyo", m["tz"] == "Asia/Tokyo", repr(m["tz"]))
    ck("主线程 canvas 噪声生效 (fp!=native)", m_canvas != base_canvas,
       "%r vs %r" % (m_canvas, base_canvas))
    ck("dedicated worker platform=Win32", w.get("platform") == "Win32", repr(w.get("platform")))
    ck("dedicated worker tz=Asia/Tokyo", w.get("tz") == "Asia/Tokyo", repr(w.get("tz")))
    ck("worker vs main platform 一致", w.get("platform") == m["platform"])
    ck("worker OffscreenCanvas 噪声生效 (fp!=native)",
       w.get("canvasHash") != base_worker.get("canvasHash"),
       "%r vs %r" % (w.get("canvasHash"), base_worker.get("canvasHash")))
finally:
    b3.close()

print("\n=== TOTAL: %d/%d PASS ===" % (sum(1 for r in RESULTS if r), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
