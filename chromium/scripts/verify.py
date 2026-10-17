#!/usr/bin/env python3
"""独立验证：起一个 localhost 页面(安全上下文，userAgentData 才可用) → 启动被测
chrome → 用自定义 Context CDP 域给隔离 BrowserContext 下发
Edge/法国/NVIDIA 指纹 → 回读关键维度，包括全部 UserAgentMetadata 字段、
实际发出的 Accept-Language 请求头、以及 WebGL。

只依赖 websocket-client:  pip install websocket-client
用法:  python3 scripts/verify.py [--headed] <chrome 路径>   (默认 out/Default/chrome)
"""
import json, os, subprocess, time, sys, threading, tempfile
import http.server, socketserver, urllib.request
from websocket import create_connection

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("PYTHONUTF8", "1")

_argv = [a for a in sys.argv[1:] if a != "--headed"]
HEADED = "--headed" in sys.argv[1:]
CHROME = _argv[0] if _argv else "out/Default/chrome"
PORT, DBG = 8137, 9222

FP = {
    "userAgent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.1234.7"),
    "platform": "Win32", "uaPlatform": "Windows",
    "acceptLanguages": "fr-FR,fr;q=0.9,en;q=0.8", "locale": "fr-FR", "timezone": "Europe/Paris",
    "hardwareConcurrency": 8, "screenWidth": 1920, "screenHeight": 1080,
    "uaBrands": [{"b": "Microsoft Edge", "v": "151"}, {"b": "Chromium", "v": "151"}, {"b": "Not_A Brand", "v": "24"}],
    "uaFullBrands": [{"b": "Microsoft Edge", "v": "151.0.1234.7"}, {"b": "Chromium", "v": "151.0.1234.7"}, {"b": "Not_A Brand", "v": "24.0.0.0"}],
    "uaFullVersion": "151.0.1234.7",
    "platformVersion": "15.0.0",
    "architecture": "x86",
    "model": "",
    "mobile": False,
    "bitness": "64",
    "wow64": False,
    "webglVendor": "Google Inc. (NVIDIA)",
    "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "readbackSeed": 77777,
    "webRTCPublicIP": "203.0.113.7",   # TEST-NET-3，绝不会是真实出口 IP
    "colorDepth": 30,                  # 故意取非 24，与真机默认值区分开
    "deviceMemory": 8,
}

EXPECT_HE = {
    "platform": "Windows",
    "uaFullVersion": "151.0.1234.7",
    "platformVersion": "15.0.0",
    "architecture": "x86",
    "model": "",
    "mobile": False,
    "bitness": "64",
    "wow64": False,
    "formFactors": ["Desktop"],
}

# 记录每个请求实际带的 Accept-Language，用于校验主文档 / 子资源是否一致。
HDRS = {}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HDRS[self.path] = self.headers.get("Accept-Language")
        if self.path == "/sub.js":
            self.send_response(200); self.send_header("Content-Type", "application/javascript"); self.end_headers()
            self.wfile.write(b"window.__sub=1;")
            return
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(b"<!doctype html><html><body><h1>fp-verify</h1>"
                         b"<script src='/sub.js'></script></body></html>")
    def log_message(self, *a): pass

class _Server(socketserver.ThreadingTCPServer):
    # 必须多线程：verify 会开多个 BrowserContext，每个都来连一次。
    # 单线程 TCPServer 只要被一个 keep-alive 连接挂住就不再 accept，
    # 后续 context 的 Page.navigate 会永久挂起。
    daemon_threads = True
    allow_reuse_address = True


def serve():
    with _Server(("127.0.0.1", PORT), H) as httpd:
        httpd.serve_forever()

_T0 = time.time()
def step(msg):
    """分阶段进度。卡住时最后一行就是卡住的位置。"""
    print("  [%6.1fs] %s" % (time.time() - _T0, msg), flush=True)


_id = 0
def cmd(ws, method, params=None, sess=None):
    global _id; _id += 1; mid = _id
    m = {"id": mid, "method": method, "params": params or {}}
    if sess: m["sessionId"] = sess
    ws.send(json.dumps(m))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            if "error" in r:
                raise RuntimeError("%s: %s" % (method, r["error"]))
            return r.get("result", {})


def set_context_overrides(ws, fingerprint=None, sess=None, proxy=None):
    """Prefer Context.setContextOverrides; fall back to Fingerprint domain."""
    params = {}
    if fingerprint is not None:
        params["fingerprint"] = (
            fingerprint if isinstance(fingerprint, str) else json.dumps(fingerprint)
        )
    if proxy is not None:
        params["proxy"] = proxy
    try:
        return cmd(ws, "Context.setContextOverrides", params, sess=sess)
    except RuntimeError:
        if "fingerprint" not in params:
            raise
        return cmd(ws, "Fingerprint.setContextOverrides",
                   {"fingerprint": params["fingerprint"]}, sess=sess)


# //BROWSER_FINGERPRINT: 读回面摘要。canvas/WebGL/audio 是本项目最核心的能力，
# 但此前 verify 只校验了 webglVendor/Renderer 两个字符串，噪声与固定回放一项没测。
# 用 FNV-1a 而非 crypto.subtle：后者依赖安全上下文，探测时不一定可用。
READBACK_JS = r"""
(async () => {
  const out = {};
  const dig = (buf) => {
    const u = new Uint8Array(buf);
    let h1 = 0x811c9dc5, h2 = 0x01000193;
    for (let i = 0; i < u.length; i++) {
      h1 ^= u[i]; h1 = Math.imul(h1, 16777619) >>> 0;
      h2 = (h2 + u[i] * (i % 251 + 1)) >>> 0;
    }
    return (h1.toString(16).padStart(8,'0') + h2.toString(16).padStart(8,'0')).slice(0,12);
  };
  const paint = (c) => {
    const x = c.getContext('2d');
    x.textBaseline='top'; x.font='14px Arial'; x.fillStyle='#f60';
    x.fillRect(1,1,62,20); x.fillStyle='#069'; x.fillText('Cwm fjord',2,2);
    x.strokeStyle='rgba(0,255,0,0.7)'; x.beginPath(); x.arc(40,20,15,0,Math.PI*2); x.stroke();
    return x;
  };
  try { const c=document.createElement('canvas'); c.width=120; c.height=40;
        out['canvas2d.getImageData']=dig(paint(c).getImageData(0,0,120,40).data.buffer);
  } catch(e){ out['canvas2d.getImageData']='ERR'; }
  try { const c=document.createElement('canvas'); c.width=120; c.height=40; paint(c);
        out['canvas2d.toDataURL']=dig(new TextEncoder().encode(c.toDataURL()).buffer);
  } catch(e){ out['canvas2d.toDataURL']='ERR'; }
  try { const c=document.createElement('canvas'); c.width=120; c.height=40; paint(c);
        const b=await new Promise(r=>c.toBlob(r));
        out['canvas2d.toBlob']=dig(await b.arrayBuffer());
  } catch(e){ out['canvas2d.toBlob']='ERR'; }
  try { const oc=new OffscreenCanvas(120,40); const x=oc.getContext('2d');
        x.font='14px Arial'; x.fillStyle='#069'; x.fillText('Off',2,20);
        out['OffscreenCanvas.convertToBlob']=dig(await (await oc.convertToBlob()).arrayBuffer());
  } catch(e){ out['OffscreenCanvas.convertToBlob']='ERR'; }
  for (const [n,t] of [['webgl1','webgl'],['webgl2','webgl2']]) {
    try {
      const c=document.createElement('canvas'); c.width=64; c.height=64;
      const gl=c.getContext(t); if(!gl){ out['gl.readPixels.'+n]='NOCTX'; continue; }
      gl.clearColor(0.2,0.5,0.8,1.0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.SCISSOR_TEST); gl.scissor(10,10,20,20);
      gl.clearColor(0.9,0.1,0.3,1.0); gl.clear(gl.COLOR_BUFFER_BIT); gl.disable(gl.SCISSOR_TEST);
      const px=new Uint8Array(64*64*4); gl.readPixels(0,0,64,64,gl.RGBA,gl.UNSIGNED_BYTE,px);
      out['gl.readPixels.'+n]=dig(px.buffer);
    } catch(e){ out['gl.readPixels.'+n]='ERR'; }
  }
  try {
    const o=new OfflineAudioContext(1,4096,44100);
    const s=o.createOscillator(); s.type='triangle'; s.frequency.value=1e3;
    const c=o.createDynamicsCompressor(); s.connect(c); c.connect(o.destination); s.start(0);
    out['OfflineAudioContext']=dig((await o.startRendering()).getChannelData(0).buffer);
  } catch(e){ out['OfflineAudioContext']='ERR'; }
  try {
    const o=new OfflineAudioContext(1,4096,44100);
    const s=o.createOscillator(); const a=o.createAnalyser();
    s.connect(a); a.connect(o.destination); s.start(0); await o.startRendering();
    const f=new Float32Array(a.frequencyBinCount); a.getFloatFrequencyData(f);
    out['AnalyserNode.float']=dig(f.buffer);
    const b=new Uint8Array(a.frequencyBinCount); a.getByteFrequencyData(b);
    out['AnalyserNode.byte']=dig(b.buffer);
  } catch(e){ out['AnalyserNode.float']='ERR'; out['AnalyserNode.byte']='ERR'; }
  return JSON.stringify(out);
})()"""


def readback_digests(ws, fp, tag=""):
    """新开一个 BrowserContext(fp=None 表示不下发指纹)，回读各读回面摘要。"""
    step("readback[%s] 建 context" % tag)
    ctx = cmd(ws, "Target.createBrowserContext")["browserContextId"]
    tgt = cmd(ws, "Target.createTarget",
              {"url": "about:blank", "browserContextId": ctx})["targetId"]
    sess = cmd(ws, "Target.attachToTarget",
               {"targetId": tgt, "flatten": True})["sessionId"]
    if fp is not None:
        set_context_overrides(ws, fingerprint=fp, sess=sess)
    cmd(ws, "Page.enable", sess=sess)
    cmd(ws, "Page.navigate", {"url": "http://localhost:%d/" % PORT}, sess=sess)
    time.sleep(0.8)
    step("readback[%s] 执行 JS" % tag)
    r = json.loads(cmd(ws, "Runtime.evaluate",
                       {"expression": READBACK_JS, "returnByValue": True,
                        "awaitPromise": True}, sess=sess)["result"]["value"])
    step("readback[%s] 完成" % tag)
    cmd(ws, "Target.closeTarget", {"targetId": tgt})
    return r


# //BROWSER_FINGERPRINT: 移动端自洽 + webgl2 分键。这些维度全部由内核按画像派生，
# 不经 CDP 逐字段下发：dpr/maxTouchPoints 直读，pointer/hover 由 maxTouchPoints
# 派生(触屏=coarse/none，桌面=fine/hover)，screen.orientation 由 screen 尺寸+触屏
# 派生，webgl2 扩展按上下文版本(IsWebGL2)分键读 webgl2Extensions。
NEWDIMS_JS = r"""JSON.stringify((function(){
  var mm=function(q){try{return matchMedia(q).matches;}catch(e){return null;}};
  var o={
    dpr: window.devicePixelRatio,
    mtp: navigator.maxTouchPoints,
    ptr_coarse: mm('(pointer: coarse)'), ptr_fine: mm('(pointer: fine)'),
    ptr_none: mm('(pointer: none)'),
    any_coarse: mm('(any-pointer: coarse)'), any_fine: mm('(any-pointer: fine)'),
    hover_hover: mm('(hover: hover)'), hover_none: mm('(hover: none)'),
    any_hover: mm('(any-hover: hover)'),
    ori_type: (screen.orientation? screen.orientation.type : null),
    ori_angle: (screen.orientation? screen.orientation.angle : null)
  };
  try{var c1=document.createElement('canvas');var g1=c1.getContext('webgl');
      o.gl1ext=g1?g1.getSupportedExtensions():null;}catch(e){o.gl1ext='ERR';}
  try{var c2=document.createElement('canvas');var g2=c2.getContext('webgl2');
      o.gl2ext=g2?g2.getSupportedExtensions():null;}catch(e){o.gl2ext='ERR';}
  return o;
})())"""


def newdims_probe(ws, fp, tag=""):
    """新开 context 下发 fp，回读 dpr/touch/pointer/hover/orientation/webglExt。"""
    step("newdims[%s] 建 context" % tag)
    ctx = cmd(ws, "Target.createBrowserContext")["browserContextId"]
    tgt = cmd(ws, "Target.createTarget",
              {"url": "about:blank", "browserContextId": ctx})["targetId"]
    sess = cmd(ws, "Target.attachToTarget",
               {"targetId": tgt, "flatten": True})["sessionId"]
    set_context_overrides(ws, fingerprint=fp, sess=sess)
    cmd(ws, "Page.enable", sess=sess)
    cmd(ws, "Page.navigate", {"url": "http://localhost:%d/" % PORT}, sess=sess)
    time.sleep(0.8)
    r = json.loads(cmd(ws, "Runtime.evaluate",
                       {"expression": NEWDIMS_JS, "returnByValue": True},
                       sess=sess)["result"]["value"])
    step("newdims[%s] 完成" % tag)
    cmd(ws, "Target.closeTarget", {"targetId": tgt})
    return r


def check_newdims(ws):
    """校验 5 个新增维度在桌面(mtp=0)与触屏(mtp>0)两种画像下自洽。"""
    ok = True
    GL1 = ["ANGLE_instanced_arrays", "OES_texture_float", "WEBGL_debug_renderer_info"]
    GL2 = ["EXT_color_buffer_float", "OES_draw_buffers_indexed", "EXT_texture_norm16"]

    # 桌面：dpr=1.5，无触点，1920x1080 横屏 → pointer:fine / hover:hover /
    # orientation=landscape-primary,angle=0。
    desk = dict(FP, dpr=1.5, maxTouchPoints=0, screenWidth=1920, screenHeight=1080,
                webglExtensions=GL1, webgl2Extensions=GL2)
    # 触屏：dpr=3.5，5 触点，412x915 竖屏 → pointer:coarse / hover:none /
    # orientation=portrait-primary,angle=0。UA 不改(不测 UA，仅测按触点派生)。
    touch = dict(FP, dpr=3.5, maxTouchPoints=5, screenWidth=412, screenHeight=915,
                 webglExtensions=GL1, webgl2Extensions=GL2)

    d = newdims_probe(ws, desk, "desktop")
    t = newdims_probe(ws, touch, "touch")

    def chk(label, got, want):
        nonlocal ok
        m = got == want
        print("  %-34s: %s  (期望=%r, 实际=%r)" % (label, "OK" if m else "FAIL", want, got))
        if not m:
            ok = False

    print("\n===== 新增维度·桌面画像 (mtp=0, 1920x1080) =====")
    chk("devicePixelRatio", d["dpr"], 1.5)
    chk("navigator.maxTouchPoints", d["mtp"], 0)
    chk("pointer: fine", d["ptr_fine"], True)
    chk("pointer: coarse", d["ptr_coarse"], False)
    chk("any-pointer: fine", d["any_fine"], True)
    chk("hover: hover", d["hover_hover"], True)
    chk("hover: none", d["hover_none"], False)
    chk("screen.orientation.type", d["ori_type"], "landscape-primary")
    chk("screen.orientation.angle", d["ori_angle"], 0)

    print("\n===== 新增维度·触屏画像 (mtp=5, 412x915) =====")
    chk("devicePixelRatio", t["dpr"], 3.5)
    chk("navigator.maxTouchPoints", t["mtp"], 5)
    chk("pointer: coarse", t["ptr_coarse"], True)
    chk("pointer: fine", t["ptr_fine"], False)
    chk("any-pointer: coarse", t["any_coarse"], True)
    chk("hover: none", t["hover_none"], True)
    chk("hover: hover", t["hover_hover"], False)
    chk("screen.orientation.type", t["ori_type"], "portrait-primary")
    chk("screen.orientation.angle", t["ori_angle"], 0)

    print("\n===== 新增维度·webgl2 扩展分键 (IsWebGL2) =====")
    # webgl1 上下文读 webglExtensions、webgl2 读 webgl2Extensions；两者必须各自
    # 命中且互不串味。headless swiftshader 拿不到 context 时明确报告，不静默放过。
    if d["gl1ext"] in ("ERR", None) or d["gl2ext"] in ("ERR", None):
        print("  webgl context 不可用(%r/%r): FAIL 未验证" % (d["gl1ext"], d["gl2ext"]))
        ok = False
    else:
        chk("webgl1.getSupportedExtensions", d["gl1ext"], GL1)
        chk("webgl2.getSupportedExtensions", d["gl2ext"], GL2)
        split = d["gl1ext"] != d["gl2ext"]
        print("  webgl1 != webgl2 (分键生效)        : %s" % ("OK" if split else "FAIL"))
        if not split:
            ok = False
    return ok



def main():
    threading.Thread(target=serve, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="fp-verify-")
    chrome_args = [CHROME]
    if not HEADED:
        chrome_args.append("--headless=new")
    chrome_args += [
        "--no-sandbox", "--disable-gpu-sandbox",
        "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
        # Windows 无 GPU / headless 下不显式指定就拿不到 WebGL context
        "--use-gl=angle", "--use-angle=swiftshader",
        # 不关掉的话 navigator.languages 会被截断成只剩第一项，
        # q 值泄漏就被掩盖、多语言画像也验不了。browser-controller 也是这么启动的。
        "--disable-features=ReduceAcceptLanguage",
        "--password-store=basic",   # Windows: ssh 网络登录下 DPAPI 不可用，不加会崩
        "--no-first-run", "--disable-extensions",
        "--remote-allow-origins=*",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=%d" % DBG, "--user-data-dir=%s" % profile,
    ]
    chrome_cwd = os.path.dirname(os.path.abspath(CHROME)) or None
    step("启动 chrome headed=%s cwd=%s" % (HEADED, chrome_cwd))
    proc = subprocess.Popen(
        chrome_args, cwd=chrome_cwd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    step("chrome 已启动，等调试端口")
    try:
        bws = None
        for _ in range(60):
            try:
                v = json.load(urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/version" % DBG, timeout=1))
                bws = v["webSocketDebuggerUrl"]; break
            except Exception:
                time.sleep(0.5)
        if not bws:
            raise RuntimeError("chrome 调试端口未就绪")
        step("调试端口就绪")
        ws = create_connection(bws, max_size=None)
        ws.settimeout(45)
        step("websocket 已连接")

        ctx = cmd(ws, "Target.createBrowserContext")["browserContextId"]
        tgt = cmd(ws, "Target.createTarget", {"url": "about:blank", "browserContextId": ctx})["targetId"]
        sess = cmd(ws, "Target.attachToTarget", {"targetId": tgt, "flatten": True})["sessionId"]

        step("context/target 已建")
        set_context_overrides(ws, fingerprint=FP, sess=sess)
        step("指纹已下发")

        cmd(ws, "Page.enable", sess=sess)
        cmd(ws, "Page.navigate", {"url": "http://localhost:%d/" % PORT}, sess=sess)
        time.sleep(1.0)

        PROBE = r"""JSON.stringify((function(){var o={ua:navigator.userAgent,platform:navigator.platform,
          lang:navigator.language,langs:navigator.languages,tz:Intl.DateTimeFormat().resolvedOptions().timeZone,
          locale:Intl.DateTimeFormat().resolvedOptions().locale,hc:navigator.hardwareConcurrency,
          screen:[screen.width,screen.height],avail:[screen.availWidth,screen.availHeight,screen.availLeft,screen.availTop],
          cd:screen.colorDepth,pd:screen.pixelDepth,dm:navigator.deviceMemory,
          brands:(navigator.userAgentData?navigator.userAgentData.brands:null)};
          try{var c=document.createElement('canvas');var gl=c.getContext('webgl')||c.getContext('experimental-webgl');
          var e=gl.getExtension('WEBGL_debug_renderer_info');o.webglVendor=gl.getParameter(e.UNMASKED_VENDOR_WEBGL);
          o.webglRenderer=gl.getParameter(e.UNMASKED_RENDERER_WEBGL);}catch(err){o.webglErr=String(err);}return o;})())"""
        step("执行 PROBE")
        p = json.loads(cmd(ws, "Runtime.evaluate", {"expression": PROBE, "returnByValue": True}, sess=sess)["result"]["value"])
        step("PROBE 完成")
        print("\n===== 基本指纹回读 =====")
        for k in ("ua", "platform", "lang", "langs", "tz", "locale", "hc", "screen", "avail",
                  "cd", "pd", "dm", "brands", "webglVendor", "webglRenderer", "webglErr"):
            if k in p:
                print("  %-13s: %s" % (k, p[k]))

        HE = ('navigator.userAgentData.getHighEntropyValues('
              '["platform","fullVersionList","uaFullVersion","platformVersion",'
              '"architecture","model","mobile","bitness","wow64","formFactors"])'
              '.then(v=>JSON.stringify(v))')
        step("执行高熵值")
        r2 = cmd(ws, "Runtime.evaluate", {"expression": HE, "returnByValue": True, "awaitPromise": True}, sess=sess)
        step("高熵值完成")
        he = json.loads(r2["result"]["value"])

        print("\n===== 高熵值回读 (getHighEntropyValues) =====")
        for k, v in sorted(he.items()):
            print("  %-18s: %s" % (k, v))

        print("\n===== 高熵值验证 =====")
        ok = True
        for k, expected in EXPECT_HE.items():
            actual = he.get(k)
            match = actual == expected
            mark = "OK" if match else "FAIL"
            print("  %-18s: %s  (期望=%r, 实际=%r)" % (k, mark, expected, actual))
            if not match:
                ok = False

        fvl = he.get("fullVersionList", [])
        expected_fvl = [{"brand": e["b"], "version": e["v"]} for e in FP["uaFullBrands"]]
        fvl_match = fvl == expected_fvl
        print("  %-18s: %s" % ("fullVersionList", "OK" if fvl_match else "FAIL"))
        if not fvl_match:
            print("    期望: %s" % expected_fvl)
            print("    实际: %s" % fvl)
            ok = False

        # Accept-Language：浏览器必须把 acceptLanguages 逐字透传，自身不补 q。
        # 调用方(browser_controller 的 _accept_language_q)负责按 Chrome 规则补 q。
        # 曾经的 bug：子资源/worker 路径额外补一次 q，产出 "fr;q=0.9;q=0.9"，
        # 且与主文档导航头不一致 —— 只比对这两个头就能识破。
        print("\n===== Accept-Language 请求头 =====")
        expect_hdr = FP["acceptLanguages"]
        for path, label in (("/", "主文档"), ("/sub.js", "子资源")):
            got = HDRS.get(path)
            mark = "OK" if got == expect_hdr else "FAIL"
            print("  %-6s %-9s: %s  %r" % (label, path, mark, got))
            if got != expect_hdr:
                print("           %-9s  期望=%r" % ("", expect_hdr))
                ok = False

        # navigator.languages 反过来必须剥掉 q —— 真实 Chrome 的列表里绝不含 ";q="。
        print("\n===== navigator.languages 不得含 q 值 =====")
        langs = p.get("langs") or []
        leaked = [x for x in langs if ";" in x]
        print("  langs      : %s" % langs)
        print("  含 q 的项  : %s  -> %s" % (leaked or "无", "OK" if not leaked else "FAIL"))
        if leaked:
            ok = False
        expect_langs = [t.split(";")[0].strip() for t in expect_hdr.split(",") if t.strip()]
        if langs != expect_langs:
            print("  FAIL 列表不符  期望=%r 实际=%r" % (expect_langs, langs))
            ok = False

        # screen / deviceMemory。availHeight 必须与 height 不同 —— 真实桌面有任务栏，
        # 两者相等本身就是特征。deviceMemory 还有请求头出口，见下方注释。
        print("\n===== screen / deviceMemory =====")
        exp_avail_h = FP["screenHeight"] - 40      # uaPlatform=Windows → 扣任务栏
        checks = [
            ("screen.width",      p["screen"][0], FP["screenWidth"]),
            ("screen.height",     p["screen"][1], FP["screenHeight"]),
            ("screen.availWidth", p["avail"][0],  FP["screenWidth"]),
            ("screen.availHeight", p["avail"][1], exp_avail_h),
            ("screen.colorDepth", p["cd"],        FP["colorDepth"]),
            ("screen.pixelDepth", p["pd"],        FP["colorDepth"]),
            ("navigator.deviceMemory", p["dm"],   FP["deviceMemory"]),
        ]
        for name, got, want in checks:
            mark = "OK" if got == want else "FAIL"
            print("  %-24s: %s  (期望=%r, 实际=%r)" % (name, mark, want, got))
            if got != want:
                ok = False
        if p["avail"][1] == p["screen"][1]:
            print("  availHeight == height    : FAIL  真实桌面不会相等")
            ok = False

        # WebRTC：srflx 必须报 webRTCPublicIP，host 必须仍是 mDNS。
        # 四个 JS 出口都要查 —— 只改 candidate 字符串会漏掉 .address 和 getStats()。
        RTC = r"""
        (async () => {
          const out = {cands: [], sdp: '', stats: []};
          const pc = new RTCPeerConnection({iceServers:[
            {urls:'stun:stun.l.google.com:19302'},{urls:'stun:stun.qq.com:3478'}]});
          pc.onicecandidate = e => { if (e.candidate) out.cands.push(
            {s: e.candidate.candidate, a: e.candidate.address, t: e.candidate.type}); };
          pc.createDataChannel('v');
          await pc.setLocalDescription(await pc.createOffer());
          await new Promise(r => { const t = setTimeout(r, 5000);
            pc.addEventListener('icegatheringstatechange', () => {
              if (pc.iceGatheringState === 'complete') { clearTimeout(t); r(); } }); });
          out.sdp = pc.localDescription.sdp;
          (await pc.getStats()).forEach(s => { if (s.type === 'local-candidate')
            out.stats.push({a: s.address, t: s.candidateType}); });
          return JSON.stringify(out);
        })()"""
        step("执行 WebRTC 收集(最多5s)")
        rtc = json.loads(cmd(ws, "Runtime.evaluate",
                             {"expression": RTC, "returnByValue": True, "awaitPromise": True},
                             sess=sess)["result"]["value"])
        step("WebRTC 完成")
        want_ip = FP["webRTCPublicIP"]
        srflx = [c for c in rtc["cands"] if c["t"] == "srflx"]
        hosts = [c for c in rtc["cands"] if c["t"] == "host"]
        print("\n===== WebRTC ICE candidate =====")
        for c in rtc["cands"]:
            print("  %-6s %s" % (c["t"], c["s"]))
        if not srflx:
            # 没有 srflx 说明 STUN 不通（网络受限），无法判定，明确报告而不是静默放过
            print("  !! 没有 srflx candidate（STUN 不可达？），WebRTC 覆盖未被验证")
            ok = False
        for c in srflx:
            good = c["a"] == want_ip and want_ip in c["s"]
            print("  srflx .address : %s  %r" % ("OK" if good else "FAIL", c["a"]))
            if not good:
                ok = False
        for c in hosts:
            good = c["a"].endswith(".local")
            print("  host  .address : %s  %r  (应为 mDNS)" % ("OK" if good else "FAIL", c["a"]))
            if not good:
                ok = False
        n_dup = len(srflx) - len({c["s"] for c in srflx})
        print("  srflx 重复条数  : %s  (%d 条)" % ("OK" if n_dup == 0 else "FAIL", len(srflx)))
        if n_dup:
            ok = False
        sdp_ok = ("c=IN IP4 %s" % want_ip) in rtc["sdp"]
        print("  SDP c= 行       : %s" % ("OK" if sdp_ok else "FAIL"))
        if not sdp_ok:
            ok = False
        st = [s["a"] for s in rtc["stats"] if s["t"] == "srflx"]
        st_ok = bool(st) and all(a == want_ip for a in st)
        print("  getStats() srflx: %s  %r" % ("OK" if st_ok else "FAIL", st))
        if not st_ok:
            ok = False

        # webRTC 模式开关：另起一个 context 下发 webRTC=0，应当一条 candidate 都没有。
        # 不验这个的话，模式开关坏掉了主流程也发现不了（主流程用的是默认模式）。
        print("\n===== WebRTC 模式开关 (webRTC=0) =====")
        ctx0 = cmd(ws, "Target.createBrowserContext")["browserContextId"]
        tgt0 = cmd(ws, "Target.createTarget",
                   {"url": "http://localhost:%d/" % PORT,
                    "browserContextId": ctx0})["targetId"]
        sess0 = cmd(ws, "Target.attachToTarget",
                    {"targetId": tgt0, "flatten": True})["sessionId"]
        set_context_overrides(ws, fingerprint={"webRTC": 0}, sess=sess0)
        time.sleep(0.6)
        rtc0 = json.loads(cmd(ws, "Runtime.evaluate",
                              {"expression": RTC, "returnByValue": True,
                               "awaitPromise": True}, sess=sess0)["result"]["value"])
        n0 = len(rtc0["cands"])
        print("  candidate 数   : %s  (%d，期望 0)" % ("OK" if n0 == 0 else "FAIL", n0))
        if n0 != 0:
            for c in rtc0["cands"]:
                print("      %s" % c["s"])
            ok = False

        # 读回面：同 seed 必一致(可复现)、异 seed 必不同(context 隔离)、
        # 且都必须与不下发指纹时不同(说明真的生效)。三者缺一，检查就是废的。
        print("\n===== 读回面 canvas / WebGL / audio =====")
        rb_base = readback_digests(ws, FP, "base")
        rb_same = readback_digests(ws, FP, "same")
        rb_diff = readback_digests(ws, dict(FP, readbackSeed=FP["readbackSeed"] + 1), "diff")
        rb_nat = readback_digests(ws, None, "native")
        for k in sorted(rb_base):
            b = rb_base.get(k)
            if str(b).startswith("ERR") or b == "NOCTX":
                print("  %-30s: 跳过 (%s)" % (k, b))
                continue
            det = (b == rb_same.get(k))
            iso = (b != rb_diff.get(k))
            act = (b != rb_nat.get(k))
            good = det and iso and act
            print("  %-30s: %-4s 确定性%s 隔离%s 生效%s  %s" % (
                k, "OK" if good else "FAIL",
                "OK" if det else "FAIL", "OK" if iso else "FAIL",
                "OK" if act else "FAIL", b))
            if not good:
                ok = False

        # webgl 拿不到 context 时上面只会打印 webglErr，若不在此判负会假通过。
        print("\n===== WebGL =====")
        for key in ("webglVendor", "webglRenderer"):
            got, expected = p.get(key), FP[key]
            mark = "OK" if got == expected else "FAIL"
            print("  %-14s: %s  %r" % (key, mark, got))
            if got != expected:
                ok = False
        if "webglErr" in p:
            print("  webglErr      : FAIL  %s" % p["webglErr"])
            ok = False

        # 新增维度：移动端自洽(dpr/maxTouchPoints/pointer/hover/orientation) + webgl2 分键
        if not check_newdims(ws):
            ok = False

        print("\n" + ("ALL PASSED" if ok else "SOME FAILED"))
        return ok
    finally:
        proc.terminate()

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
