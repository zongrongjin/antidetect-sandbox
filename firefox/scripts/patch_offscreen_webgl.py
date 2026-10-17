#!/usr/bin/env python3
# Incremental kernel fix: window OffscreenCanvas WebGL fingerprint +
# keep masked VENDOR/RENDERER as Mozilla.
from pathlib import Path
import sys

p = Path(sys.argv[1] if len(sys.argv) > 1 else
         "/root/ff/firefox-152.0.5/dom/canvas/ClientWebGLContext.cpp")
s = p.read_text(encoding="utf-8")
orig = s
marker = "BROWSER_FINGERPRINT_OFFSCREEN_WEBGL"
if marker in s:
    print("already patched")
    sys.exit(0)

inc = '#include "mozilla/dom/BrowsingContext.h"  // BROWSER_FINGERPRINT\n'
inc2 = (
    '#include "mozilla/dom/BrowsingContext.h"  // BROWSER_FINGERPRINT\n'
    '#include "mozilla/dom/OffscreenCanvas.h"  // BROWSER_FINGERPRINT_OFFSCREEN_WEBGL\n'
)
if inc not in s:
    sys.exit("include anchor missing")
s = s.replace(inc, inc2, 1)

old_fp = '''static nsString FpRbProfileGl(mozilla::dom::Document* aDoc) {
  if (aDoc) {
    if (mozilla::dom::BrowsingContext* bc = aDoc->GetBrowsingContext()) {
      if (mozilla::dom::BrowsingContext* top = bc->Top()) {
        nsString j = top->GetFingerprintProfile();
        if (!j.IsEmpty()) return j;
      }
    }
  }
  // //BROWSER_FINGERPRINT: OffscreenCanvas WebGL in worker 无 doc/BC，从快照取
  if (mozilla::dom::WorkerPrivate* wp =
          mozilla::dom::GetCurrentThreadWorkerPrivate()) {
    return nsString(wp->GetFingerprintProfile());
  }
  return nsString();
}'''

new_fp = '''static nsString FpRbProfileGl(
    mozilla::dom::Document* aDoc,
    mozilla::dom::OffscreenCanvas* aOffscreen = nullptr) {
  if (aDoc) {
    if (mozilla::dom::BrowsingContext* bc = aDoc->GetBrowsingContext()) {
      if (mozilla::dom::BrowsingContext* top = bc->Top()) {
        nsString j = top->GetFingerprintProfile();
        if (!j.IsEmpty()) return j;
      }
    }
  }
  // Window OffscreenCanvas has no HTML owner doc; walk the canvas global.
  if (aOffscreen) {
    nsString j;
    aOffscreen->CopyFingerprintProfile(j);
    if (!j.IsEmpty()) {
      return j;
    }
  }
  // Worker OffscreenCanvas: snapshot on WorkerPrivate.
  if (mozilla::dom::WorkerPrivate* wp =
          mozilla::dom::GetCurrentThreadWorkerPrivate()) {
    return nsString(wp->GetFingerprintProfile());
  }
  return nsString();
}'''

if old_fp not in s:
    sys.exit("FpRbProfileGl block not found")
s = s.replace(old_fp, new_fp, 1)

old_fn = '''      nsString fpj = FpRbProfileGl(GetOwnerDoc()); nsString v;'''
new_fn = '''      nsString fpj = FpRbProfileGl(GetOwnerDoc(), mOffscreenCanvas); nsString v;'''
if old_fn not in s:
    sys.exit("fnFpWebgl lookup not found")
s = s.replace(old_fn, new_fn, 1)

old_r = '''      case LOCAL_GL_RENDERER: {
        // BROWSER_FINGERPRINT: masked RENDERER 也走画像覆盖，否则漏出宿主机
        // 真实(ANGLE/D3D)渲染器，与安卓画像及下面 UNMASKED_* 覆盖冲突。
        if (Maybe<std::string> fpv = fnFpWebgl("webglRenderer")) { ret = fpv; break; }
        bool allowRenderer = StaticPrefs::webgl_enable_renderer_query();'''
new_r = '''      case LOCAL_GL_RENDERER: {
        // Fingerprint present: keep Firefox-masked constant. Do not leak
        // host llvmpipe and do not put ANGLE on this slot (UNMASKED only).
        if (fnFpWebgl("webglRenderer") || fnFpWebgl("webglVendor")) {
          ret = Some(std::string{"Mozilla"});
          break;
        }
        bool allowRenderer = StaticPrefs::webgl_enable_renderer_query();'''
if old_r not in s:
    # Already converted to Mozilla-masked form.
    if 'ret = Some(std::string{"Mozilla"});' in s and "case LOCAL_GL_RENDERER:" in s:
        print("LOCAL_GL_RENDERER already Mozilla-masked")
    else:
        sys.exit("LOCAL_GL_RENDERER override not found")
else:
    s = s.replace(old_r, new_r, 1)

# Capabilities / shader / readPixels should also see window OffscreenCanvas.
s = s.replace(
    "static bool FpwSetCapability(ClientWebGLContext* aContext, Document* aDocument,\n"
    "                             JSContext* aCx, bool aWebGL2, GLenum aPname,\n"
    "                             JS::MutableHandle<JS::Value> aRetval,\n"
    "                             ErrorResult& aRv) {\n"
    "  nsString fingerprint = FpRbProfileGl(aDocument);",
    "static bool FpwSetCapability(ClientWebGLContext* aContext, Document* aDocument,\n"
    "                             JSContext* aCx, bool aWebGL2, GLenum aPname,\n"
    "                             JS::MutableHandle<JS::Value> aRetval,\n"
    "                             ErrorResult& aRv) {\n"
    "  nsString fingerprint = FpRbProfileGl(aDocument, aContext->OffscreenCanvas());",
    1,
)

# OffscreenCanvas() getter may not exist — use mOffscreenCanvas from methods,
# not from static FpwSetCapability via aContext. ClientWebGLContext likely
# doesn't expose OffscreenCanvas(). Revert that if I added it — check header.

if s != orig and "aContext->OffscreenCanvas()" in s:
    # Don't use a missing getter. Keep FpwSetCapability on document/worker only;
    # GetParameter strings are the DataDome path.
    s = s.replace(
        "  nsString fingerprint = FpRbProfileGl(aDocument, aContext->OffscreenCanvas());",
        "  nsString fingerprint = FpRbProfileGl(aDocument);",
        1,
    )

if s == orig:
    sys.exit("no changes applied")
p.write_text(s, encoding="utf-8")
print("patched", p)
print("offscreen_lookup", "GetOwnerDoc(), mOffscreenCanvas" in s)
print("masked_renderer_fp", 'fnFpWebgl("webglRenderer")) { ret = fpv; break; }\n        bool allowRenderer' not in s)
