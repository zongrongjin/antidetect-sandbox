#!/usr/bin/env python3
"""formFactors Client Hints + kernel layout viewport.

Folded into patches/fp_full.diff; apply.sh no longer runs this.
Keep for upgrading an older tree that already has a pre-formFactors fp_full.diff.

On top of an older fp_full.diff:
  - Copy formFactors into every UserAgentMetadata overlay (JS + CH + worker).
  - innerWidth/innerHeight and visualViewport follow viewportWidth/Height.
  - WebView Resize so CSS layout / matchMedia / getBoundingClientRect match.

Usage: python3 scripts/patch_formfactors_layout.py <chromium/src>
Idempotent via BROWSER_FINGERPRINT_FORMFACTORS_LAYOUT.
"""
from __future__ import annotations

import pathlib
import sys

MARKER = "BROWSER_FINGERPRINT_FORMFACTORS_LAYOUT"

FF_SNIPPET = r"""
            // %s: UA-CH formFactors (JS high-entropy + sec-ch-ua-form-factors).
            {
              std::vector<std::string> ffs;
              if (const base::ListValue* ffl = fp_d.FindList("formFactors")) {
                for (const base::Value& it : *ffl) {
                  if (const std::string* s = it.GetIfString();
                      s && blink::UserAgentMetadata::IsValidFormFactor(*s)) {
                    ffs.push_back(*s);
                  }
                }
              }
              if (ffs.empty()) {
                bool mobile_ff = false;
                if (std::optional<bool> mob = fp_d.FindBool("mobile"))
                  mobile_ff = *mob;
                else if (const std::string* plat =
                             fp_d.FindString("uaPlatform"))
                  mobile_ff = (*plat == "Android" || *plat == "iOS");
                ffs.push_back(mobile_ff ? std::string(blink::kMobileFormFactor)
                                        : std::string(blink::kDesktopFormFactor));
              }
              %sform_factors = std::move(ffs);
            }
"""


def die(msg: str) -> None:
    print("!!", msg)
    sys.exit(1)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: pathlib.Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def insert_formfactors(text: str, meta_var: str) -> str:
    snippet = FF_SNIPPET % (MARKER, meta_var)
    if MARKER in text and f"{meta_var}form_factors" in text:
        return text
    key = 'FindBool("wow64"))'
    idx = text.find(key)
    if idx < 0:
        return text
    nl = text.find("\n", idx)
    if nl < 0:
        return text
    nl2 = text.find("\n", nl + 1)
    if nl2 < 0:
        return text
    assign = text[nl + 1 : nl2]
    if "wow64" not in assign or meta_var.split(">")[-1].split(".")[0] not in assign:
        idx = text.find(key, nl2)
        if idx < 0:
            return text
        nl = text.find("\n", idx)
        nl2 = text.find("\n", nl + 1)
        if nl2 < 0:
            return text
    return text[:nl2] + snippet + text[nl2:]


def patch_formfactors(src: pathlib.Path) -> None:
    targets = [
        (
            src / "content/browser/renderer_host/navigation_request.cc",
            "ua_metadata->",
        ),
        (
            src
            / "third_party/blink/renderer/core/loader/frame_fetch_context.cc",
            "metadata->",
        ),
        (
            src / "third_party/blink/renderer/core/loader/frame_loader.cc",
            "metadata->",
        ),
        (
            src / "third_party/blink/renderer/core/workers/worker_global_scope.cc",
            "m.",
        ),
    ]
    for path, var in targets:
        text = read(path)
        if MARKER in text:
            print("skip", path, "formFactors")
            continue
        inc = '#include "third_party/blink/public/common/user_agent/user_agent_metadata.h"\n'
        if "user_agent_metadata.h" not in text:
            # after the first include
            first = text.find("#include ")
            if first < 0:
                die("no includes in %s" % path)
            nl = text.find("\n", first)
            text = text[: nl + 1] + inc + text[nl + 1 :]
        new = insert_formfactors(text, var)
        if new == text:
            print("warn: wow64 overlay not found in %s (var=%s), skip" % (path, var))
            continue
        write(path, new)


def patch_inner_size(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/core/frame/local_dom_window.cc"
    text = read(path)
    unguarded_w = """int LocalDOMWindow::innerWidth() const {
  if (!GetFrame())
    return 0;
  // %s: CSS viewport from fingerprint, not the OS window.
  if (std::optional<int> width = FpWindowInt(GetFrame(), "viewportWidth");
      width && *width > 0) {
    return *width;
  }
  if (std::optional<int> width = FpWindowInt(GetFrame(), "screenWidth");
      width && *width > 0) {
    return *width;
  }

  return AdjustForAbsoluteZoom::AdjustInt(GetViewportSize().width(),
                                          GetFrame()->LayoutZoomFactor());
}""" % MARKER
    unguarded_h = """int LocalDOMWindow::innerHeight() const {
  if (!GetFrame())
    return 0;
  if (std::optional<int> height = FpWindowInt(GetFrame(), "viewportHeight");
      height && *height > 0) {
    return *height;
  }
  if (std::optional<int> height = FpWindowInt(GetFrame(), "screenHeight");
      height && *height > 0) {
    return *height;
  }

  return AdjustForAbsoluteZoom::AdjustInt(GetViewportSize().height(),
                                          GetFrame()->LayoutZoomFactor());
}"""
    iw = text.find("int LocalDOMWindow::innerWidth()")
    if iw >= 0 and "IsOutermostMainFrame()" in text[iw : iw + 900]:
        print("skip", path, "innerWidth")
        return
    old_w = """int LocalDOMWindow::innerWidth() const {
  if (!GetFrame())
    return 0;

  return AdjustForAbsoluteZoom::AdjustInt(GetViewportSize().width(),
                                          GetFrame()->LayoutZoomFactor());
}"""
    new_w = """int LocalDOMWindow::innerWidth() const {
  if (!GetFrame())
    return 0;
  // %s: only the outermost page. iframe innerWidth is the iframe box
  // after the main WebView Resize; OOPIF must not report the phone viewport.
  if (GetFrame()->IsOutermostMainFrame()) {
    if (std::optional<int> width = FpWindowInt(GetFrame(), "viewportWidth");
        width && *width > 0) {
      return *width;
    }
    if (std::optional<int> width = FpWindowInt(GetFrame(), "screenWidth");
        width && *width > 0) {
      return *width;
    }
  }

  return AdjustForAbsoluteZoom::AdjustInt(GetViewportSize().width(),
                                          GetFrame()->LayoutZoomFactor());
}""" % MARKER
    old_h = """int LocalDOMWindow::innerHeight() const {
  if (!GetFrame())
    return 0;

  return AdjustForAbsoluteZoom::AdjustInt(GetViewportSize().height(),
                                          GetFrame()->LayoutZoomFactor());
}"""
    new_h = """int LocalDOMWindow::innerHeight() const {
  if (!GetFrame())
    return 0;
  if (GetFrame()->IsOutermostMainFrame()) {
    if (std::optional<int> height = FpWindowInt(GetFrame(), "viewportHeight");
        height && *height > 0) {
      return *height;
    }
    if (std::optional<int> height = FpWindowInt(GetFrame(), "screenHeight");
        height && *height > 0) {
      return *height;
    }
  }

  return AdjustForAbsoluteZoom::AdjustInt(GetViewportSize().height(),
                                          GetFrame()->LayoutZoomFactor());
}"""
    if unguarded_w in text and unguarded_h in text:
        text = text.replace(unguarded_h, new_h, 1).replace(unguarded_w, new_w, 1)
        write(path, text)
        return
    if old_w not in text or old_h not in text:
        die("LocalDOMWindow::innerWidth/innerHeight not found")
    text = text.replace(old_h, new_h, 1).replace(old_w, new_w, 1)
    write(path, text)


def patch_visual_viewport(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/core/frame/visual_viewport.cc"
    text = read(path)
    width_fn = text.find("double VisualViewport::Width()")
    if MARKER in text and width_fn >= 0:
        chunk = text[width_fn : width_fn + 1200]
        if "LocalMainFrame().IsOutermostMainFrame()" in chunk:
            print("skip", path)
            return
        old_open = """  // BROWSER_FINGERPRINT_FORMFACTORS_LAYOUT
  if (WebLocalFrameImpl* web_frame =
          WebLocalFrameImpl::FromFrame(&LocalMainFrame())) {"""
        new_open = """  // BROWSER_FINGERPRINT_FORMFACTORS_LAYOUT
  if (LocalMainFrame().IsOutermostMainFrame()) {
  if (WebLocalFrameImpl* web_frame =
          WebLocalFrameImpl::FromFrame(&LocalMainFrame())) {"""
        if old_open in text:
            text = text.replace(old_open, new_open)
            # close the extra if before native layout update in Width/Height
            text = text.replace(
                """      }
    }
  }
  if (Document* document = LocalMainFrame().GetDocument())""",
                """      }
    }
  }
  }
  if (Document* document = LocalMainFrame().GetDocument())""",
            )
            write(path, text)
            return
        print("skip", path, "(marker present, could not wrap)")
        return
    inc = (
        '#include "base/json/json_reader.h"\n'
        '#include "third_party/blink/renderer/core/exported/web_view_impl.h"\n'
        '#include "third_party/blink/renderer/core/frame/web_local_frame_impl.h"\n'
    )
    needle = '#include "third_party/blink/renderer/core/frame/visual_viewport.h"\n'
    if needle not in text:
        die("visual_viewport.h include not found")
    text = text.replace(needle, needle + inc, 1)

    fp_read = r'''
  // %s: outermost page only; iframe visualViewport is the iframe widget.
  if (LocalMainFrame().IsOutermostMainFrame()) {
    if (WebLocalFrameImpl* web_frame =
            WebLocalFrameImpl::FromFrame(&LocalMainFrame())) {
      if (web_frame->ViewImpl()) {
        const std::string& fingerprint =
            web_frame->ViewImpl()->GetRendererPreferences().fingerprint;
        if (!fingerprint.empty()) {
          if (std::optional<base::Value> profile =
                  base::JSONReader::Read(fingerprint, base::JSON_PARSE_RFC)) {
            if (profile->is_dict()) {
              if (std::optional<int> v =
                      profile->GetDict().FindInt("%s");
                  v && *v > 0) {
                return *v;
              }
              if (std::optional<int> v =
                      profile->GetDict().FindInt("%s");
                  v && *v > 0) {
                return *v;
              }
            }
          }
        }
      }
    }
  }
'''
    old_w = """double VisualViewport::Width() const {
  DCHECK(IsActiveViewport());
  if (Document* document = LocalMainFrame().GetDocument())
    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);
  return VisibleWidthCSSPx();
}"""
    new_w = (
        "double VisualViewport::Width() const {\n"
        "  DCHECK(IsActiveViewport());\n"
        + (fp_read % (MARKER, "viewportWidth", "screenWidth"))
        + """  if (Document* document = LocalMainFrame().GetDocument())
    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);
  return VisibleWidthCSSPx();
}"""
    )
    old_h = """double VisualViewport::Height() const {
  DCHECK(IsActiveViewport());
  if (Document* document = LocalMainFrame().GetDocument())
    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);
  return VisibleHeightCSSPx();
}"""
    new_h = (
        "double VisualViewport::Height() const {\n"
        "  DCHECK(IsActiveViewport());\n"
        + (fp_read % (MARKER, "viewportHeight", "screenHeight"))
        + """  if (Document* document = LocalMainFrame().GetDocument())
    document->UpdateStyleAndLayout(DocumentUpdateReason::kJavaScript);
  return VisibleHeightCSSPx();
}"""
    )
    if old_w not in text or old_h not in text:
        die("VisualViewport::Width/Height not found")
    text = text.replace(old_w, new_w, 1).replace(old_h, new_h, 1)
    write(path, text)


def patch_webview_resize(src: pathlib.Path) -> None:
    path = src / "third_party/blink/renderer/core/exported/web_view_impl.cc"
    text = read(path)
    layout_mark = text.find("force CSS layout viewport")
    if layout_mark >= 0 and "IsOutermostMainFrame()" in text[layout_mark : layout_mark + 800]:
        print("skip", path, "Resize")
        return
    unguarded_resize = """      if (vw > 0 && vh > 0) {
        gfx::Size want(vw, vh);
        if (Size() != want)
          Resize(want);
      }"""
    guarded_resize = """      if (vw > 0 && vh > 0) {
        // Outermost page only. OOPIF WebView is the iframe widget.
        LocalFrame* mf = DynamicTo<LocalFrame>(GetPage() ? GetPage()->MainFrame()
                                                         : nullptr);
        if (mf && mf->IsOutermostMainFrame()) {
          gfx::Size want(vw, vh);
          if (Size() != want)
            Resize(want);
        }
      }"""
    if unguarded_resize in text:
        write(path, text.replace(unguarded_resize, guarded_resize, 1))
        return
    old = """      if (std::optional<int> mtp = d.FindInt("maxTouchPoints");
          mtp && *mtp > 0) {
        WebRuntimeFeatures::EnableFeatureFromString(
            "TouchEventFeatureDetection", true);
      }
    }
  }"""
    new = """      if (std::optional<int> mtp = d.FindInt("maxTouchPoints");
          mtp && *mtp > 0) {
        WebRuntimeFeatures::EnableFeatureFromString(
            "TouchEventFeatureDetection", true);
      }
      // %s: force CSS layout viewport so matchMedia / client rects match.
      int vw = 0;
      int vh = 0;
      if (std::optional<int> vw_fp = d.FindInt("viewportWidth");
          vw_fp && *vw_fp > 0)
        vw = *vw_fp;
      else if (std::optional<int> sw_fp = d.FindInt("screenWidth");
               sw_fp && *sw_fp > 0)
        vw = *sw_fp;
      if (std::optional<int> vh_fp = d.FindInt("viewportHeight");
          vh_fp && *vh_fp > 0)
        vh = *vh_fp;
      else if (std::optional<int> sh_fp = d.FindInt("screenHeight");
               sh_fp && *sh_fp > 0)
        vh = *sh_fp;
      if (vw > 0 && vh > 0) {
        // Outermost page only. OOPIF WebView is the iframe widget.
        LocalFrame* mf = DynamicTo<LocalFrame>(GetPage() ? GetPage()->MainFrame()
                                                         : nullptr);
        if (mf && mf->IsOutermostMainFrame()) {
          gfx::Size want(vw, vh);
          if (Size() != want)
            Resize(want);
        }
      }
    }
  }""" % MARKER
    if old not in text:
        die("WebViewImpl fingerprint maxTouchPoints block not found")
    text = text.replace(old, new, 1)
    write(path, text)


def main() -> None:
    if len(sys.argv) != 2:
        die("usage: patch_formfactors_layout.py <chromium/src>")
    src = pathlib.Path(sys.argv[1]).resolve()
    if not (src / "third_party/blink").is_dir():
        die("not a chromium src tree: %s" % src)
    patch_formfactors(src)
    patch_inner_size(src)
    patch_visual_viewport(src)
    patch_webview_resize(src)
    print(">>> formFactors + kernel layout viewport applied")


if __name__ == "__main__":
    main()
