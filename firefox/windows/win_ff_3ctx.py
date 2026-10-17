# -*- coding: utf-8 -*-
import sys, time, json, os, subprocess, shutil
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'): os.environ.pop(k, None)
os.environ['NO_PROXY']='*'; os.environ['no_proxy']='*'
sys.path.insert(0, "C:\\")
import browser_controller as bc
from websocket import create_connection
FF = r"C:\ff\firefox-152.0.5\obj-release\dist\bin\firefox.exe"
PORT = 9223
URL = "https://secdev.solvermarket.com/fp-d7c41884426bc076/index.html"
def P(ua,plat,osc,hc,langs,loc,tz,sw,sh,glv,glr,seed):
    return {"userAgent":ua,"platform":plat,"oscpu":osc,"hardwareConcurrency":hc,"acceptLanguages":langs,
            "locale":loc,"timezone":tz,"screenWidth":sw,"screenHeight":sh,"webglVendor":glv,"webglRenderer":glr,"readbackSeed":seed}
PROFILES={
 "ctxA_FR_NVIDIA_Win":P("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0","Win32","Windows NT 10.0; Win64; x64",16,"fr-FR,fr","fr-FR","Europe/Paris",2560,1440,"Google Inc. (NVIDIA)","ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)",111111),
 "ctxB_JP_Apple_Mac":P("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0","MacIntel","Intel Mac OS X 10.15",10,"ja-JP,ja","ja-JP","Asia/Tokyo",1728,1117,"Apple","Apple M2",222222),
 "ctxC_US_AMD_Linux":P("Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0","Linux x86_64","Linux x86_64",12,"en-US,en","en-US","America/New_York",1920,1080,"AMD","AMD Radeon RX 6800 XT (navi21, LLVM 15.0.6, DRM 3.49)",333333),
}
PROBE=r"""(function(){var o={};o.platform=navigator.platform;o.oscpu=navigator.oscpu;o.lang=navigator.language;o.tz=Intl.DateTimeFormat().resolvedOptions().timeZone;o.hc=navigator.hardwareConcurrency;o.numFmt=(1234567.89).toLocaleString();return JSON.stringify(o);})()"""
def wait_det(c,secs=120):
    for _ in range(secs//3):
        time.sleep(3)
        try:
            st=c.run_js("(function(){var s=document.querySelectorAll('.st');if(!s.length)return 'nost';var a=0;for(var i=0;i<s.length;i++){if(/wait|run/.test(s[i].className))a++;}return a;})()")
        except Exception: st='err'
        if str(st)=='0': return True
    return False
subprocess.run(['taskkill','/f','/im','firefox.exe'], capture_output=True)
time.sleep(2)
prof=r"C:\ffverify_prof"; shutil.rmtree(prof, ignore_errors=True)
errf=open(r'C:\ffproc.err','w',encoding='utf-8',errors='replace')
print("LAUNCHING firefox port %d"%PORT, flush=True)
proc=subprocess.Popen([FF,'-headless','--remote-debugging-port',str(PORT),'-profile',prof,'-no-remote','about:blank'], stdout=errf, stderr=subprocess.STDOUT)
ready=False
for _ in range(40):
    time.sleep(2)
    try:
        ws=create_connection('ws://127.0.0.1:%d/session'%PORT, suppress_origin=True, timeout=5); ws.close(); ready=True; break
    except Exception: pass
print("BiDi /session ready:", ready, flush=True)
if not ready:
    errf.flush()
    try: print("firefox stderr tail:\n"+open(r'C:\ffproc.err',encoding='utf-8',errors='replace').read()[-1000:], flush=True)
    except Exception as e: print("no stderr", e, flush=True)
    try: proc.terminate()
    except Exception: pass
    print(">>> bad contexts: ABORT-notready <<<", flush=True); print("FFVERIFYDONE", flush=True); sys.exit(1)
b=bc.connect(port=PORT, browser_type='bidi')
print("CONNECTED", flush=True)
res={}
for name,prof2 in PROFILES.items():
    c=b.new_context(fingerprint=prof2)
    try: c.run("browsingContext.activate", {"context": c._driver._ctx})
    except Exception: pass
    try:
        c.get(URL,timeout=60); time.sleep(1)
        c.run_js("var r=document.getElementById('run'); if(r) r.click();")
    except Exception as e:
        print(name,"nav warn",repr(e)[:100],flush=True)
    res[name]=c
    print(name,"created+navigated",flush=True)
print("---- wait detectors ----",flush=True)
out={}
for name,c in res.items():
    wait_det(c)
    meta=str(c.run_js("(document.getElementById('meta')||{}).innerText||''")).replace("\n"," ")
    probe=json.loads(c.run_js(PROBE))
    incon=""
    if "0 " not in meta[:3]:
        incon=str(c.run_js("(document.getElementById('inconWrap')||{}).innerText||''"))[:900]
    out[name]={"meta":meta,"probe":probe,"incon":incon}
    print("RESULT %-20s %s | %s" % (name, meta, json.dumps(probe,ensure_ascii=False)),flush=True)
    if incon: print("  INCON: "+incon.replace("\n"," | "),flush=True)
bad=[n for n in out if "0 " not in out[n]["meta"][:3]]
print(">>> bad contexts: %s <<<" % (bad if bad else "NONE all 0"),flush=True)
print("FFVERIFYDONE",flush=True)
try: b.close()
except Exception: pass
try: proc.terminate()
except Exception: pass
