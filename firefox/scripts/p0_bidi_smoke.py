# -*- coding: utf-8 -*-
"""P0 冒烟：自编 Firefox 152 起 headless + WebDriver BiDi 连通，读基本值。
在云机上跑：python3 p0_bidi_smoke.py
依赖：~/browser_controller（包）+ websocket-client。"""
import sys, time
sys.path.insert(0, "/home/ubuntu")          # browser_controller 包的父目录
import browser_controller as bc

FF = "/home/ubuntu/firefox-152.0.5/obj-release/dist/bin/firefox"

print("launching self-built Firefox 152 (headless, BiDi)...")
b = bc.launch(FF, extra_args=["-headless"], timeout=90)
try:
    b.get("data:text/html,<title>smoke</title><h1>hi</h1>", timeout=30)
    print("  title    :", b.title)
    print("  UA       :", b.user_agent)
    print("  platform :", b.run_js("navigator.platform"))
    print("  webdriver:", b.run_js("navigator.webdriver"))
    print("  langs    :", b.run_js("navigator.languages.join(',')"))
    print("P0 SMOKE OK")
finally:
    b.close()
