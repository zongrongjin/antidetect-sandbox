#!/usr/bin/env python3
"""Apply plugins / pdfViewerEnabled / connection on top of fp_all.diff.

Keyboard API is not shipped by real Firefox; nothing to hide.

Run after scripts/fp_apply.sh. Idempotent: skip if the marker is already present.
Usage: python3 scripts/patch_android_surface.py <firefox-152.0.5>
"""
from __future__ import annotations

import pathlib
import shutil
import sys

MARKER = "BROWSER_FINGERPRINT_ANDROID_SURFACE"
HEADER_REL = "dom/base/FingerprintAndroidSurface.h"


def die(msg: str) -> None:
    print("!!", msg)
    sys.exit(1)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: pathlib.Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def install_header(src: pathlib.Path, here: pathlib.Path) -> None:
    dest = src / HEADER_REL
    incoming = here / "src-new" / HEADER_REL
    if not incoming.is_file():
        die(f"missing {incoming}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(incoming, dest)
    print("copied", dest)


def patch_plugins(src: pathlib.Path) -> None:
    path = src / "dom/base/nsPluginArray.cpp"
    text = read(path)
    if MARKER in text:
        print("skip", path)
    else:
        inc = '#include "FingerprintAndroidSurface.h"\n'
        needle = '#include "nsPluginArray.h"\n'
        if needle not in text:
            die("nsPluginArray.cpp include not found")
        text = text.replace(needle, needle + inc, 1)
        old = """bool nsPluginArray::ForceNoPlugins() {
  return StaticPrefs::pdfjs_disabled() &&
         !nsContentUtils::ShouldResistFingerprinting(
             mWindow ? mWindow->GetDocShell() : nullptr, RFPTarget::PdfjsSpoof);
}"""
        old_alt = """bool nsPluginArray::ForceNoPlugins() { return StaticPrefs::pdfjs_disabled(); }"""
        new = f"""bool nsPluginArray::ForceNoPlugins() {{
  // {MARKER}: 显式 plugins:[] 或 Android/iOS 画像 → 空数组；非空列表仍走原生 5 PDF。
  nsAutoString json;
  if (fp_android_surface::GetJson(mWindow, json) &&
      fp_android_surface::ForceEmptyPlugins(json)) {{
    return true;
  }}
  return StaticPrefs::pdfjs_disabled() &&
         !nsContentUtils::ShouldResistFingerprinting(
             mWindow ? mWindow->GetDocShell() : nullptr, RFPTarget::PdfjsSpoof);
}}"""
        if old in text:
            text = text.replace(old, new, 1)
        elif old_alt in text:
            text = text.replace(old_alt, new, 1)
        else:
            die("nsPluginArray::ForceNoPlugins not found")
        write(path, text)

    mime = src / "dom/base/nsMimeTypeArray.cpp"
    mtext = read(mime)
    if MARKER in mtext:
        print("skip", mime)
        return
    inc = '#include "FingerprintAndroidSurface.h"\n'
    needle = '#include "nsMimeTypeArray.h"\n'
    if needle not in mtext:
        die("nsMimeTypeArray.cpp include not found")
    mtext = mtext.replace(needle, needle + inc, 1)
    old = """bool nsMimeTypeArray::ForceNoPlugins() {
  return StaticPrefs::pdfjs_disabled() &&
         !nsContentUtils::ShouldResistFingerprinting(
             mWindow ? mWindow->GetDocShell() : nullptr, RFPTarget::PdfjsSpoof);
}"""
    old_alt = """bool nsMimeTypeArray::ForceNoPlugins() { return StaticPrefs::pdfjs_disabled(); }"""
    new = f"""bool nsMimeTypeArray::ForceNoPlugins() {{
  // {MARKER}: 与 nsPluginArray 同源，Android/iOS 或 plugins:[] → 空 MIME 面。
  nsAutoString json;
  if (fp_android_surface::GetJson(mWindow, json) &&
      fp_android_surface::ForceEmptyPlugins(json)) {{
    return true;
  }}
  return StaticPrefs::pdfjs_disabled() &&
         !nsContentUtils::ShouldResistFingerprinting(
             mWindow ? mWindow->GetDocShell() : nullptr, RFPTarget::PdfjsSpoof);
}}"""
    if old in mtext:
        mtext = mtext.replace(old, new, 1)
    elif old_alt in mtext:
        mtext = mtext.replace(old_alt, new, 1)
    else:
        die("nsMimeTypeArray::ForceNoPlugins not found")
    write(mime, mtext)


def patch_pdf_viewer(src: pathlib.Path) -> None:
    path = src / "dom/base/Navigator.cpp"
    text = read(path)
    if f"{MARKER}: pdfViewerEnabled" in text:
        print("skip", path)
        return
    inc = '#include "FingerprintAndroidSurface.h"\n'
    if inc not in text:
        needle = '#include "Navigator.h"\n'
        if needle not in text:
            die("Navigator.cpp include not found")
        text = text.replace(needle, needle + inc, 1)
    old = """bool Navigator::PdfViewerEnabled() {
  return !StaticPrefs::pdfjs_disabled() ||
         nsContentUtils::ShouldResistFingerprinting(GetDocShell(),
                                                    RFPTarget::PdfjsSpoof);
}"""
    old_alt = """bool Navigator::PdfViewerEnabled() { return !StaticPrefs::pdfjs_disabled(); }"""
    new = f"""bool Navigator::PdfViewerEnabled() {{
  // {MARKER}: pdfViewerEnabled 显式优先；Android/iOS 缺省 true（空插件 + true）。
  nsAutoString json;
  if (fp_android_surface::GetJson(mWindow, json)) {{
    if (auto override = fp_android_surface::PdfViewerOverride(json)) {{
      return *override;
    }}
  }}
  return !StaticPrefs::pdfjs_disabled() ||
         nsContentUtils::ShouldResistFingerprinting(GetDocShell(),
                                                    RFPTarget::PdfjsSpoof);
}}"""
    if old in text:
        text = text.replace(old, new, 1)
    elif old_alt in text:
        text = text.replace(old_alt, new, 1)
    else:
        die("Navigator::PdfViewerEnabled not found")
    write(path, text)


def patch_connection_idl(src: pathlib.Path) -> None:
    net = src / "dom/webidl/NetworkInformation.webidl"
    ntext = read(net)
    if MARKER in ntext:
        print("skip", net)
    else:
        old = """[Pref="dom.netinfo.enabled",
 Exposed=(Window,Worker)]
interface NetworkInformation : EventTarget {"""
        new = f"""// {MARKER}: per-context Func replaces the global pref so Android 画像能在桌面宿主露出 connection。
[Func="mozilla::dom::network::Connection::Enabled",
 Exposed=(Window,Worker)]
interface NetworkInformation : EventTarget {{"""
        if old not in ntext:
            die("NetworkInformation.webidl Pref block not found")
        write(net, ntext.replace(old, new, 1))

    nav = src / "dom/webidl/Navigator.webidl"
    vtext = read(nav)
    if f"{MARKER}: connection" in vtext:
        print("skip", nav)
    else:
        old = """partial interface Navigator {
  [Throws, Pref="dom.netinfo.enabled"]
  readonly attribute NetworkInformation connection;
};"""
        new = f"""partial interface Navigator {{
  // {MARKER}: connection
  [Throws, Func="mozilla::dom::network::Connection::Enabled"]
  readonly attribute NetworkInformation connection;
}};"""
        if old not in vtext:
            die("Navigator.webidl connection block not found")
        write(nav, vtext.replace(old, new, 1))

    wnav = src / "dom/webidl/WorkerNavigator.webidl"
    wtext = read(wnav)
    if MARKER in wtext:
        print("skip", wnav)
        return
    old = """partial interface WorkerNavigator {
    [Pref="dom.netinfo.enabled", Throws]
    readonly attribute NetworkInformation connection;
};"""
    new = f"""partial interface WorkerNavigator {{
    // {MARKER}
    [Func="mozilla::dom::network::Connection::Enabled", Throws]
    readonly attribute NetworkInformation connection;
}};"""
    if old not in wtext:
        die("WorkerNavigator.webidl connection block not found")
    write(wnav, wtext.replace(old, new, 1))


def patch_connection_cpp(src: pathlib.Path) -> None:
    hdr = src / "dom/network/Connection.h"
    htext = read(hdr)
    if MARKER in htext:
        print("skip", hdr)
    else:
        old_decl = """  ConnectionType Type() const {
    return mShouldResistFingerprinting
               ? static_cast<ConnectionType>(ConnectionType::Unknown)
               : mType;
  }"""
        new_decl = f"""  static bool Enabled(JSContext* aCx, JSObject* aGlobal);

  ConnectionType Type() const;  // {MARKER}"""
        if old_decl not in htext:
            die("Connection.h Type() not found")
        htext = htext.replace(old_decl, new_decl, 1)
        write(hdr, htext)

    path = src / "dom/network/Connection.cpp"
    text = read(path)
    if MARKER in text:
        print("skip", path)
        return
    extra = """#include "../base/FingerprintAndroidSurface.h"
#include "mozilla/StaticPrefs_dom.h"
#include "mozilla/dom/WorkerPrivate.h"
#include "nsCOMPtr.h"
#include "nsPIDOMWindow.h"
#include "nsString.h"
#include "xpcpublic.h"
"""
    needle = '#include "Connection.h"\n'
    if needle not in text:
        die("Connection.cpp include not found")
    text = text.replace(needle, needle + extra, 1)

    impl = f"""
bool Connection::Enabled(JSContext* aCx, JSObject* aGlobal) {{
  // {MARKER}: Android 画像或 connection 对象 → 露出 API；false / iOS → 隐藏；否则跟 pref。
  nsAutoString json;
  bool have = false;
  if (aCx && aGlobal) {{
    if (nsCOMPtr<nsPIDOMWindowInner> win = xpc::WindowOrNull(aGlobal)) {{
      have = mozilla::dom::fp_android_surface::GetJson(win, json);
    }}
  }}
  if (!have) {{
    if (mozilla::dom::WorkerPrivate* wp =
            mozilla::dom::GetCurrentThreadWorkerPrivate()) {{
      json = wp->GetFingerprintProfile();
      have = !json.IsEmpty();
    }}
  }}
  if (have) {{
    using V = mozilla::dom::fp_android_surface::ConnVis;
    V vis = mozilla::dom::fp_android_surface::ConnectionVisibility(json);
    if (vis == V::Hide) {{
      return false;
    }}
    if (vis == V::Show) {{
      return true;
    }}
  }}
  return mozilla::StaticPrefs::dom_netinfo_enabled();
}}

ConnectionType Connection::Type() const {{
  if (mShouldResistFingerprinting) {{
    return static_cast<ConnectionType>(ConnectionType::Unknown);
  }}
  nsAutoString json;
  bool have = false;
  if (nsPIDOMWindowInner* win = GetOwnerWindow()) {{
    have = mozilla::dom::fp_android_surface::GetJson(win, json);
  }}
  if (!have) {{
    if (mozilla::dom::WorkerPrivate* wp =
            mozilla::dom::GetCurrentThreadWorkerPrivate()) {{
      json = wp->GetFingerprintProfile();
      have = !json.IsEmpty();
    }}
  }}
  if (have) {{
    if (auto token = mozilla::dom::fp_android_surface::ConnectionTypeToken(json)) {{
      if (*token == "cellular"_ns) {{
        return ConnectionType::Cellular;
      }}
      if (*token == "wifi"_ns) {{
        return ConnectionType::Wifi;
      }}
      if (*token == "ethernet"_ns) {{
        return ConnectionType::Ethernet;
      }}
      if (*token == "bluetooth"_ns) {{
        return ConnectionType::Bluetooth;
      }}
      if (*token == "none"_ns) {{
        return ConnectionType::None;
      }}
      if (*token == "other"_ns) {{
        return ConnectionType::Other;
      }}
      if (*token == "unknown"_ns) {{
        return ConnectionType::Unknown;
      }}
    }}
  }}
  return mType;
}}

"""
    marker_dtor = "Connection::~Connection() {"
    if marker_dtor not in text:
        die("Connection destructor not found")
    text = text.replace(marker_dtor, impl + marker_dtor, 1)
    write(path, text)


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_android_surface.py <firefox-152.0.5>")
    src = pathlib.Path(sys.argv[1]).resolve()
    here = pathlib.Path(__file__).resolve().parent.parent
    if not (src / "mach").is_file() and not (src / "moz.configure").is_file():
        die(f"not a firefox source tree: {src}")
    install_header(src, here)
    patch_plugins(src)
    patch_pdf_viewer(src)
    patch_connection_idl(src)
    patch_connection_cpp(src)
    print("ANDROID_SURFACE_PATCH_OK")


if __name__ == "__main__":
    main()
