# -*- coding: utf-8 -*-
"""Firefox WebRTC srflx 覆盖验证(BiDi)。
下发 webRTCPublicIP,建 RTCPeerConnection 配真实 STUN,采集 srflx candidate,
断言其地址 = fakeIP 而非真实公网 IP。native(不下发)作对照。
退出码 0=通过 / 1=失败。用法: python ff_webrtc_verify.py <firefox.exe> [fakeIP]
"""
import sys, time, json, os, subprocess, tempfile
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"): os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"
from websocket import create_connection

FF = sys.argv[1] if len(sys.argv) > 1 else r"E:\ff\obj-release\dist\bin\firefox.exe"
FAKE = sys.argv[2] if len(sys.argv) > 2 else "203.0.113.77"
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

# 页面内建 PeerConnection 收 candidate。用 script.evaluate 跑 async JS。
RTC_JS = r"""
(async () => {
  const out = {cands: [], sdp: ""};
  const pc = new RTCPeerConnection({iceServers: [
    {urls: "stun:stun.l.google.com:19302"},
    {urls: "stun:stun.cloudflare.com:3478"}
  ]});
  pc.onicecandidate = e => { if (e.candidate) out.cands.push(
    {c: e.candidate.candidate, a: e.candidate.address, t: e.candidate.type}); };
  pc.createDataChannel("x");
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(r => { const t = setTimeout(r, 8000);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") { clearTimeout(t); r(); } }); });
  out.sdp = pc.localDescription.sdp;
  return JSON.stringify(out);
})()
"""

def main():
    if os.name == "nt":
        subprocess.run(["taskkill", "/f", "/im", "firefox.exe"], capture_output=True)
        time.sleep(2)
    prof = tempfile.mkdtemp(prefix="ffw-")
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
            print(open(os.path.join(prof, "ff.err"), encoding="utf-8", errors="replace").read()[-1500:])
            return False

        ws = create_connection("ws://127.0.0.1:%d/session" % PORT,
                               suppress_origin=True, max_size=None)
        ws.settimeout(60)
        cmd(ws, "session.new", {"capabilities": {}})

        def gather(fp):
            uc = cmd(ws, "browser.createUserContext", {})["userContext"]
            if fp is not None:
                cmd(ws, "moz:fingerprint.setContextOverrides",
                    {"fingerprint": json.dumps(fp), "userContexts": [uc]})
            ctx = cmd(ws, "browsingContext.create",
                      {"type": "tab", "userContext": uc})["context"]
            # 需要安全上下文/https? WebRTC 在 http 也可用；navigate 到 example.com
            cmd(ws, "browsingContext.navigate",
                {"context": ctx, "url": "https://example.com/", "wait": "complete"})
            r = cmd(ws, "script.evaluate",
                    {"expression": RTC_JS, "target": {"context": ctx},
                     "awaitPromise": True})
            val = r.get("result", {}).get("value")
            return json.loads(val)

        print("被测: %s" % FF)
        print("fakeIP(webRTCPublicIP) = %s\n" % FAKE)

        nat = gather(None)
        fp = gather({"webRTCPublicIP": FAKE})

        def srflx(d):
            return [c for c in d["cands"] if c["t"] == "srflx"]
        def hosts(d):
            return [c for c in d["cands"] if c["t"] == "host"]

        ok = True
        print("===== native(不下发) srflx =====")
        nat_srflx = srflx(nat)
        for c in nat_srflx:
            print("  %s" % c["a"])
        real_ips = {c["a"] for c in nat_srflx}
        if not nat_srflx:
            print("  (无 srflx — STUN 不可达？无法验证)")
            return False

        print("\n===== 下发 webRTCPublicIP=%s 后 =====" % FAKE)
        fp_srflx = srflx(fp)
        for c in fp_srflx:
            good = c["a"] == FAKE
            print("  srflx .address : %s  %s" % ("OK" if good else "FAIL", c["a"]))
            if not good: ok = False
        if not fp_srflx:
            print("  FAIL 覆盖后没有 srflx candidate"); ok = False
        # SDP 里也不能出现真实 IP
        for rip in real_ips:
            if rip in fp.get("sdp", ""):
                print("  FAIL SDP 仍含真实 IP %s" % rip); ok = False
        # fakeIP 必须出现在 SDP
        if FAKE not in fp.get("sdp", ""):
            print("  FAIL SDP 未含 fakeIP"); ok = False
        else:
            print("  SDP 含 fakeIP        : OK")
        # host 应仍是 mDNS(.local)
        h = hosts(fp)
        for c in h:
            mdns = (c["a"] or "").endswith(".local")
            print("  host .address       : %s  %s" % ("OK" if mdns else "WARN", c["a"]))

        print("\n" + ("ALL PASSED" if ok else "SOME FAILED"))
        return ok
    finally:
        try: proc.terminate()
        except Exception: pass

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
