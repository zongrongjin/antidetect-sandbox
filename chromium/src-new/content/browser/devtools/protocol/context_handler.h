#ifndef CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_HANDLER_H_
#define CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_HANDLER_H_

#include <memory>
#include <optional>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "content/browser/devtools/protocol/context.h"
#include "content/browser/devtools/protocol/devtools_domain_handler.h"

namespace content {

class RenderFrameHostImpl;
class WebContentsImpl;

namespace protocol {

class ContextHandler : public DevToolsDomainHandler, public Context::Backend {
 public:
  ContextHandler();

  ContextHandler(const ContextHandler&) = delete;
  ContextHandler& operator=(const ContextHandler&) = delete;

  ~ContextHandler() override;

  void Wire(UberDispatcher* dispatcher) override;
  void SetRenderer(int process_host_id,
                   RenderFrameHostImpl* frame_host) override;

  void SetContextOverrides(
      std::optional<String> fingerprint,
      std::unique_ptr<Context::ProxyConfig> proxy,
      std::unique_ptr<Context::CacheConfig> cache,
      std::unique_ptr<protocol::Array<Context::CookieParam>> cookies,
      std::optional<String> url,
      std::optional<String> html,
      std::unique_ptr<SetContextOverridesCallback> callback) override;

  void GetCacheState(std::unique_ptr<GetCacheStateCallback> callback) override;

  void ExplainCache(
      std::unique_ptr<protocol::Array<Context::CacheExplainRequest>> requests,
      std::unique_ptr<ExplainCacheCallback> callback) override;

  void NotifyMatch(const std::string& kind, const std::string& url);
  void NotifyCacheDecision(const std::string& request_id,
                           const std::string& url,
                           const std::string& action);

 private:
  WebContentsImpl* GetWebContents();

  raw_ptr<RenderFrameHostImpl> host_ = nullptr;
  std::unique_ptr<Context::Frontend> frontend_;
  base::WeakPtrFactory<ContextHandler> weak_factory_{this};
};

}  // namespace protocol
}  // namespace content

#endif  // CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_HANDLER_H_
