#ifndef CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_PROXY_SUPPORT_H_
#define CONTENT_BROWSER_DEVTOOLS_PROTOCOL_CONTEXT_PROXY_SUPPORT_H_

#include <string>

#include "base/functional/callback.h"
#include "base/task/sequenced_task_runner.h"

namespace network {
namespace mojom {
class NetworkContextParams;
}
}  // namespace network

namespace content {

class BrowserContext;

void BeginIsolatedProxyContextCreation();
void RegisterIsolatedProxyContext(BrowserContext* browser_context);
bool ApplyContextProxyToNetworkParams(
    BrowserContext* browser_context,
    network::mojom::NetworkContextParams* params);
void SetContextProxy(BrowserContext* browser_context,
                     const std::string& endpoint,
                     const std::string& username,
                     const std::string& password);
bool GetContextProxy(BrowserContext* browser_context,
                     std::string* endpoint,
                     std::string* username,
                     std::string* password);
void SetContextCache(BrowserContext* browser_context,
                     const std::string& dir,
                     const std::string& map,
                     const std::string& rules);
bool GetContextCache(BrowserContext* browser_context,
                     std::string* dir,
                     std::string* map,
                     std::string* rules);
// Shared blocking sequence for all Contexts that persist into the same cache
// dir. Disk load and _map.json updates must use this runner.
scoped_refptr<base::SequencedTaskRunner> ContextCachePersistRunner();
// Load <dir>/_map.json off the UI thread. No-op if already started or dir empty.
void ScheduleContextCacheDiskLoad(BrowserContext* browser_context);
// Capture a WeakPtr now; the returned callback is safe after BrowserContext
// destruction (it becomes a no-op).
base::OnceCallback<void(std::string)> BindContextCacheMapMerge(
    BrowserContext* browser_context);
void SetContextDocument(BrowserContext* browser_context,
                        const std::string& url,
                        const std::string& html);
bool GetContextDocument(BrowserContext* browser_context,
                        std::string* url,
                        std::string* html);

}  // namespace content

#endif
