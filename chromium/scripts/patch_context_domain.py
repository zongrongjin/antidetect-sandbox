#!/usr/bin/env python3
"""After fp_full.diff: rename Fingerprint CDP domain to Context and add proxy.

Usage: python3 scripts/patch_context_domain.py /path/to/chromium/src
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC_NEW = HERE / "src-new"

REPLACEMENTS = [
    ("protocol/fingerprint_handler.cc", "protocol/context_handler.cc"),
    ("protocol/fingerprint_handler.h", "protocol/context_handler.h"),
    ("protocol/fingerprint.cc", "protocol/context.cc"),
    ("protocol/fingerprint.h", "protocol/context.h"),
    ("class FingerprintHandler;", "class ContextHandler;"),
    ("protocol::FingerprintHandler", "protocol::ContextHandler"),
    ("domains/Fingerprint.pdl", "domains/Context.pdl"),
    ('"domain": "Fingerprint"', '"domain": "Context"'),
]


PROXY_STORAGE = r'''
namespace {
const char kContextProxyUserDataKey[] = "browser_context_proxy";
class ContextProxyUserData : public base::SupportsUserData::Data {
 public:
  std::string endpoint;
  std::string username;
  std::string password;
};
}  // namespace

void WebContentsImpl::SetBrowserContextProxy(BrowserContext* browser_context,
                                             const std::string& endpoint,
                                             const std::string& username,
                                             const std::string& password) {
  if (!browser_context)
    return;
  auto* data = static_cast<ContextProxyUserData*>(
      browser_context->GetUserData(kContextProxyUserDataKey));
  if (!data) {
    auto owned = std::make_unique<ContextProxyUserData>();
    data = owned.get();
    browser_context->SetUserData(kContextProxyUserDataKey, std::move(owned));
  }
  data->endpoint = endpoint;
  data->username = username;
  data->password = password;
  // CONTEXT_PROXY_APPLY: push endpoint into this context's NetworkContext.
  // Auth is consumed by ContextProxyThrottle (Proxy-Authorization, no 407).
  // Wire SetProxy / SetConfiguredProxy here if the 151 mojom name differs.
}

bool WebContentsImpl::GetBrowserContextProxy(BrowserContext* browser_context,
                                             std::string* endpoint,
                                             std::string* username,
                                             std::string* password) {
  if (!browser_context)
    return false;
  auto* data = static_cast<ContextProxyUserData*>(
      browser_context->GetUserData(kContextProxyUserDataKey));
  if (!data || data->endpoint.empty())
    return false;
  if (endpoint)
    *endpoint = data->endpoint;
  if (username)
    *username = data->username;
  if (password)
    *password = data->password;
  return true;
}

'''


def replace_all(path: Path, pairs):
    text = path.read_text(encoding="utf-8")
    orig = text
    for a, b in pairs:
        text = text.replace(a, b)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main():
    if len(sys.argv) != 2:
        print("usage: patch_context_domain.py <chromium/src>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    if not (src / "content" / "browser" / "devtools").is_dir():
        raise SystemExit(f"not a chromium src: {src}")

    # Copy new protocol files
    pdl_dst = src / "third_party/blink/public/devtools_protocol/domains/Context.pdl"
    pdl_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        SRC_NEW / "third_party/blink/public/devtools_protocol/domains/Context.pdl",
        pdl_dst,
    )
    old_pdl = src / "third_party/blink/public/devtools_protocol/domains/Fingerprint.pdl"
    if old_pdl.exists():
        old_pdl.unlink()

    for name in (
        "context_handler.cc",
        "context_handler.h",
        "context_proxy_support.cc",
        "context_proxy_support.h",
        "context_request_interceptor.cc",
        "context_request_interceptor.h",
    ):
        shutil.copy2(
            SRC_NEW / "content/browser/devtools/protocol" / name,
            src / "content/browser/devtools/protocol" / name,
        )
    for stale in ("fingerprint_handler.cc", "fingerprint_handler.h"):
        p = src / "content/browser/devtools/protocol" / stale
        if p.exists():
            p.unlink()

    targets = [
        src / "content/browser/BUILD.gn",
        src / "content/browser/devtools/BUILD.gn",
        src / "content/browser/devtools/devtools_session.h",
        src / "content/browser/devtools/render_frame_devtools_agent_host.cc",
        src / "third_party/blink/public/devtools_protocol/BUILD.gn",
        src / "third_party/blink/public/devtools_protocol/browser_protocol.pdl",
        src / "content/browser/devtools/protocol/emulation_handler.cc",
        src / "content/browser/devtools/protocol/emulation_handler.h",
        src / "content/browser/devtools/protocol_config.json",
    ]
    for t in targets:
        if t.exists():
            replace_all(t, REPLACEMENTS)

    # Handler class names in session type list
    session_h = src / "content/browser/devtools/devtools_session.h"
    if session_h.exists():
        replace_all(session_h, [("FingerprintHandler", "ContextHandler")])

    agent = src / "content/browser/devtools/render_frame_devtools_agent_host.cc"
    if agent.exists():
        replace_all(agent, [("FingerprintHandler", "ContextHandler")])

    wc_cc = src / "content/browser/web_contents/web_contents_impl.cc"
    if wc_cc.exists():
        text = wc_cc.read_text(encoding="utf-8")
        if "SetBrowserContextProxy" not in text:
            marker = "std::string WebContentsImpl::GetBrowserContextFingerprint"
            idx = text.find(marker)
            if idx < 0:
                raise SystemExit("web_contents_impl.cc: fingerprint getter not found")
            # insert proxy storage after the fingerprint getter function
            end = text.find("\nconst blink::RendererPreferences&", idx)
            if end < 0:
                end = text.find("\nconst blink::RendererPreferences &", idx)
            if end < 0:
                raise SystemExit("web_contents_impl.cc: insert point not found")
            text = text[:end] + PROXY_STORAGE + text[end:]
            wc_cc.write_text(text, encoding="utf-8")

    wc_h = src / "content/browser/web_contents/web_contents_impl.h"
    if wc_h.exists():
        text = wc_h.read_text(encoding="utf-8")
        if "SetBrowserContextProxy" not in text:
            needle = "static std::string GetBrowserContextFingerprint"
            if needle not in text:
                needle = "GetBrowserContextFingerprint"
            # append declarations near fingerprint
            decl = (
                "  static void SetBrowserContextProxy(BrowserContext* browser_context,\n"
                "                                    const std::string& endpoint,\n"
                "                                    const std::string& username,\n"
                "                                    const std::string& password);\n"
                "  static bool GetBrowserContextProxy(BrowserContext* browser_context,\n"
                "                                    std::string* endpoint,\n"
                "                                    std::string* username,\n"
                "                                    std::string* password);\n"
            )
            if "SetBrowserContextFingerprint" in text:
                text = text.replace(
                    "SetBrowserContextFingerprint",
                    "SetBrowserContextFingerprint",
                    1,
                )
                # insert after the fingerprint setter/getter block: after GetBrowserContextFingerprint decl
                import re
                m = re.search(
                    r"static std::string GetBrowserContextFingerprint\([^;]*\);",
                    text,
                )
                if m:
                    text = text[: m.end()] + "\n" + decl + text[m.end() :]
                    wc_h.write_text(text, encoding="utf-8")
                else:
                    print("!! web_contents_impl.h: could not insert proxy decls, add manually")
            else:
                print("!! web_contents_impl.h: fingerprint decls missing")

    print("== Context domain patched (fingerprint renamed, proxy storage added) ==")
    print("   Next: gn gen && ninja. Wire CONTEXT_PROXY_APPLY if NetworkContext SetProxy fails to compile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
