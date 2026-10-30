#include "content/browser/devtools/protocol/context_proxy_support.h"

#include "base/base64.h"
#include "base/command_line.h"
#include "base/containers/flat_set.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/supports_user_data.h"
#include "base/values.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/base/auth.h"
#include "net/base/network_anonymization_key.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "net/proxy_resolution/proxy_config_with_annotation.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "services/network/public/mojom/proxy_config.mojom.h"
#include "url/gurl.h"
#include "url/scheme_host_port.h"

namespace content {
namespace {

const char kContextProxyUserDataKey[] = "browser_context_proxy";

const net::NetworkTrafficAnnotationTag kContextProxyTrafficAnnotation =
    net::DefineNetworkTrafficAnnotation("zzbrowser_context_proxy", R"(
      semantics {
        sender: "zzbrowser Context proxy"
        description:
          "Per-BrowserContext upstream proxy set by Context.setContextOverrides."
        trigger: "Context.setContextOverrides proxy field."
        data: "Traffic from the isolated browser context."
        destination: OTHER
        destination_other: "Embedder-supplied proxy endpoint."
      }
      policy {
        cookies_allowed: NO
        setting: "DevTools Context.setContextOverrides only."
        policy_exception_justification: "Isolated automation context."
      })");

class ContextProxyUserData : public base::SupportsUserData::Data {
 public:
  std::string endpoint;
  std::string username;
  std::string password;
  std::string cache_dir;
  std::string cache_map;
  std::string cache_rules;
  std::string document_url;
  std::string document_html;
  bool cache_disk_load_started = false;
  bool cache_file_checked = false;
  mojo::Remote<network::mojom::ProxyConfigClient> client;
  mojo::Remote<network::mojom::CustomProxyConfigClient> custom_client;
  base::WeakPtrFactory<ContextProxyUserData> weak_factory{this};
};

base::flat_set<std::string>& IsolatedIds() {
  static base::NoDestructor<base::flat_set<std::string>> ids;
  return *ids;
}

bool& PendingIsolatedApply() {
  static bool pending = false;
  return pending;
}

ContextProxyUserData* GetOrCreate(BrowserContext* bc) {
  auto* data = static_cast<ContextProxyUserData*>(
      bc->GetUserData(kContextProxyUserDataKey));
  if (!data) {
    auto owned = std::make_unique<ContextProxyUserData>();
    data = owned.get();
    bc->SetUserData(kContextProxyUserDataKey, std::move(owned));
  }
  return data;
}

GURL ProxyGURL(const std::string& endpoint) {
  if (endpoint.empty())
    return GURL();
  std::string spec = endpoint;
  if (spec.find("://") == std::string::npos)
    spec = "http://" + spec;
  return GURL(spec);
}

// host:port — the form ParseFromString treats as a single proxy for all schemes.
std::string ProxyRulesString(const std::string& endpoint) {
  GURL u = ProxyGURL(endpoint);
  if (!u.is_valid() || u.host().empty())
    return std::string();
  int port = u.EffectiveIntPort();
  if (port <= 0)
    port = 80;
  return u.GetHost() + ":" + std::to_string(port);
}

net::ProxyConfig MakeProxyConfig(const std::string& endpoint) {
  if (endpoint.empty())
    return net::ProxyConfig::CreateDirect();
  std::string rules = ProxyRulesString(endpoint);
  net::ProxyConfig config;
  if (rules.empty())
    return net::ProxyConfig::CreateDirect();
  config.proxy_rules().ParseFromString(rules);
  return config;
}

network::mojom::CustomProxyConfigPtr MakeCustomConfig(
    const std::string& endpoint,
    const std::string& username,
    const std::string& password) {
  auto custom = network::mojom::CustomProxyConfig::New();
  custom->should_override_existing_config = true;
  custom->allow_non_idempotent_methods = true;
  if (endpoint.empty())
    return custom;
  net::ProxyConfig config = MakeProxyConfig(endpoint);
  custom->rules = config.proxy_rules();
  if (!username.empty()) {
    std::string token = base::Base64Encode(username + ":" + password);
    custom->connect_tunnel_headers.SetHeader(
        net::HttpRequestHeaders::kProxyAuthorization, "Basic " + token);
  }
  return custom;
}

void PushAuth(BrowserContext* bc, ContextProxyUserData* data) {
  if (data->username.empty() || data->endpoint.empty())
    return;
  StoragePartition* part = bc->GetDefaultStoragePartition();
  if (!part)
    return;
  network::mojom::NetworkContext* nc = part->GetNetworkContext();
  if (!nc)
    return;
  GURL proxy_url = ProxyGURL(data->endpoint);
  if (!proxy_url.is_valid())
    return;
  net::AuthChallengeInfo challenge;
  challenge.is_proxy = true;
  challenge.challenger = url::SchemeHostPort(proxy_url);
  challenge.scheme = "basic";
  challenge.realm = "";
  net::AuthCredentials creds(base::UTF8ToUTF16(data->username),
                             base::UTF8ToUTF16(data->password));
  nc->AddAuthCacheEntry(challenge, net::NetworkAnonymizationKey(), creds,
                        base::DoNothing());
}

void PushToClients(ContextProxyUserData* data) {
  net::ProxyConfig config = MakeProxyConfig(data->endpoint);
  if (data->client && data->client.is_bound()) {
    data->client->OnProxyConfigUpdated(
        net::ProxyConfigWithAnnotation(config, kContextProxyTrafficAnnotation));
    data->client->FlushProxyConfig(base::DoNothing());
  }
  if (data->custom_client && data->custom_client.is_bound()) {
    data->custom_client->OnCustomProxyConfigUpdated(
        MakeCustomConfig(data->endpoint, data->username, data->password),
        base::DoNothing());
  }
}

}  // namespace

void BeginIsolatedProxyContextCreation() {
  PendingIsolatedApply() = true;
}

void RegisterIsolatedProxyContext(BrowserContext* browser_context) {
  PendingIsolatedApply() = false;
  if (!browser_context)
    return;
  IsolatedIds().insert(browser_context->UniqueId());
  GetOrCreate(browser_context);
}

bool ApplyContextProxyToNetworkParams(
    BrowserContext* browser_context,
    network::mojom::NetworkContextParams* params) {
  if (!browser_context || !params)
    return false;
  const bool pending_create = PendingIsolatedApply();
  const bool known =
      IsolatedIds().contains(browser_context->UniqueId());
  if (!pending_create && !known)
    return false;
  IsolatedIds().insert(browser_context->UniqueId());
  PendingIsolatedApply() = false;
  auto* data = GetOrCreate(browser_context);
  net::ProxyConfig config = MakeProxyConfig(data->endpoint);
  params->initial_proxy_config =
      net::ProxyConfigWithAnnotation(config, kContextProxyTrafficAnnotation);
  mojo::PendingRemote<network::mojom::ProxyConfigClient> pending;
  params->proxy_config_client_receiver =
      pending.InitWithNewPipeAndPassReceiver();
  if (data->client)
    data->client.reset();
  data->client.Bind(std::move(pending));

  params->initial_custom_proxy_config =
      MakeCustomConfig(data->endpoint, data->username, data->password);
  mojo::PendingRemote<network::mojom::CustomProxyConfigClient> custom_pending;
  params->custom_proxy_config_client_receiver =
      custom_pending.InitWithNewPipeAndPassReceiver();
  if (data->custom_client)
    data->custom_client.reset();
  data->custom_client.Bind(std::move(custom_pending));
  return true;
}

void SetContextProxy(BrowserContext* browser_context,
                     const std::string& endpoint,
                     const std::string& username,
                     const std::string& password) {
  if (!browser_context)
    return;
  auto* data = GetOrCreate(browser_context);
  data->endpoint = endpoint;
  data->username = username;
  data->password = password;
  if (!data->client || !data->client.is_bound() ||
      !data->custom_client || !data->custom_client.is_bound()) {
    if (StoragePartition* part =
            browser_context->GetDefaultStoragePartition()) {
      part->GetNetworkContext();
    }
  }
  PushToClients(data);
  PushAuth(browser_context, data);
}

bool GetContextProxy(BrowserContext* browser_context,
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

static bool MapJsonEmpty(const std::string& map) {
  std::string t = std::string(base::TrimWhitespaceASCII(map, base::TRIM_ALL));
  return t.empty() || t == "{}" || t == "null";
}

static void OverlayCacheMap(base::DictValue* working, const std::string& map) {
  if (!working || MapJsonEmpty(map))
    return;
  std::optional<base::DictValue> parsed =
      base::JSONReader::ReadDict(map, /*options=*/0);
  if (!parsed)
    return;
  for (auto kv : *parsed)
    working->Set(kv.first, kv.second.Clone());
}

static void MergeMapIntoData(ContextProxyUserData* data,
                             const std::string& map) {
  if (!data)
    return;
  base::DictValue working;
  if (!MapJsonEmpty(data->cache_map)) {
    std::optional<base::DictValue> parsed =
        base::JSONReader::ReadDict(data->cache_map, /*options=*/0);
    if (parsed)
      working = std::move(*parsed);
  }
  OverlayCacheMap(&working, map);
  std::string out;
  if (!working.empty())
    base::JSONWriter::Write(base::Value(working.Clone()), &out);
  data->cache_map = out.empty() ? "{}" : out;
}

scoped_refptr<base::SequencedTaskRunner> ContextCachePersistRunner() {
  static base::NoDestructor<scoped_refptr<base::SequencedTaskRunner>> runner(
      base::ThreadPool::CreateSequencedTaskRunner(
          {base::MayBlock(), base::TaskPriority::USER_VISIBLE,
           base::TaskShutdownBehavior::SKIP_ON_SHUTDOWN}));
  return *runner;
}

void WriteContextCacheProfile(BrowserContext* browser_context,
                               const std::string& dir,
                               const std::string& rules) {
  if (!browser_context)
    return;
  base::FilePath profile = browser_context->GetPath();
  if (profile.empty())
    return;
  base::DictValue out;
  out.Set("dir", dir);
  out.Set("rules", rules);
  std::string json;
  base::JSONWriter::Write(base::Value(out.Clone()), &json);
  // DevTools applies rules on the UI thread. File IO there trips
  // AssertBlockingAllowed and kills the browser.
  ContextCachePersistRunner()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](base::FilePath path, std::string json) {
            base::WriteFile(path, json);
          },
          profile.AppendASCII("context_cache.json"), std::move(json)));
}

struct LoadedContextCache {
  bool ok = false;
  std::string dir;
  std::string rules;
  std::string map;
};

LoadedContextCache ReadContextCacheFile(base::FilePath path) {
  LoadedContextCache loaded;
  std::string text;
  if (!base::ReadFileToString(path, &text) || text.empty())
    return loaded;
  std::optional<base::DictValue> parsed =
      base::JSONReader::ReadDict(text, /*options=*/0);
  if (!parsed)
    return loaded;
  const std::string* dir = parsed->FindString("dir");
  loaded.dir = dir ? *dir : std::string();
  if (const std::string* rules = parsed->FindString("rules")) {
    loaded.rules = *rules;
  } else if (const base::DictValue* rules_dict = parsed->FindDict("rules")) {
    base::JSONWriter::Write(base::Value(rules_dict->Clone()), &loaded.rules);
  }
  if (const std::string* map = parsed->FindString("map")) {
    loaded.map = *map;
  } else if (!loaded.dir.empty()) {
    base::ReadFileToString(
        base::FilePath::FromUTF8Unsafe(loaded.dir).AppendASCII("_map.json"),
        &loaded.map);
  }
  loaded.ok = true;
  return loaded;
}

void SetContextCache(BrowserContext* browser_context,
                     const std::string& dir,
                     const std::string& map,
                     const std::string& rules);

void MaybeLoadContextCacheFile(BrowserContext* browser_context) {
  if (!browser_context)
    return;
  auto* data = GetOrCreate(browser_context);
  if (data->cache_file_checked)
    return;
  data->cache_file_checked = true;
  if (!data->cache_dir.empty() || !data->cache_map.empty() ||
      !data->cache_rules.empty())
    return;
  base::FilePath path;
  const base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();
  if (cmd->HasSwitch("context-cache-file")) {
    path = base::FilePath::FromUTF8Unsafe(
        cmd->GetSwitchValueASCII("context-cache-file"));
  } else {
    base::FilePath profile = browser_context->GetPath();
    if (profile.empty())
      return;
    path = profile.AppendASCII("context_cache.json");
  }
  auto weak = data->weak_factory.GetWeakPtr();
  ContextCachePersistRunner()->PostTaskAndReplyWithResult(
      FROM_HERE, base::BindOnce(&ReadContextCacheFile, path),
      base::BindOnce(
          [](base::WeakPtr<ContextProxyUserData> weak,
             BrowserContext* browser_context, LoadedContextCache loaded) {
            if (!weak || !loaded.ok)
              return;
            SetContextCache(browser_context, loaded.dir, loaded.map,
                            loaded.rules);
          },
          std::move(weak), browser_context));
}

void SetContextCache(BrowserContext* browser_context,
                     const std::string& dir,
                     const std::string& map,
                     const std::string& rules) {
  if (!browser_context)
    return;
  std::string cache_dir = dir;
  if (cache_dir.empty() && !rules.empty() && rules != "{}") {
    base::FilePath profile = browser_context->GetPath();
    if (!profile.empty()) {
      base::FilePath automatic = profile.AppendASCII("ContextCache");
      ContextCachePersistRunner()->PostTask(
          FROM_HERE,
          base::BindOnce(
              [](base::FilePath path) { base::CreateDirectory(path); },
              automatic));
      cache_dir = automatic.AsUTF8Unsafe();
    }
  }
  auto* data = GetOrCreate(browser_context);
  data->cache_dir = cache_dir;
  data->cache_rules = rules;
  MergeMapIntoData(data, map);
  WriteContextCacheProfile(browser_context, cache_dir, rules);
}

void ScheduleContextCacheDiskLoad(BrowserContext* browser_context) {
  if (!browser_context)
    return;
  auto* data = GetOrCreate(browser_context);
  if (data->cache_dir.empty() || data->cache_disk_load_started)
    return;
  data->cache_disk_load_started = true;
  auto weak = data->weak_factory.GetWeakPtr();
  const std::string dir = data->cache_dir;
  ContextCachePersistRunner()->PostTaskAndReplyWithResult(
      FROM_HERE,
      base::BindOnce(
          [](std::string dir) {
            std::string disk;
            base::FilePath path =
                base::FilePath::FromUTF8Unsafe(dir).AppendASCII("_map.json");
            base::ReadFileToString(path, &disk);
            return disk;
          },
          dir),
      base::BindOnce(
          [](base::WeakPtr<ContextProxyUserData> weak, std::string disk) {
            if (!weak || disk.empty())
              return;
            MergeMapIntoData(weak.get(), disk);
          },
          std::move(weak)));
}

base::OnceCallback<void(std::string)> BindContextCacheMapMerge(
    BrowserContext* browser_context) {
  if (!browser_context)
    return base::OnceCallback<void(std::string)>();
  auto* data = GetOrCreate(browser_context);
  auto weak = data->weak_factory.GetWeakPtr();
  return base::BindOnce(
      [](base::WeakPtr<ContextProxyUserData> weak, std::string json) {
        if (!weak)
          return;
        MergeMapIntoData(weak.get(), json);
      },
      std::move(weak));
}

base::OnceClosure CallbackIfContextCacheAlive(BrowserContext* browser_context,
                                              base::OnceClosure task) {
  if (!browser_context || !task)
    return base::OnceClosure();
  auto* data = GetOrCreate(browser_context);
  auto weak = data->weak_factory.GetWeakPtr();
  return base::BindOnce(
      [](base::WeakPtr<ContextProxyUserData> weak, base::OnceClosure task) {
        if (!weak || !task)
          return;
        std::move(task).Run();
      },
      std::move(weak), std::move(task));
}

bool GetContextCache(BrowserContext* browser_context,
                     std::string* dir,
                     std::string* map,
                     std::string* rules) {
  if (!browser_context)
    return false;
  auto* data = static_cast<ContextProxyUserData*>(
      browser_context->GetUserData(kContextProxyUserDataKey));
  if (!data || (data->cache_dir.empty() && data->cache_map.empty() &&
                data->cache_rules.empty()))
    return false;
  if (dir)
    *dir = data->cache_dir;
  if (map)
    *map = data->cache_map;
  if (rules)
    *rules = data->cache_rules;
  return true;
}

void SetContextDocument(BrowserContext* browser_context,
                        const std::string& url,
                        const std::string& html) {
  if (!browser_context)
    return;
  auto* data = GetOrCreate(browser_context);
  data->document_url = url;
  data->document_html = html;
}

bool GetContextDocument(BrowserContext* browser_context,
                        std::string* url,
                        std::string* html) {
  if (!browser_context)
    return false;
  auto* data = static_cast<ContextProxyUserData*>(
      browser_context->GetUserData(kContextProxyUserDataKey));
  if (!data || data->document_url.empty())
    return false;
  if (url)
    *url = data->document_url;
  if (html)
    *html = data->document_html;
  return true;
}

}  // namespace content

