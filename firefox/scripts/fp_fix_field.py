# -*- coding: utf-8 -*-
# 用 chr() 规避一切转义歧义地修 FIELD 续行行。
import os
p = os.path.expanduser("~/firefox-152.0.5/docshell/base/BrowsingContext.h")
s = open(p, encoding="utf-8").read()
BS = chr(92)   # 反斜杠
NL = chr(10)   # 真换行
# 当前坏样子：一行含  FIELD(FingerprintProfile, nsString) <BS>n  /* Specifies...
bad = "  FIELD(FingerprintProfile, nsString) " + BS + "n  /* Specifies if this BC has loaded"
good = "  FIELD(FingerprintProfile, nsString) " + BS + NL + "  /* Specifies if this BC has loaded"
if bad in s:
    s = s.replace(bad, good, 1)
    open(p, "w", encoding="utf-8").write(s)
    print("FIELD_FIXED")
elif ("  FIELD(FingerprintProfile, nsString) " + BS + NL) in s:
    print("FIELD_ALREADY_OK")
else:
    print("FIELD_PATTERN_NOT_FOUND")
