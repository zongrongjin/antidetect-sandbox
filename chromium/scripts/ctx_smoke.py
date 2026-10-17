import json,os,subprocess,sys,time,urllib.request
for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'): os.environ.pop(k,None)
os.environ['NO_PROXY']='*'
os.environ['PYTHONUTF8']='1'
from websocket import create_connection
CHROME=r'D:\src\src\out\Default\chrome.exe'
OUT=r'D:\src\src\out\Default'
DBG=9331
PROF=r'C:\Users\Administrator\ctx_smoke_profile'
FA={'userAgent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36','timezone':'Europe/Paris'}
FB={'userAgent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36','timezone':'Asia/Tokyo'}
I=[0]
def log(m):
    print(m,flush=True)
def cmd(ws,m,p=None,s=None):
    I[0]+=1
    x={'id':I[0],'method':m,'params':p or {}}
    if s: x['sessionId']=s
    ws.send(json.dumps(x))
    while True:
        r=json.loads(ws.recv())
        if r.get('id')==I[0]:
            if 'error' in r: raise RuntimeError('%s %s'%(m,r['error']))
            return r.get('result',{})
def ev(ws,s,e):
    return cmd(ws,'Runtime.evaluate',{'expression':e,'returnByValue':True},s).get('result',{}).get('value')
def ctx(ws,fp,px=None):
    c=cmd(ws,'Target.createBrowserContext')['browserContextId']
    t=cmd(ws,'Target.createTarget',{'url':'about:blank','browserContextId':c})['targetId']
    s=cmd(ws,'Target.attachToTarget',{'targetId':t,'flatten':True})['sessionId']
    pr={}
    if fp is not None: pr['fingerprint']=json.dumps(fp)
    if px is not None: pr['proxy']=px
    if pr: cmd(ws,'Context.setContextOverrides',pr,s)
    cmd(ws,'Runtime.enable',None,s)
    cmd(ws,'Page.navigate',{'url':'data:text/html,<title>x</title>'},s)
    time.sleep(0.5)
    return s
subprocess.call('taskkill /F /IM chrome.exe /T',shell=True)
time.sleep(1)
os.makedirs(PROF,exist_ok=True)
args=[CHROME,'--password-store=basic','--no-first-run','--disable-extensions','--disable-gpu','--remote-allow-origins=*','--remote-debugging-address=127.0.0.1','--remote-debugging-port=%d'%DBG,'--user-data-dir=%s'%PROF,'about:blank']
log('launch')
p=subprocess.Popen(args,cwd=OUT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
fails=[]
try:
    bws=None
    last=None
    for _ in range(50):
        try:
            bws=json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version'%DBG,timeout=1))['webSocketDebuggerUrl']; break
        except Exception as e:
            last=e; time.sleep(0.4)
    if not bws:
        log('FAIL no debug port '+str(last)); sys.exit(1)
    log('OK debug port')
    ws=create_connection(bws,max_size=None); ws.settimeout(20)
    probe=ctx(ws,None)
    try:
        cmd(ws,'Context.setContextOverrides',{},probe)
        log('OK Context domain')
    except Exception as e:
        log('FAIL domain '+str(e)); sys.exit(1)
    try:
        cmd(ws,'Fingerprint.setContextOverrides',{'fingerprint':'{}'},probe)
        log('WARN Fingerprint still present')
    except Exception:
        log('OK Fingerprint gone')
    sa=ctx(ws,FA); sb=ctx(ws,FB)
    ua,ub=ev(ws,sa,'navigator.userAgent'),ev(ws,sb,'navigator.userAgent')
    za,zb=ev(ws,sa,'Intl.DateTimeFormat().resolvedOptions().timeZone'),ev(ws,sb,'Intl.DateTimeFormat().resolvedOptions().timeZone')
    log('A '+str(ua)+' '+str(za)); log('B '+str(ub)+' '+str(zb))
    if ua!=FA['userAgent']: fails.append('uaA')
    if ub!=FB['userAgent']: fails.append('uaB')
    if za!='Europe/Paris': fails.append('tzA')
    if zb!='Asia/Tokyo': fails.append('tzB')
    try:
        ctx(ws,FA,{'endpoint':'127.0.0.1:9','username':'u','password':'p'})
        log('OK proxy field')
    except Exception as e:
        log('FAIL proxy '+str(e)); fails.append('proxy')
    log('SMOKE '+('FAIL' if fails else 'PASS')+' '+str(fails))
    sys.exit(1 if fails else 0)
finally:
    try: p.terminate()
    except Exception: pass
    subprocess.call('taskkill /F /IM chrome.exe /T',shell=True)
