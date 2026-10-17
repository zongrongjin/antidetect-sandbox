#!/usr/bin/env python3
"""Patch Chromium 151 tree: apply Context proxy to NetworkContext, store cache."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC_NEW = HERE / "src-new"

PROXY_APPLY_CALL = """
  data->endpoint = endpoint;
  data->username = username;
  data->password = password;
  PushContextProxy(browser_context, data);
"""

PUSH_AND_APPLY = r'''
void WebContentsImpl::RegisterIsolatedProxyContext(
    BrowserContext* browser_context) {
  if (!browser_context)
    return;
  IsolatedProxyContextIds().insert(browser_context->UniqueId());
  GetOrCreateContextProxyUserData(browser_context);
}

bool WebContentsImpl::ApplyContextProxyToNetworkParams(
    BrowserContext* browser_context,
    network::mojom::NetworkContextParams* params) {
  if (!browser_context || !params)
    return false;
  if (!IsolatedProxyContextIds().contains(browser_context->UniqueId()))
    return false;
  auto* data = GetOrCreateContextProxyUserData(browser_context);
  net::ProxyConfig config;
  if (data->endpoint.empty()) {
    config = net::ProxyConfig::CreateDirect();
  } else {
    config.proxy_rules().ParseFromString(data->endpoint);
  }
  params->initial_proxy_config = net::ProxyConfigWithAnnotation(
      config, kContextProxyTrafficAnnotation);
  mojo::PendingRemote<network::mojom::ProxyConfigClient> pending;
  params->proxy_config_client_receiver =
      pending.InitWithNewPipeAndPassReceiver();
  if (data->client)
    data->client.reset();
  data->client.Bind(std::move(pending));
  return true;
}

void WebContentsImpl::SetBrowserContextCache(BrowserContext* browser_context,
                                             const std::string& dir,
                                             const std::string& map,
                                             const std::string& rules) {
  if (!browser_context)
    return;
  auto* data = GetOrCreateContextProxyUserData(browser_context);
  data->cache_dir = dir;
  data->cache_map = map;
  data->cache_rules = rules;
}

bool WebContentsImpl::GetBrowserContextCache(BrowserContext* browser_context,
                                             std::string* dir,
                                             std::string* map,
                                             std::string* rules) {
  if (!browser_context)
    return false;
  auto* data = static_cast<ContextProxyUserData*>(
      browser_context->GetUserData(kContextProxyUserDataKey));
  if (!data || (data->cache_dir.empty() && data->cache_map.empty()))
    return false;
  if (dir)
    *dir = data->cache_dir;
  if (map)
    *map = data->cache_map;
  if (rules)
    *rules = data->cache_rules;
  return true;
}

'''

USERDATA_CLASS = r'''
namespace {
const char kContextProxyUserDataKey[] = "browser_context_proxy";

const net::NetworkTrafficAnnotationTag kContextProxyTrafficAnnotation =
    net::DefineNetworkTrafficAnnotation("zzbrowser_context_proxy", R"(
      semantics {
        sender: "zzbrowser Context proxy"
        description:
          "Per-BrowserContext upstream proxy configured by Context.setContextOverrides."
        trigger: "Context.setContextOverrides proxy field."
        data: "All network traffic from that isolated browser context."
        destination: OTHER
        destination_other: "The proxy endpoint supplied by the embedder."
      }
      policy {
        cookies_allowed: NO
        setting: "Set only via DevTools Context.setContextOverrides."
        policy_exception_justification: "Isolated automation context proxy."
      })");

class ContextProxyUserData : public base::SupportsUserData::Data {
 public:
  std::string endpoint;
  std::string username;
  std::string password;
  std::string cache_dir;
  std::string cache_map;
  std::string cache_rules;
  mojo::Remote<network::mojom::ProxyConfigClient> client;
};

base::flat_set<std::string>& IsolatedProxyContextIds() {
  static base::NoDestructor<base::flat_set<std::string>> ids;
  return *ids;
}

ContextProxyUserData* GetOrCreateContextProxyUserData(
    BrowserContext* browser_context) {
  auto* data = static_cast<ContextProxyUserData*>(
      browser_context->GetUserData(kContextProxyUserDataKey));
  if (!data) {
    auto owned = std::make_unique<ContextProxyUserData>();
    data = owned.get();
    browser_context->SetUserData(kContextProxyUserDataKey, std::move(owned));
  }
  return data;
}

void PushContextProxy(BrowserContext* browser_context,
                      ContextProxyUserData* data) {
  if (!browser_context || !data)
    return;
  net::ProxyConfig config;
  if (data->endpoint.empty()) {
    config = net::ProxyConfig::CreateDirect();
  } else {
    config.proxy_rules().ParseFromString(data->endpoint);
  }
  net::ProxyConfigWithAnnotation annotated(
      config, kContextProxyTrafficAnnotation);
  if (data->client && data->client.is_bound()) {
    data->client->OnProxyConfigUpdated(annotated);
  }
  StoragePartition* partition =
      browser_context->GetDefaultStoragePartition();
  if (!partition)
    return;
  network::mojom::NetworkContext* network_context =
      partition->GetNetworkContext();
  if (!network_context || data->username.empty())
    return;
  std::string spec = data->endpoint;
  if (spec.find("://") == std::string::npos)
    spec = "http://" + spec;
  GURL proxy_url(spec);
  if (!proxy_url.is_valid())
    return;
  net::AuthChallengeInfo challenge;
  challenge.is_proxy = true;
  challenge.challenger = url::SchemeHostPort(proxy_url);
  challenge.scheme = "basic";
  challenge.realm = "";
  net::AuthCredentials creds(base::UTF8ToUTF16(data->username),
                             base::UTF8ToUTF16(data->password));
  network_context->AddAuthCacheEntry(challenge, net::NetworkAnonymizationKey(),
                                     creds, base::DoNothing());
}
}  // namespace
'''

INCLUDES = [
    '#include "base/containers/flat_set.h"',
    '#include "base/base64.h"',
    '#include "base/functional/callback_helpers.h"',
    '#include "base/no_destructor.h"',
    '#include "base/strings/utf_string_conversions.h"',
    '#include "content/public/browser/storage_partition.h"',
    '#include "mojo/public/cpp/bindings/remote.h"',
    '#include "net/base/auth.h"',
    '#include "net/base/network_anonymization_key.h"',
    '#include "net/proxy_resolution/proxy_config.h"',
    '#include "net/proxy_resolution/proxy_config_with_annotation.h"',
    '#include "net/traffic_annotation/network_traffic_annotation.h"',
    '#include "services/network/public/mojom/network_context.mojom.h"',
    '#include "services/network/public/mojom/proxy_config.mojom.h"',
    '#include "url/gurl.h"',
    '#include "url/scheme_host_port.h"',
]


def ensure_includes(text: str) -> str:
    for inc in INCLUDES:
        if inc not in text:
            # insert after first include
            idx = text.find("#include ")
            line_end = text.find("\n", idx)
            text = text[: line_end + 1] + inc + "\n" + text[line_end + 1 :]
    return text


def patch_web_contents_cc(path: Path):
    text = path.read_text(encoding="utf-8")
    text = ensure_includes(text)
    if "kContextProxyUserDataKey" in text and "class ContextProxyUserData" in text:
        # replace old class + functions
        start = text.find("namespace {\nconst char kContextProxyUserDataKey")
        if start < 0:
            start = text.find("const char kContextProxyUserDataKey")
            start = text.rfind("namespace {", 0, start)
        end = text.find("void WebContentsImpl::SetBrowserContextProxy")
        if start < 0 or end < 0:
            raise SystemExit("cannot find proxy userdata block")
        text = text[:start] + USERDATA_CLASS + "\n" + text[end:]
    old_assign = """  data->endpoint = endpoint;
  data->username = username;
  data->password = password;
  // CONTEXT_PROXY_APPLY: push endpoint into this context's NetworkContext.
  // Auth is consumed by ContextProxyThrottle (Proxy-Authorization, no 407).
  // Wire SetProxy / SetConfiguredProxy here if the 151 mojom name differs.
}"""
    new_assign = """  data->endpoint = endpoint;
  data->username = username;
  data->password = password;
  PushContextProxy(browser_context, data);
}"""
    if old_assign not in text:
        if "PushContextProxy(browser_context, data);" not in text:
            raise SystemExit("SetBrowserContextProxy body not found")
    else:
        text = text.replace(old_assign, new_assign)
    marker = "bool WebContentsImpl::GetBrowserContextProxy"
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit("GetBrowserContextProxy not found")
    # find end of GetBrowserContextProxy function
    end = text.find("\nconst blink::RendererPreferences&", idx)
    if end < 0:
        end = text.find("\nvoid WebContentsImpl::", idx + 10)
    if "ApplyContextProxyToNetworkParams" not in text:
        text = text[:end] + PUSH_AND_APPLY + text[end:]
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_web_contents_h(path: Path):
    text = path.read_text(encoding="utf-8")
    extra = """
  static void RegisterIsolatedProxyContext(BrowserContext* browser_context);
  static bool ApplyContextProxyToNetworkParams(
      BrowserContext* browser_context,
      network::mojom::NetworkContextParams* params);
  static void SetBrowserContextCache(BrowserContext* browser_context,
                                     const std::string& dir,
                                     const std::string& map,
                                     const std::string& rules);
  static bool GetBrowserContextCache(BrowserContext* browser_context,
                                     std::string* dir,
                                     std::string* map,
                                     std::string* rules);
"""
    if "ApplyContextProxyToNetworkParams" not in text:
        needle = "static bool GetBrowserContextProxy"
        i = text.find(needle)
        if i < 0:
            raise SystemExit("header GetBrowserContextProxy missing")
        semi = text.find(";", i)
        text = text[: semi + 1] + extra + text[semi + 1 :]
    if "namespace mojom" not in text.split("class WebContentsImpl")[0]:
        fwd = """
namespace network {
namespace mojom {
class NetworkContextParams;
}
}
"""
        if "class NetworkContextParams" not in text:
            text = text.replace("namespace content {", "namespace content {\n" + fwd, 1)
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_target_handler(path: Path):
    text = path.read_text(encoding="utf-8")
    if "RegisterIsolatedProxyContext" not in text:
        old = """  if (in_disposeOnDetach.value_or(false)) {
    dispose_on_detach_context_ids_.insert(context->UniqueId());
  }
  callback->sendSuccess(context->UniqueId());
}"""
        new = """  if (in_disposeOnDetach.value_or(false)) {
    dispose_on_detach_context_ids_.insert(context->UniqueId());
  }
  WebContentsImpl::RegisterIsolatedProxyContext(context);
  callback->sendSuccess(context->UniqueId());
}"""
        if old not in text:
            raise SystemExit("CreateBrowserContext tail not found")
        text = text.replace(old, new, 1)
    if "ApplyContextProxyToNetworkParams" not in text:
        needle = "void TargetHandler::ApplyNetworkContextParamsOverrides("
        i = text.find(needle)
        if i < 0:
            raise SystemExit("ApplyNetworkContextParamsOverrides not found")
        brace = text.find("{", i)
        insert = """
  if (WebContentsImpl::ApplyContextProxyToNetworkParams(browser_context,
                                                        context_params)) {
    return;
  }
"""
        text = text[: brace + 1] + insert + text[brace + 1 :]
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def copy_protocol(src: Path):
    pdl_src = SRC_NEW / "third_party/blink/public/devtools_protocol/domains/Context.pdl"
    pdl_dst = src / "third_party/blink/public/devtools_protocol/domains/Context.pdl"
    shutil.copy2(pdl_src, pdl_dst)
    for name in ("context_handler.cc", "context_handler.h"):
        shutil.copy2(
            SRC_NEW / "content/browser/devtools/protocol" / name,
            src / "content/browser/devtools/protocol" / name,
        )
    print("copied protocol files")


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    if not (src / "content/browser/web_contents/web_contents_impl.cc").exists():
        raise SystemExit(f"not chromium src: {src}")
    copy_protocol(src)
    patch_web_contents_cc(src / "content/browser/web_contents/web_contents_impl.cc")
    patch_web_contents_h(src / "content/browser/web_contents/web_contents_impl.h")
    patch_target_handler(
        src / "content/browser/devtools/protocol/target_handler.cc"
    )
    print("== context proxy apply patched ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
