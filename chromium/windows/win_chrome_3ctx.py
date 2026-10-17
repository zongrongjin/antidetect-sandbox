# -*- coding: utf-8 -*-
import sys, time, json, os
for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'): os.environ.pop(k, None)
os.environ['NO_PROXY']='*'; os.environ['no_proxy']='*'
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
sys.path.insert(0, "C:\\")
import browser_controller as bc
CHROME = r"C:\src\src\out\Default\chrome.exe"
URL = "https://secdev.solvermarket.com/fp-d7c41884426bc076/index.html"
BR = [{"b":"Not(A:Brand","v":"24"},{"b":"Chromium","v":"151"},{"b":"Google Chrome","v":"151"}]
FB = [{"b":"Not(A:Brand","v":"24.0.0.0"},{"b":"Chromium","v":"151.0.7907.0"},{"b":"Google Chrome","v":"151.0.7907.0"}]
def P(ua,plat,uap,hc,langs,loc,tz,sw,sh,glv,glr,seed):
    return {"userAgent":ua,"platform":plat,"uaPlatform":uap,"hardwareConcurrency":hc,"acceptLanguages":langs,
            "locale":loc,"timezone":tz,"screenWidth":sw,"screenHeight":sh,"webglVendor":glv,"webglRenderer":glr,
            "uaBrands":BR,"uaFullBrands":FB,"readbackSeed":seed}
PROFILES={
 "ctxA_FR_NVIDIA_Win":P("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36","Win32","Windows",16,"fr-FR,fr","fr-FR","Europe/Paris",2560,1440,"Google Inc. (NVIDIA)","ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)",111111),
 "ctxB_JP_Apple_Mac":P("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36","MacIntel","macOS",10,"ja-JP,ja","ja-JP","Asia/Tokyo",1728,1117,"Google Inc. (Apple)","ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",222222),
 "ctxC_US_AMD_Linux":P("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36","Linux x86_64","Linux",12,"en-US,en","en-US","America/New_York",1920,1080,"Google Inc. (AMD)","ANGLE (AMD, AMD Radeon RX 6800 XT, OpenGL 4.6)",333333),
}
PROBE=r"""(function(){var o={};o.platform=navigator.platform;o.lang=navigator.language;o.tz=Intl.DateTimeFormat().resolvedOptions().timeZone;o.hc=navigator.hardwareConcurrency;try{o.uaDataPlat=navigator.userAgentData.platform;}catch(e){o.uaDataPlat='err';}o.numFmt=(1234567.89).toLocaleString();return JSON.stringify(o);})()"""
def wait_det(c,secs=90):
    for _ in range(secs//3):
        time.sleep(3)
        try:
            st=c.run_js("(function(){var s=document.querySelectorAll('.st');if(!s.length)return 'nost';var a=0;for(var i=0;i<s.length;i++){if(/wait|run/.test(s[i].className))a++;}return a;})()")
        except Exception: st='err'
        if str(st)=='0': return True
    return False
print("LAUNCHING", flush=True)
b=bc.launch(CHROME, extra_args=["--no-sandbox","--disable-dev-shm-usage","--headless=new","--disable-gpu","--password-store=basic"], timeout=120)
print("LAUNCHED", flush=True)
res={}
for name,prof in PROFILES.items():
    c=b.new_context(fingerprint=prof)
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
    out[name]={"meta":meta,"probe":probe}
    print("RESULT %-20s %s | %s" % (name, meta, json.dumps(probe,ensure_ascii=False)),flush=True)
bad=[n for n in out if "0 " not in out[n]["meta"][:3]]
print(">>> bad contexts: %s <<<" % (bad if bad else "NONE all 0"),flush=True)
print("CHROMEVERIFYDONE",flush=True)
b.close()
