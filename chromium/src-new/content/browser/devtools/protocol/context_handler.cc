#include "content/browser/devtools/protocol/context_handler.h"

#include <utility>
#include <vector>

#include "base/barrier_closure.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "content/browser/devtools/protocol/context_proxy_support.h"
#include "content/browser/renderer_host/render_frame_host_impl.h"
#include "content/browser/web_contents/web_contents_impl.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/referrer.h"
#include "net/cookies/canonical_cookie.h"
#include "net/cookies/cookie_options.h"
#include "net/cookies/cookie_util.h"
#include "services/network/public/mojom/cookie_manager.mojom.h"
#include "ui/base/page_transition_types.h"
#include "url/gurl.h"

namespace content {
namespace protocol {
namespace {

net::CookieSameSite SameSiteFrom(const std::string& s) {
  if (s == "Lax" || s == "lax")
    return net::CookieSameSite::LAX_MODE;
  if (s == "Strict" || s == "strict")
    return net::CookieSameSite::STRICT_MODE;
  if (s == "None" || s == "none")
    return net::CookieSameSite::NO_RESTRICTION;
  return net::CookieSameSite::UNSPECIFIED;
}

std::unique_ptr<net::CanonicalCookie> MakeCookie(Context::CookieParam& p) {
  const std::string url_spec = p.GetUrl("");
  std::string domain = p.GetDomain("");
  if (url_spec.empty() && domain.empty())
    return nullptr;
  bool secure = p.GetSecure(false);
  GURL source_url(url_spec);
  if (source_url.is_valid() && source_url.SchemeIsHTTPOrHTTPS()) {
    secure = secure || source_url.SchemeIsCryptographic();
    if (domain.empty())
      domain = std::string(source_url.GetHost());
  }
  std::string url_host = domain;
  std::string cookie_domain = domain;
  if (!domain.empty() && domain[0] == '.') {
    url_host = domain.substr(1);
  } else {
    cookie_domain.clear();
  }
  if (url_spec.empty()) {
    source_url = GURL(std::string(secure ? "https://" : "http://") + url_host);
  }
  base::Time expiry;
  double expires = p.GetExpires(-1);
  if (expires >= 0)
    expiry = base::Time::FromSecondsSinceUnixEpoch(expires);
  return net::CanonicalCookie::CreateSanitizedCookie(
      source_url, p.GetName(), p.GetValue(), cookie_domain, p.GetPath(""),
      base::Time(), expiry, base::Time(), secure, p.GetHttpOnly(false),
      SameSiteFrom(p.GetSameSite("")),
      net::CookiePriority::COOKIE_PRIORITY_MEDIUM, std::nullopt,
      /*status=*/nullptr);
}

}  // namespace

ContextHandler::ContextHandler()
    : DevToolsDomainHandler(Context::Metainfo::domainName) {}

ContextHandler::~ContextHandler() = default;

void ContextHandler::Wire(UberDispatcher* dispatcher) {
  frontend_ = std::make_unique<Context::Frontend>(dispatcher->channel());
  Context::Dispatcher::wire(dispatcher, this);
}

void ContextHandler::NotifyMatch(const std::string& kind,
                                 const std::string& url) {
  if (!frontend_)
    return;
  if (kind == "capture")
    frontend_->Captured(url);
  else if (kind == "callback")
    frontend_->Callback(url);
  else if (kind == "observe")
    frontend_->Observed(url);
}

void ContextHandler::SetRenderer(int process_host_id,
                                 RenderFrameHostImpl* frame_host) {
  host_ = frame_host;
}

WebContentsImpl* ContextHandler::GetWebContents() {
  if (!host_)
    return nullptr;
  return static_cast<WebContentsImpl*>(
      WebContents::FromRenderFrameHost(host_));
}

void ContextHandler::SetContextOverrides(
    std::optional<String> fingerprint,
    std::unique_ptr<Context::ProxyConfig> proxy,
    std::unique_ptr<Context::CacheConfig> cache,
    std::unique_ptr<protocol::Array<Context::CookieParam>> cookies,
    std::optional<String> url,
    std::optional<String> html,
    std::unique_ptr<SetContextOverridesCallback> callback) {
  auto* wc = GetWebContents();
  if (!wc) {
    callback->sendFailure(
        DispatchResponse::ServerError("no WebContents for this session"));
    return;
  }
  BrowserContext* bc = wc->GetBrowserContext();
  if (!bc) {
    callback->sendFailure(DispatchResponse::ServerError("no BrowserContext"));
    return;
  }

  if (fingerprint.has_value()) {
    WebContentsImpl::SetBrowserContextFingerprint(bc, fingerprint.value());
  }

  // Proxy before any navigation so the first document uses this exit.
  if (proxy) {
    SetContextProxy(bc, proxy->GetEndpoint(""), proxy->GetUsername(""),
                    proxy->GetPassword(""));
  }

  if (cache) {
    SetContextCache(bc, cache->GetDir(""), cache->GetMap(""),
                    cache->GetRules(""));
  }

  const std::string nav_url = url.value_or("");
  const std::string nav_html = html.value_or("");
  if (url.has_value() || html.has_value())
    SetContextDocument(bc, nav_url, nav_html);

  std::vector<std::unique_ptr<net::CanonicalCookie>> net_cookies;
  if (cookies && !cookies->empty()) {
    if (!host_) {
      callback->sendFailure(DispatchResponse::ServerError("no frame host"));
      return;
    }
    StoragePartition* partition = host_->GetStoragePartition();
    if (!partition) {
      callback->sendFailure(
          DispatchResponse::ServerError("no StoragePartition"));
      return;
    }
    network::mojom::CookieManager* cookie_manager =
        partition->GetCookieManagerForBrowserProcess();
    if (!cookie_manager) {
      callback->sendFailure(DispatchResponse::ServerError("no CookieManager"));
      return;
    }
    net_cookies.reserve(cookies->size());
    for (auto& cookie : *cookies) {
      if (!cookie)
        continue;
      auto cc = MakeCookie(*cookie);
      if (!cc) {
        callback->sendFailure(
            DispatchResponse::InvalidParams("invalid cookie fields"));
        return;
      }
      net_cookies.push_back(std::move(cc));
    }
    if (net_cookies.empty()) {
      cookies.reset();
    } else {
      net::CookieOptions options;
      options.set_include_httponly();
      options.set_same_site_cookie_context(
          net::CookieOptions::SameSiteCookieContext::MakeInclusive());
      base::RepeatingClosure barrier = base::BarrierClosure(
          net_cookies.size(),
          base::BindOnce(
              [](base::WeakPtr<ContextHandler> self, std::string nav_url,
                 std::unique_ptr<SetContextOverridesCallback> cb) {
                if (self && !nav_url.empty()) {
                  if (auto* contents = self->GetWebContents()) {
                    contents->GetController().LoadURL(
                        GURL(nav_url), Referrer(), ui::PAGE_TRANSITION_TYPED,
                        std::string());
                  }
                }
                cb->sendSuccess();
              },
              weak_factory_.GetWeakPtr(), nav_url, std::move(callback)));
      for (const auto& cc : net_cookies) {
        cookie_manager->SetCanonicalCookie(
            *cc, net::cookie_util::SimulatedCookieSource(*cc, "https"), options,
            base::BindOnce(
                [](base::RepeatingClosure done, net::CookieAccessResult) {
                  done.Run();
                },
                barrier));
      }
      return;
    }
  }

  if (!nav_url.empty()) {
    wc->GetController().LoadURL(GURL(nav_url), Referrer(),
                                ui::PAGE_TRANSITION_TYPED, std::string());
  }
  callback->sendSuccess();
}

}  // namespace protocol
}  // namespace content
