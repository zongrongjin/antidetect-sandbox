#!/usr/bin/env python3
"""Android Chrome surface follow-up. Folded into patches/fp_full.diff.

apply.sh no longer runs this. Keep for upgrading an older tree that already
has a pre-android-surface fp_full.diff.

Pixel 3 Chrome 151 gold (2026-08-28 probe upload):
  chrome keys = loadTimes,csi  ('app' in chrome === false)
  plugins=[], mimeTypes=[], pdfViewerEnabled=false
  connection.type=wifi on the prototype

plugins / pdfViewer / connection already live in the DS6797 android-surface
tree. This patcher adds the remaining chrome.app hide, and sets the Android
pdfViewerEnabled default to false (explicit JSON still wins).

Usage: python3 scripts/patch_android_surface.py <chromium/src>
Idempotent via BROWSER_FINGERPRINT_ANDROID_SURFACE_APP.
"""
from __future__ import annotations

import pathlib
import sys

MARKER = "BROWSER_FINGERPRINT_ANDROID_SURFACE_APP"


def die(msg: str) -> None:
    print("!!", msg)
    sys.exit(1)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: pathlib.Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_chrome_app(src: pathlib.Path) -> None:
    path = src / "extensions/renderer/native_extension_bindings_system.cc"
    text = read(path)
    if MARKER in text:
        print("skip", path)
        return

    inc = (
        '#include "base/json/json_reader.h"\n'
        '#include "third_party/blink/public/common/renderer_preferences/'
        'renderer_preferences.h"\n'
        '#include "third_party/blink/public/web/web_view.h"\n'
    )
    needle = '#include "third_party/blink/public/web/web_local_frame.h"\n'
    if needle not in text:
        die("web_local_frame.h include not found")
    text = text.replace(needle, needle + inc, 1)

    helper = r'''
bool HideChromeAppForFingerprint(ScriptContext* context) {
  // BROWSER_FINGERPRINT_ANDROID_SURFACE_APP: Android/iOS Chrome has
  // window.chrome.loadTimes/csi and no chrome.app. Desktop ENABLE_PLATFORM_APPS
  // otherwise injects app onto every webpage.
  if (!context)
    return false;
  blink::WebLocalFrame* frame = context->web_frame();
  if (!frame || !frame->View())
    return false;
  const std::string& fp = frame->View()->GetRendererPreferences().fingerprint;
  if (fp.empty())
    return false;
  std::optional<base::Value> parsed =
      base::JSONReader::Read(fp, base::JSON_PARSE_RFC);
  if (!parsed || !parsed->is_dict())
    return false;
  const base::DictValue& d = parsed->GetDict();
  if (const std::string* plat = d.FindString("uaPlatform")) {
    if (*plat == "Android" || *plat == "iOS")
      return true;
  }
  if (const std::string* ua = d.FindString("userAgent")) {
    if (ua->find("Android") != std::string::npos ||
        ua->find("iPhone") != std::string::npos ||
        ua->find("iPad") != std::string::npos) {
      return true;
    }
  }
  return false;
}

'''
    features = "const std::string_view kWebAvailableFeatures[] = {"
    if features not in text:
        die("kWebAvailableFeatures not found")
    text = text.replace(features, helper + features, 1)

    old = """        // chrome.app is exposed to all webpages, we ignore it for this check.
        if (feature_name != "app") {
          is_any_feature_available_to_page = true;
        }
        if (!set_accessor(feature_name)) {"""
    new = """        // chrome.app is exposed to all webpages, we ignore it for this check.
        if (feature_name == "app" && HideChromeAppForFingerprint(context)) {
          continue;
        }
        if (feature_name != "app") {
          is_any_feature_available_to_page = true;
        }
        if (!set_accessor(feature_name)) {"""
    if old not in text:
        die("webpage chrome.app registration loop not found")
    text = text.replace(old, new, 1)
    write(path, text)


def patch_connection_type(src: pathlib.Path) -> None:
    path = src / (
        "third_party/blink/renderer/modules/netinfo/network_information.cc"
    )
    text = read(path)
    marker = "BROWSER_FINGERPRINT_ANDROID_SURFACE_CONN_TYPE"
    if marker in text:
        print("skip", path, "type()")
        return
    old = """V8ConnectionType NetworkInformation::type() const {
  if (RuntimeEnabledFeatures::NetInfoConstantTypeEnabled()) {
    return V8ConnectionType(V8ConnectionType::Enum::kUnknown);
  }"""
    new = """V8ConnectionType NetworkInformation::type() const {
  // %s: Android Chrome exposes connection.type (wifi/cellular).
  // Desktop NetInfoConstantType would otherwise force "unknown" → BMP "null".
  if (std::optional<base::Value> profile =
          FpNetInfoProfile(GetExecutionContext())) {
    const base::Value* conn = profile->GetDict().Find("connection");
    if (conn && conn->is_dict()) {
      if (const std::string* ty = conn->GetDict().FindString("type")) {
        if (*ty == "wifi")
          return V8ConnectionType(V8ConnectionType::Enum::kWifi);
        if (*ty == "cellular")
          return V8ConnectionType(V8ConnectionType::Enum::kCellular);
        if (*ty == "ethernet")
          return V8ConnectionType(V8ConnectionType::Enum::kEthernet);
        if (*ty == "none")
          return V8ConnectionType(V8ConnectionType::Enum::kNone);
        if (*ty == "bluetooth")
          return V8ConnectionType(V8ConnectionType::Enum::kBluetooth);
        if (*ty == "wimax")
          return V8ConnectionType(V8ConnectionType::Enum::kWimax);
        if (*ty == "other")
          return V8ConnectionType(V8ConnectionType::Enum::kOther);
        if (*ty == "unknown")
          return V8ConnectionType(V8ConnectionType::Enum::kUnknown);
      }
    }
  }
  if (RuntimeEnabledFeatures::NetInfoConstantTypeEnabled()) {
    return V8ConnectionType(V8ConnectionType::Enum::kUnknown);
  }""" % marker
    if old not in text:
        die("NetworkInformation::type() not found")
    text = text.replace(old, new, 1)
    write(path, text)


def patch_pdf_viewer_default(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/modules/plugins/navigator_plugins.cc"
    text = read(path)
    marker = "BROWSER_FINGERPRINT_ANDROID_SURFACE_PDF_DEFAULT_FALSE"
    if marker in text:
        print("skip", path)
        return
    old = """          const std::string* ua = d.FindString("uaPlatform");
          if (ua && (*ua == "Android" || *ua == "iOS"))
            return true;"""
    new = """          const std::string* ua = d.FindString("uaPlatform");
          // Pixel 3 Chrome 151: pdfViewerEnabled is false with empty plugins.
          // Explicit pdfViewerEnabled in JSON still wins above.
          if (ua && (*ua == "Android" || *ua == "iOS"))
            return false;  // %s""" % marker
    if old not in text:
        print("warn: pdfViewer Android default not found (tree may predate android-surface)")
        return
    text = text.replace(old, new, 1)
    write(path, text)


def patch_webview_runtime_features(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/core/exported/web_view_impl.cc"
    text = read(path)
    marker = "BROWSER_FINGERPRINT_ANDROID_SURFACE_RUNTIME"
    if marker in text:
        print("skip", path)
        return
    old = """      if (const std::string* tz = d.FindString("timezone");
          tz && !tz->empty()) {
        String tz_str = String::FromUtf8(std::string_view(*tz));
        static base::NoDestructor<
            std::unique_ptr<TimeZoneController::TimeZoneOverride>>
            tz_handle;
        if (*tz_handle) {
          (*tz_handle)->change(tz_str);
        } else {
          auto result = TimeZoneController::SetTimeZoneOverride(tz_str);
          if (result.handle)
            *tz_handle = std::move(result.handle);
        }
      }
    }
  }"""
    new = """      if (const std::string* tz = d.FindString("timezone");
          tz && !tz->empty()) {
        String tz_str = String::FromUtf8(std::string_view(*tz));
        static base::NoDestructor<
            std::unique_ptr<TimeZoneController::TimeZoneOverride>>
            tz_handle;
        if (*tz_handle) {
          (*tz_handle)->change(tz_str);
        } else {
          auto result = TimeZoneController::SetTimeZoneOverride(tz_str);
          if (result.handle)
            *tz_handle = std::move(result.handle);
        }
      }
      // %s: Linux desktop builds leave NetInfoDownlinkMax experimental, so
      // connection.type is missing from IDL. Android Chrome has it (wifi).
      // maxTouchPoints>0 turns on ontouchstart IDL (not addEventListener).
      const std::string* plat = d.FindString("uaPlatform");
      const base::Value* conn = d.Find("connection");
      if ((plat && (*plat == "Android" || *plat == "iOS")) ||
          (conn && conn->is_dict() && conn->GetDict().FindString("type"))) {
        WebRuntimeFeatures::EnableFeatureFromString("NetInfoDownlinkMax", true);
      }
      if (std::optional<int> mtp = d.FindInt("maxTouchPoints");
          mtp && *mtp > 0) {
        WebRuntimeFeatures::EnableFeatureFromString(
            "TouchEventFeatureDetection", true);
      }
    }
  }""" % marker
    if old not in text:
        die("UpdateRendererPreferences timezone fingerprint block not found")
    if "runtime_enabled_features.h" not in text:
        needle = '#include "third_party/blink/renderer/platform/runtime_enabled_features.h"\n'
        alt = '#include "third_party/blink/renderer/platform/scheduler/public/thread.h"\n'
        if needle.strip() in text:
            pass
        elif alt in text:
            text = text.replace(alt, needle + alt, 1)
        else:
            die("could not insert runtime_enabled_features.h")
    text = text.replace(old, new, 1)
    write(path, text)


def patch_webshare(src: pathlib.Path) -> None:
    """Expose native navigator.share on Linux android-surface.

    Chrome only EnableWebShare() on Android/Win/Mac/ChromeOS, so Linux magai
    reports typeof navigator.share === 'undefined'. PX records
    `function share() { [native code] }` on real Android/Win Chrome.
    Do not polyfill this in page JS — toString would not be native.
    """
    marker = "BROWSER_FINGERPRINT_ANDROID_SURFACE_WEBSHARE"

    renderer = src / "chrome/renderer/chrome_content_renderer_client.cc"
    text = read(renderer)
    if marker in text:
        print("skip", renderer)
    else:
        old = """// Web Share is conditionally enabled here in chrome/, to avoid it
// being made available in WebView or Linux.
#if BUILDFLAG(IS_ANDROID) || BUILDFLAG(IS_CHROMEOS) || BUILDFLAG(IS_WIN) || \\
    BUILDFLAG(IS_MAC)
  blink::WebRuntimeFeatures::EnableWebShare(true);
#endif"""
        new = """// Web Share is conditionally enabled here in chrome/, to avoid it
// being made available in WebView or stock Linux.
// %s: magai android-surface is a Linux desktop build that impersonates
// Android Chrome, which exposes native navigator.share.
#if BUILDFLAG(IS_ANDROID) || BUILDFLAG(IS_CHROMEOS) || BUILDFLAG(IS_WIN) || \\
    BUILDFLAG(IS_MAC) || BUILDFLAG(IS_LINUX)
  blink::WebRuntimeFeatures::EnableWebShare(true);
#endif""" % marker
        if old not in text:
            die("EnableWebShare block not found in chrome_content_renderer_client.cc")
        write(renderer, text.replace(old, new, 1))

    view = src / "third_party/blink/renderer/core/exported/web_view_impl.cc"
    text = read(view)
    if marker in text:
        print("skip", view)
        return
    needle = 'WebRuntimeFeatures::EnableFeatureFromString("NetInfoDownlinkMax", true);'
    if needle not in text:
        die("NetInfoDownlinkMax enable not found; apply android-surface runtime patch first")
    insert = (
        needle
        + '\n        // %s: Android/Win Chrome expose native navigator.share.\n'
          '        WebRuntimeFeatures::EnableFeatureFromString("WebShare", true);'
        % marker
    )
    if insert not in text:
        text = text.replace(needle, insert, 1)
        write(view, text)


def patch_apply_webprefs_touch(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/core/exported/web_view_impl.cc"
    text = read(path)
    marker = "BROWSER_FINGERPRINT_ANDROID_SURFACE_TOUCH_PREF"
    if marker in text:
        print("skip", path, "ApplyWebPreferences")
        return
    old = """  RuntimeEnabledFeatures::SetTouchEventFeatureDetectionEnabled(
      prefs.touch_event_feature_detection_enabled);
  settings->SetMaxTouchPoints(prefs.pointer_events_max_touch_points);"""
    new = """  RuntimeEnabledFeatures::SetTouchEventFeatureDetectionEnabled(
      prefs.touch_event_feature_detection_enabled);
  // %s: desktop WebPreferences force detection off after fingerprint
  // enable; keep ontouchstart on window when maxTouchPoints>0.
  {
    const std::string& fp =
        web_view_impl->GetRendererPreferences().fingerprint;
    if (!fp.empty()) {
      std::optional<base::Value> parsed =
          base::JSONReader::Read(fp, base::JSON_PARSE_RFC);
      if (parsed && parsed->is_dict()) {
        if (std::optional<int> mtp =
                parsed->GetDict().FindInt("maxTouchPoints");
            mtp && *mtp > 0) {
          RuntimeEnabledFeatures::SetTouchEventFeatureDetectionEnabled(true);
        }
      }
    }
  }
  settings->SetMaxTouchPoints(prefs.pointer_events_max_touch_points);""" % marker
    if old not in text:
        die("ApplyWebPreferences touch detection assignment not found")
    text = text.replace(old, new, 1)
    write(path, text)


def patch_mediacapture_feature(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/core/exported/web_view_impl.cc"
    text = read(path)
    if 'EnableFeatureFromString("MediaCapture"' in text:
        print("skip", path, "MediaCapture")
        return
    old = 'WebRuntimeFeatures::EnableFeatureFromString("NetInfoDownlinkMax", true);'
    new = """WebRuntimeFeatures::EnableFeatureFromString("NetInfoDownlinkMax", true);
        WebRuntimeFeatures::EnableFeatureFromString("MediaCapture", true);"""
    if old not in text:
        die("NetInfoDownlinkMax enable line not found for MediaCapture")
    text = text.replace(old, new, 1)
    write(path, text)


def patch_memory_info(src: pathlib.Path) -> None:
    hdr = src / "third_party/blink/renderer/core/timing/memory_info.h"
    htext = read(hdr)
    if "ApplyFingerprint" in htext:
        print("skip", hdr)
    else:
        old = """  explicit MemoryInfo(Precision precision);

  uint64_t totalJSHeapSize() const { return info_.total_js_heap_size; }"""
        new = """  explicit MemoryInfo(Precision precision);

  // BROWSER_FINGERPRINT: override jsHeapSizeLimit from the context fingerprint.
  static Precision PrecisionFromFingerprint(ExecutionContext* context,
                                            bool locked_to_site);
  void ApplyFingerprint(ExecutionContext* context);

  uint64_t totalJSHeapSize() const { return info_.total_js_heap_size; }"""
        if old not in htext:
            die("MemoryInfo constructor not found")
        if "execution_context.h" not in htext:
            htext = htext.replace(
                '#include "third_party/blink/renderer/platform/bindings/script_wrappable.h"\n',
                '#include "third_party/blink/renderer/core/execution_context/execution_context.h"\n'
                '#include "third_party/blink/renderer/platform/bindings/script_wrappable.h"\n',
                1,
            )
        write(hdr, htext.replace(old, new, 1))

    path = src / "third_party/blink/renderer/core/timing/memory_info.cc"
    text = read(path)
    if "MemoryInfo::ApplyFingerprint" in text:
        print("skip", path)
        return
    inc = """#include "base/json/json_reader.h"
#include "base/values.h"
#include "third_party/blink/renderer/core/exported/web_view_impl.h"
#include "third_party/blink/renderer/core/execution_context/execution_context.h"
#include "third_party/blink/renderer/core/frame/local_dom_window.h"
#include "third_party/blink/renderer/core/frame/web_local_frame_impl.h"
#include "third_party/blink/renderer/core/workers/worker_global_scope.h"
"""
    needle = '#include "third_party/blink/renderer/core/timing/memory_info.h"\n'
    if needle not in text:
        die("memory_info.cc include not found")
    text = text.replace(needle, needle + inc, 1)
    impl = r'''
static std::optional<base::Value> FpMemoryProfile(ExecutionContext* ec) {
  if (!ec)
    return std::nullopt;
  std::string fp;
  if (auto* window = DynamicTo<LocalDOMWindow>(ec)) {
    if (!window->GetFrame())
      return std::nullopt;
    WebLocalFrameImpl* wf = WebLocalFrameImpl::FromFrame(window->GetFrame());
    if (!wf || !wf->ViewImpl())
      return std::nullopt;
    fp = wf->ViewImpl()->GetRendererPreferences().fingerprint;
  } else if (auto* wgs = DynamicTo<WorkerGlobalScope>(ec)) {
    fp = wgs->Fingerprint().Utf8();
  }
  if (fp.empty())
    return std::nullopt;
  std::optional<base::Value> v =
      base::JSONReader::Read(fp, base::JSON_PARSE_RFC);
  if (!v || !v->is_dict())
    return std::nullopt;
  return v;
}

MemoryInfo::Precision MemoryInfo::PrecisionFromFingerprint(
    ExecutionContext* context,
    bool locked_to_site) {
  // Android Chrome bucketizes performance.memory; site isolation on a desktop
  // build would otherwise report precise heap sizes and leak the host.
  if (std::optional<base::Value> profile = FpMemoryProfile(context)) {
    const std::string* plat = profile->GetDict().FindString("uaPlatform");
    if (plat && *plat == "Android")
      return Precision::kBucketized;
  }
  return locked_to_site ? Precision::kPrecise : Precision::kBucketized;
}

void MemoryInfo::ApplyFingerprint(ExecutionContext* context) {
  std::optional<base::Value> profile = FpMemoryProfile(context);
  if (!profile)
    return;
  const base::Value* v = profile->GetDict().Find("jsHeapSizeLimit");
  if (!v)
    return;
  if (std::optional<int> i = v->GetIfInt()) {
    info_.js_heap_size_limit = static_cast<size_t>(*i);
  } else if (std::optional<double> f = v->GetIfDouble()) {
    info_.js_heap_size_limit = static_cast<size_t>(*f);
  }
}

'''
    text = text.replace(
        "MemoryInfo::MemoryInfo(Precision precision) {",
        impl + "MemoryInfo::MemoryInfo(Precision precision) {",
        1,
    )
    write(path, text)


def patch_window_performance_memory(src: pathlib.Path) -> None:
    path = src / (
        "third_party/blink/renderer/core/timing/window_performance.cc"
    )
    text = read(path)
    if "PrecisionFromFingerprint" in text:
        print("skip", path)
        return
    old = """  const bool is_locked_to_site = Platform::Current()->IsLockedToSite();
  auto* memory_info = MakeGarbageCollected<MemoryInfo>(
      is_locked_to_site ? MemoryInfo::Precision::kPrecise
                        : MemoryInfo::Precision::kBucketized);
  // Record Web Memory UKM.
  const uint64_t kBytesInKB = 1024;
  auto* execution_context = ExecutionContext::From(script_state);"""
    new = """  const bool is_locked_to_site = Platform::Current()->IsLockedToSite();
  auto* execution_context = ExecutionContext::From(script_state);
  auto* memory_info = MakeGarbageCollected<MemoryInfo>(
      MemoryInfo::PrecisionFromFingerprint(execution_context,
                                           is_locked_to_site));
  memory_info->ApplyFingerprint(execution_context);
  // Record Web Memory UKM.
  const uint64_t kBytesInKB = 1024;"""
    if old not in text:
        die("WindowPerformance::memory body not found")
    write(path, text.replace(old, new, 1))


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_android_surface.py <chromium/src>")
    src = pathlib.Path(sys.argv[1]).resolve()
    if not (src / "BUILD.gn").is_file():
        die(f"not a chromium src tree: {src}")
    patch_chrome_app(src)
    patch_pdf_viewer_default(src)
    patch_connection_type(src)
    patch_webview_runtime_features(src)
    patch_webshare(src)
    patch_apply_webprefs_touch(src)
    patch_mediacapture_feature(src)
    patch_memory_info(src)
    patch_window_performance_memory(src)
    print("ok")


if __name__ == "__main__":
    main()
