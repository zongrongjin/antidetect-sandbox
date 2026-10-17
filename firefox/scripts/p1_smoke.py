# -*- coding: utf-8 -*-
import sys, time, json
sys.path.insert(0, "/home/ubuntu")
import browser_controller as bc
FF = "/home/ubuntu/firefox-152.0.5/obj-release/dist/bin/firefox"
b = bc.launch(FF, extra_args=["-headless"], timeout=120)
try:
    b.get("data:text/html,<title>t1</title><h1>hi</h1>", timeout=30)
    print("baseline platform:", b.run_js("navigator.platform"), "| webdriver:", b.run_js("navigator.webdriver"))
    fp = json.dumps({"platform": "Win32", "userAgent": "TEST-UA-152"})
    r = b.run("moz:fingerprint.setContextOverrides", {"fingerprint": fp}, timeout=15)
    print("setContextOverrides ->", r)
    print("same-doc platform:", b.run_js("navigator.platform"), "(DidSet 清缓存后同文档)")
    b.get("data:text/html,<title>t2</title>", timeout=30)
    print("after-nav platform:", b.run_js("navigator.platform"))
    print("RESULT platform_override =", b.run_js("navigator.platform") == "Win32")
finally:
    b.close()
