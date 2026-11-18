#ifndef CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_REQUEST_INTERCEPTOR_H_
#define CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_REQUEST_INTERCEPTOR_H_

#include <string>

namespace network {
namespace mojom {
class URLLoaderFactoryOverride;
}
}  // namespace network

namespace content {

class DevToolsAgentHostImpl;
class StoragePartition;
class BrowserContext;

// Installs a per-BrowserContext URLLoaderFactory wrapper that applies
// Context cache rules (captures > callbacks > HIT > blocks > allow-miss >
// observe > pass) without Fetch.enable on "*". HIT requires a disk file;
// eligible GET/POST 2xx misses are forwarded and written under cache dir.
// POST map keys are "POST {url} {sha256(body)}" so different AJAX bodies miss.
bool MaybeInstallContextRequestInterceptor(
    DevToolsAgentHostImpl* agent_host,
    StoragePartition* storage_partition,
    network::mojom::URLLoaderFactoryOverride* intercepting_factory);

// Current-rule verdict for a URL already in the Network log.
// html, hit, block, allow-miss, observe, capture, callback, or pass.
std::string ExplainContextCache(BrowserContext* browser_context,
                                const std::string& method,
                                const std::string& url,
                                const std::string& body_sha256);

}  // namespace content

#endif
