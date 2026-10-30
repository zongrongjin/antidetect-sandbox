#include "content/browser/devtools/protocol/context_request_interceptor.h"

#include <algorithm>
#include <array>
#include <string>
#include <utility>
#include <vector>

#include "base/compiler_specific.h"
#include "base/containers/span.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/memory/raw_ptr.h"
#include "base/strings/pattern.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "content/browser/devtools/devtools_agent_host_impl.h"
#include "content/browser/devtools/protocol/context.h"
#include "content/browser/devtools/protocol/context_handler.h"
#include "content/browser/devtools/protocol/context_proxy_support.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/devtools_agent_host.h"
#include "content/public/browser/storage_partition.h"
#include "crypto/hash.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "mojo/public/cpp/bindings/receiver_set.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "mojo/public/cpp/bindings/self_owned_receiver.h"
#include "mojo/public/cpp/base/big_buffer.h"
#include "mojo/public/cpp/system/data_pipe.h"
#include "mojo/public/cpp/system/data_pipe_drainer.h"
#include "net/base/net_errors.h"
#include "net/http/http_connection_info.h"
#include "net/http/http_response_headers.h"
#include "net/http/http_util.h"
#include "net/url_request/redirect_info.h"
#include "services/network/public/cpp/data_element.h"
#include "services/network/public/cpp/parsed_headers.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/resource_request_body.h"
#include "services/network/public/cpp/url_loader_completion_status.h"
#include "services/network/public/mojom/early_hints.mojom.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "services/network/public/mojom/url_loader.mojom.h"
#include "services/network/public/mojom/url_loader_factory.mojom.h"
#include "services/network/public/mojom/url_response_head.mojom.h"
#include "third_party/brotli/include/brotli/decode.h"
#include "third_party/zlib/zlib.h"
#include "url/gurl.h"

namespace content {
namespace {

bool MatchAny(const std::string& url, const std::vector<std::string>& pats) {
  for (const auto& pat : pats) {
    if (pat.empty())
      continue;
    if (pat == url || pat == "*" || base::MatchPattern(url, pat))
      return true;
  }
  return false;
}

std::vector<std::string> ListFrom(const base::DictValue* rules,
                                  const char* key) {
  std::vector<std::string> out;
  if (!rules)
    return out;
  const base::ListValue* list = rules->FindList(key);
  if (!list)
    return out;
  for (const auto& item : *list) {
    if (item.is_string())
      out.push_back(item.GetString());
  }
  return out;
}

double NumberFrom(const base::DictValue* dict, const char* key, double fallback) {
  if (!dict)
    return fallback;
  if (std::optional<double> d = dict->FindDouble(key))
    return *d;
  if (std::optional<int> i = dict->FindInt(key))
    return static_cast<double>(*i);
  return fallback;
}

struct UrlLimits {
  double ttl = 0;
  double max_entry = 10.0 * 1024 * 1024;
  bool limit_status = false;
  std::vector<int> statuses;
};

bool PatternHits(const std::string& url, const std::string& pat) {
  return !pat.empty() && (pat == url || pat == "*" || base::MatchPattern(url, pat));
}

void ReadStatusList(const base::DictValue* dict, UrlLimits* limits) {
  const base::ListValue* list = dict ? dict->FindList("cacheableStatus") : nullptr;
  if (!list || list->empty())
    return;
  limits->limit_status = true;
  for (const auto& item : *list) {
    if (item.is_int())
      limits->statuses.push_back(item.GetInt());
    else if (item.is_double())
      limits->statuses.push_back(static_cast<int>(item.GetDouble()));
  }
}

UrlLimits LimitsFor(const std::string& url, const base::DictValue* rules) {
  UrlLimits limits;
  if (!rules)
    return limits;
  if (const base::ListValue* items = rules->FindList("items")) {
    for (const auto& value : *items) {
      const base::DictValue* item = value.GetIfDict();
      if (!item)
        continue;
      const std::string* kind = item->FindString("kind");
      if (!kind || *kind != "include")
        continue;
      if (std::optional<bool> enabled = item->FindBool("enabled");
          enabled && !*enabled) {
        continue;
      }
      const std::string* pattern = item->FindString("pattern");
      if (!pattern || !PatternHits(url, *pattern))
        continue;
      limits.ttl = NumberFrom(item, "ttl", 0);
      limits.max_entry = NumberFrom(item, "maxEntry", 10.0 * 1024 * 1024);
      ReadStatusList(item, &limits);
      return limits;
    }
  }
  limits.ttl = NumberFrom(rules, "ttl", 0);
  limits.max_entry = NumberFrom(rules, "maxEntry", 10.0 * 1024 * 1024);
  ReadStatusList(rules, &limits);
  return limits;
}

bool LooksLikeSha256Hex(const std::string& s) {
  if (s.size() != 64)
    return false;
  for (char c : s) {
    if (!base::IsHexDigit(c))
      return false;
  }
  return true;
}

const base::DictValue* FindHitEntry(const base::DictValue* index,
                                    const std::string& key) {
  if (!index)
    return nullptr;
  if (const base::DictValue* entry = index->FindDict(key))
    return entry;
  // Kernel POST keys append " {sha256}". Python map uses "POST {url}".
  if (base::StartsWith(key, "POST ", base::CompareCase::SENSITIVE)) {
    size_t sp = key.rfind(' ');
    if (sp != std::string::npos && sp > 5 &&
        LooksLikeSha256Hex(key.substr(sp + 1))) {
      if (const base::DictValue* entry = index->FindDict(key.substr(0, sp)))
        return entry;
    }
  }
  GURL g(key);
  if (g.is_valid() && g.has_ref()) {
    GURL::Replacements r;
    r.ClearRef();
    if (const base::DictValue* entry =
            index->FindDict(g.ReplaceComponents(r).spec()))
      return entry;
  }
  return nullptr;
}

bool DocumentUrlMatch(const std::string& request, const std::string& target) {
  if (request == target)
    return true;
  GURL a(request);
  GURL b(target);
  if (!a.is_valid() || !b.is_valid())
    return false;
  GURL::Replacements r;
  r.ClearRef();
  a = a.ReplaceComponents(r);
  b = b.ReplaceComponents(r);
  if (a == b)
    return true;
  std::string as = a.spec();
  std::string bs = b.spec();
  if (!as.empty() && as.back() == '/')
    as.pop_back();
  if (!bs.empty() && bs.back() == '/')
    bs.pop_back();
  return as == bs;
}

bool CacheExcluded(const std::string& url, const base::DictValue* rules) {
  std::vector<std::string> include = ListFrom(rules, "include");
  if (!include.empty() && !MatchAny(url, include))
    return true;
  return MatchAny(url, ListFrom(rules, "exclude"));
}

bool EntryExpired(const base::DictValue* entry,
                  const std::string& url,
                  const base::DictValue* rules) {
  double ttl = LimitsFor(url, rules).ttl;
  if (ttl <= 0 || !entry)
    return false;
  if (!entry->Find("created_at"))
    return false;
  double created = NumberFrom(entry, "created_at", 0);
  double now = (base::Time::Now() - base::Time::UnixEpoch()).InSecondsF();
  return now - created > ttl;
}

std::string MatchAction(const std::string& url,
                        const std::string& cache_key,
                        const base::DictValue* rules,
                        const base::DictValue* index) {
  if (MatchAny(url, ListFrom(rules, "captures")))
    return "capture";
  if (MatchAny(url, ListFrom(rules, "callbacks")))
    return "callback";
  const base::DictValue* entry = FindHitEntry(index, cache_key);
  if (entry && !CacheExcluded(url, rules) && !EntryExpired(entry, url, rules))
    return "hit";
  if (MatchAny(url, ListFrom(rules, "blocks")))
    return "block";
  if (MatchAny(url, ListFrom(rules, "allowMiss")))
    return "allow-miss";
  if (MatchAny(url, ListFrom(rules, "observe")))
    return "observe";
  return "pass";
}

void DispatchMatch(BrowserContext* bc,
                   const std::string& kind,
                   const std::string& url) {
  if (!bc || (kind != "capture" && kind != "callback" && kind != "observe"))
    return;
  for (auto& host : DevToolsAgentHost::GetOrCreateAll()) {
    if (host->GetBrowserContext() != bc)
      continue;
    auto* impl = static_cast<DevToolsAgentHostImpl*>(host.get());
    for (auto* h : impl->HandlersByName<protocol::ContextHandler>(
             protocol::Context::Metainfo::domainName)) {
      h->NotifyMatch(kind, url);
    }
  }
}

void DispatchCacheDecision(BrowserContext* bc,
                           const std::string& request_id,
                           const std::string& url,
                           const std::string& action) {
  if (!bc || action.empty())
    return;
  for (auto& host : DevToolsAgentHost::GetOrCreateAll()) {
    if (host->GetBrowserContext() != bc)
      continue;
    auto* impl = static_cast<DevToolsAgentHostImpl*>(host.get());
    for (auto* h : impl->HandlersByName<protocol::ContextHandler>(
             protocol::Context::Metainfo::domainName)) {
      h->NotifyCacheDecision(request_id, url, action);
    }
  }
}

std::string DevToolsRequestId(const network::ResourceRequest& request) {
  return request.devtools_request_id.value_or(std::string());
}

bool SkipHeader(const std::string& name) {
  return base::EqualsCaseInsensitiveASCII(name, "content-encoding") ||
         base::EqualsCaseInsensitiveASCII(name, "content-length") ||
         base::EqualsCaseInsensitiveASCII(name, "set-cookie");
}

bool LooksLikeGzip(const std::string& body) {
  return body.size() >= 2 && static_cast<uint8_t>(body[0]) == 0x1f &&
         static_cast<uint8_t>(body[1]) == 0x8b;
}

bool GzipInflate(const std::string& in, std::string* out) {
  if (!LooksLikeGzip(in) || !out)
    return false;
  z_stream zs = {};
  if (inflateInit2(&zs, 16 + MAX_WBITS) != Z_OK)
    return false;
  out->clear();
  int ret = Z_OK;
  UNSAFE_BUFFERS({
    zs.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(in.data()));
    zs.avail_in = static_cast<uInt>(in.size());
    char buf[4096];
    do {
      zs.next_out = reinterpret_cast<Bytef*>(buf);
      zs.avail_out = sizeof(buf);
      ret = inflate(&zs, Z_NO_FLUSH);
      if (ret != Z_OK && ret != Z_STREAM_END) {
        inflateEnd(&zs);
        return false;
      }
      out->append(buf, sizeof(buf) - zs.avail_out);
    } while (ret != Z_STREAM_END);
  });
  inflateEnd(&zs);
  return true;
}

bool GzipDeflate(const std::string& in, std::string* out) {
  if (!out)
    return false;
  z_stream zs = {};
  if (deflateInit2(&zs, Z_DEFAULT_COMPRESSION, Z_DEFLATED, 16 + MAX_WBITS, 8,
                   Z_DEFAULT_STRATEGY) != Z_OK)
    return false;
  out->clear();
  int ret = Z_OK;
  UNSAFE_BUFFERS({
    zs.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(in.data()));
    zs.avail_in = static_cast<uInt>(in.size());
    char buf[4096];
    do {
      zs.next_out = reinterpret_cast<Bytef*>(buf);
      zs.avail_out = sizeof(buf);
      ret = deflate(&zs, Z_FINISH);
      if (ret != Z_OK && ret != Z_STREAM_END) {
        deflateEnd(&zs);
        return false;
      }
      out->append(buf, sizeof(buf) - zs.avail_out);
    } while (ret != Z_STREAM_END);
  });
  deflateEnd(&zs);
  return !out->empty();
}

int64_t EncodedSizeForHit(const std::string& decoded, int64_t stored_encoded) {
  const int64_t decoded_n = static_cast<int64_t>(decoded.size());
  if (stored_encoded > 0 && stored_encoded < decoded_n)
    return stored_encoded;
  std::string gz;
  if (GzipDeflate(decoded, &gz)) {
    const int64_t gz_n = static_cast<int64_t>(gz.size());
    if (gz_n > 0 && gz_n < decoded_n)
      return gz_n;
  }
  return decoded_n;
}

bool EncodingIsBrotli(const std::string& encoding) {
  std::string enc = base::ToLowerASCII(encoding);
  return enc == "br" || enc == "brotli" ||
         base::StartsWith(enc, "br;", base::CompareCase::SENSITIVE);
}

bool BrotliInflate(const std::string& in, std::string* out) {
  if (in.empty() || !out)
    return false;
  BrotliDecoderState* state =
      BrotliDecoderCreateInstance(nullptr, nullptr, nullptr);
  if (!state)
    return false;
  out->clear();
  const uint8_t* next_in = reinterpret_cast<const uint8_t*>(in.data());
  size_t avail_in = in.size();
  BrotliDecoderResult result = BROTLI_DECODER_RESULT_ERROR;
  UNSAFE_BUFFERS({
    uint8_t buf[4096];
    do {
      size_t avail_out = sizeof(buf);
      uint8_t* next_out = buf;
      result = BrotliDecoderDecompressStream(state, &avail_in, &next_in,
                                             &avail_out, &next_out, nullptr);
      size_t produced = sizeof(buf) - avail_out;
      if (produced)
        out->append(reinterpret_cast<char*>(buf), produced);
    } while (result == BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT);
  });
  BrotliDecoderDestroyInstance(state);
  return result == BROTLI_DECODER_RESULT_SUCCESS && !out->empty();
}

// Persist identity (decoded) bytes. Replay strips Content-Encoding.
// gzip/br still on the pipe are inflated; already-decoded bodies are kept.
std::string DecodePersistBody(const std::string& body,
                              const std::string& content_encoding) {
  std::string decoded;
  if (LooksLikeGzip(body) && GzipInflate(body, &decoded))
    return decoded;
  if (EncodingIsBrotli(content_encoding) && BrotliInflate(body, &decoded))
    return decoded;
  return body;
}

std::string FileHash(const std::string& url) {
  std::array<uint8_t, 32> digest = crypto::hash::Sha256(base::as_byte_span(url));
  return base::ToLowerASCII(base::HexEncode(digest));
}

std::string RequestBodyBytes(const network::ResourceRequest& request) {
  if (!request.request_body)
    return std::string();
  const std::vector<network::DataElement>* elements =
      request.request_body->elements();
  if (!elements)
    return std::string();
  std::string out;
  for (const auto& element : *elements) {
    if (element.type() != network::DataElement::Tag::kBytes)
      continue;
    base::span<const uint8_t> bytes =
        element.As<network::DataElementBytes>().bytes();
    if (bytes.empty())
      continue;
    out.append(reinterpret_cast<const char*>(bytes.data()), bytes.size());
  }
  return out;
}

std::string CacheKey(const std::string& method,
                     const std::string& url,
                     const std::string& body) {
  std::string m = base::ToUpperASCII(method);
  if (m.empty() || m == "GET" || m == "HEAD")
    return url;
  std::string key = m + " " + url;
  if (!body.empty()) {
    key.push_back(' ');
    key.append(FileHash(body));
  }
  return key;
}

bool StatusCacheable(int status,
                     const std::string& url,
                     const base::DictValue* rules) {
  UrlLimits limits = LimitsFor(url, rules);
  if (!limits.limit_status)
    return status >= 200 && status < 300;
  for (int code : limits.statuses) {
    if (code == status)
      return true;
  }
  return false;
}

bool ShouldPersist(const std::string& method,
                   const std::string& url,
                   const std::string& dir,
                   const std::string& action,
                   const base::DictValue* rules) {
  if (dir.empty())
    return false;
  if (!base::EqualsCaseInsensitiveASCII(method, "GET") &&
      !base::EqualsCaseInsensitiveASCII(method, "POST"))
    return false;
  if (action == "capture" || action == "callback" || action == "block")
    return false;
  if (CacheExcluded(url, rules))
    return false;
  return true;
}

class IdleLoader : public network::mojom::URLLoader {
 public:
  void FollowRedirect(network::HttpRequestHeadersUpdateParams /*headers*/,
                      const std::optional<GURL>& /*new_url*/) override {}
  void SetPriority(net::RequestPriority /*priority*/,
                   int32_t /*intra_priority_value*/) override {}
};

void BindIdleLoader(
    mojo::PendingReceiver<network::mojom::URLLoader> receiver) {
  mojo::MakeSelfOwnedReceiver(std::make_unique<IdleLoader>(),
                              std::move(receiver));
}

void FailRequest(mojo::PendingRemote<network::mojom::URLLoaderClient> client,
                 int net_error) {
  mojo::Remote<network::mojom::URLLoaderClient> remote(std::move(client));
  remote->OnComplete(network::URLLoaderCompletionStatus(net_error));
}

void FinishServeHit(
    const std::string& url,
    const std::string& raw,
    mojo::PendingRemote<network::mojom::URLLoaderClient> client,
    int64_t stored_encoded,
    std::optional<std::string> body_opt) {
  if (!body_opt) {
    FailRequest(std::move(client), net::ERR_FILE_NOT_FOUND);
    return;
  }
  const std::string& body = *body_opt;
  auto head = network::mojom::URLResponseHead::New();
  head->headers = base::MakeRefCounted<net::HttpResponseHeaders>(
      net::HttpUtil::AssembleRawHeaders(raw));
  if (head->headers)
    head->headers->GetMimeType(&head->mime_type);
  if (head->mime_type.empty()) {
    if (base::EndsWith(url, ".js", base::CompareCase::INSENSITIVE_ASCII))
      head->mime_type = "application/javascript";
    else
      head->mime_type = "text/html";
  }
  head->charset = "utf-8";
  // Renderer gets identity bytes (network service style). Performance sizes
  // come from completion encoded/decoded lengths, not the pipe.
  const int64_t decoded_n = static_cast<int64_t>(body.size());
  const int64_t encoded_n = EncodedSizeForHit(body, stored_encoded);
  head->content_length = decoded_n;
  head->network_accessed = true;
  head->was_fetched_via_cache = false;
  head->is_validated = false;
  head->connection_info = net::HttpConnectionInfo::kHTTP1_1;
  head->alpn_negotiated_protocol = "http/1.1";
  head->encoded_data_length = encoded_n + 300;
  GURL gurl(url);
  head->parsed_headers =
      network::PopulateParsedHeaders(head->headers.get(), gurl);

  mojo::ScopedDataPipeProducerHandle producer;
  mojo::ScopedDataPipeConsumerHandle consumer;
  MojoCreateDataPipeOptions options;
  options.struct_size = sizeof(MojoCreateDataPipeOptions);
  options.flags = MOJO_CREATE_DATA_PIPE_FLAG_NONE;
  options.element_num_bytes = 1;
  // Capacity must exceed the body so one write cannot SHOULD_WAIT, and so
  // 150KB+ JS HITs do not silently truncate (exact-size pipes often fail
  // WriteAllData; empty body + content-length leaves the script hanging).
  options.capacity_num_bytes = static_cast<uint32_t>(
      std::max<size_t>(body.size() + 64 * 1024, 256 * 1024));
  MojoResult pr = mojo::CreateDataPipe(&options, producer, consumer);
  if (pr != MOJO_RESULT_OK) {
    FailRequest(std::move(client), net::ERR_INSUFFICIENT_RESOURCES);
    return;
  }
  mojo::Remote<network::mojom::URLLoaderClient> remote(std::move(client));
  remote->OnReceiveResponse(std::move(head), std::move(consumer), std::nullopt);
  size_t offset = 0;
  while (offset < body.size()) {
    size_t written = 0;
    MojoResult wr = producer->WriteData(base::as_byte_span(body).subspan(offset),
                                        MOJO_WRITE_DATA_FLAG_NONE, written);
    if (wr != MOJO_RESULT_OK || written == 0)
      break;
    offset += written;
  }
  producer.reset();
  network::URLLoaderCompletionStatus done(
      offset == body.size() ? net::OK : net::ERR_CONNECTION_CLOSED);
  done.exists_in_cache = false;
  done.decoded_body_length = static_cast<int64_t>(offset);
  done.encoded_body_length = encoded_n;
  // Blink CacheState is kLocal when encoded_data_length is 0 (transferSize=0,
  // deliveryType=cache). Non-zero + kNone => transferSize = encoded+300.
  done.encoded_data_length = encoded_n + 300;
  remote->OnComplete(done);
}

void ServeHit(const std::string& cache_dir,
              const std::string& url,
              const base::DictValue* entry,
              mojo::PendingRemote<network::mojom::URLLoaderClient> client) {
  if (!entry) {
    FailRequest(std::move(client), net::ERR_FILE_NOT_FOUND);
    return;
  }
  const std::string* rel = entry->FindString("file");
  if (!rel || cache_dir.empty()) {
    FailRequest(std::move(client), net::ERR_FILE_NOT_FOUND);
    return;
  }
  base::FilePath root = base::FilePath::FromUTF8Unsafe(cache_dir);
  base::FilePath file = base::FilePath::FromUTF8Unsafe(*rel);
  if (!file.IsAbsolute())
    file = root.Append(file);
  int status = entry->FindInt("status").value_or(200);
  std::string raw = "HTTP/1.1 " + std::to_string(status) + " OK\n";
  const base::DictValue* headers = entry->FindDict("headers");
  if (headers) {
    for (auto kv : *headers) {
      if (SkipHeader(kv.first) || !kv.second.is_string())
        continue;
      raw += kv.first + ": " + kv.second.GetString() + "\n";
    }
  }
  raw += "\n";
  const int64_t stored_encoded =
      static_cast<int64_t>(NumberFrom(entry, "encoded_body_length", -1));
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock()},
      base::BindOnce(
          [](base::FilePath path) -> std::optional<std::string> {
            std::string body;
            if (!base::ReadFileToString(path, &body))
              return std::nullopt;
            return body;
          },
          file),
      base::BindOnce(&FinishServeHit, url, raw, std::move(client),
                     stored_encoded));
}

struct PersistWriteResult {
  bool ok = false;
  std::string map_json;
};

PersistWriteResult WritePersistFiles(std::string dir,
                                     std::string url,
                                     std::string hex,
                                     int status,
                                     base::DictValue headers,
                                     std::string body,
                                     double created_at,
                                     int64_t encoded_body_length) {
  PersistWriteResult result;
  if (dir.empty() || hex.size() < 2)
    return result;
  base::FilePath root = base::FilePath::FromUTF8Unsafe(dir);
  base::FilePath file = root.AppendASCII("data")
                            .AppendASCII(hex.substr(0, 2))
                            .AppendASCII(hex);
  if (!base::CreateDirectory(file.DirName()))
    return result;
  if (!base::WriteFile(file, body))
    return result;

  std::string rel = "data/" + hex.substr(0, 2) + "/" + hex;
  base::FilePath map_path = root.AppendASCII("_map.json");
  base::DictValue index;
  std::string existing;
  if (base::ReadFileToString(map_path, &existing) && !existing.empty()) {
    std::optional<base::DictValue> parsed =
        base::JSONReader::ReadDict(existing, /*options=*/0);
    if (parsed)
      index = std::move(*parsed);
  }
  base::DictValue entry;
  entry.Set("file", rel);
  entry.Set("status", status);
  entry.Set("headers", std::move(headers));
  entry.Set("created_at", created_at);
  if (encoded_body_length > 0 &&
      encoded_body_length < static_cast<int64_t>(body.size())) {
    entry.Set("encoded_body_length",
              static_cast<double>(encoded_body_length));
  }
  index.Set(url, std::move(entry));
  std::string json;
  if (!base::JSONWriter::Write(base::Value(index.Clone()), &json))
    return result;
  base::FilePath tmp = map_path.AddExtensionASCII(".tmp");
  if (!base::WriteFile(tmp, json))
    return result;
  base::ReplaceFile(tmp, map_path, nullptr);
  result.ok = true;
  result.map_json = std::move(json);
  return result;
}



void PipeBodyToClient(
    mojo::Remote<network::mojom::URLLoaderClient>& remote,
    network::mojom::URLResponseHeadPtr head,
    const std::string& body,
    std::optional<mojo_base::BigBuffer> cached_metadata) {
  mojo::ScopedDataPipeProducerHandle producer;
  mojo::ScopedDataPipeConsumerHandle consumer;
  MojoCreateDataPipeOptions options;
  options.struct_size = sizeof(MojoCreateDataPipeOptions);
  options.flags = MOJO_CREATE_DATA_PIPE_FLAG_NONE;
  options.element_num_bytes = 1;
  options.capacity_num_bytes = static_cast<uint32_t>(
      std::max<size_t>(body.size() + 64 * 1024, 256 * 1024));
  if (mojo::CreateDataPipe(&options, producer, consumer) != MOJO_RESULT_OK) {
    remote->OnComplete(
        network::URLLoaderCompletionStatus(net::ERR_INSUFFICIENT_RESOURCES));
    return;
  }
  remote->OnReceiveResponse(std::move(head), std::move(consumer),
                            std::move(cached_metadata));
  size_t offset = 0;
  while (offset < body.size()) {
    size_t written = 0;
    MojoResult wr = producer->WriteData(base::as_byte_span(body).subspan(offset),
                                        MOJO_WRITE_DATA_FLAG_NONE, written);
    if (wr != MOJO_RESULT_OK || written == 0)
      break;
    offset += written;
  }
  producer.reset();
}

class PersistClient : public network::mojom::URLLoaderClient,
                      public mojo::DataPipeDrainer::Client {
 public:
  PersistClient(BrowserContext* bc,
                std::string dir,
                std::string url,
                std::string page_url,
                std::string devtools_request_id,
                base::DictValue rules,
                scoped_refptr<base::SequencedTaskRunner> persist_runner,
                mojo::PendingRemote<network::mojom::URLLoaderClient> downstream)
      : bc_(bc),
        dir_(std::move(dir)),
        url_(std::move(url)),
        page_url_(std::move(page_url)),
        devtools_request_id_(std::move(devtools_request_id)),
        rules_(std::move(rules)),
        persist_runner_(std::move(persist_runner)),
        downstream_(std::move(downstream)) {}

  void OnReceiveEarlyHints(
      network::mojom::EarlyHintsPtr early_hints) override {
    if (downstream_)
      downstream_->OnReceiveEarlyHints(std::move(early_hints));
  }

  void OnReceiveResponse(
      network::mojom::URLResponseHeadPtr head,
      mojo::ScopedDataPipeConsumerHandle body,
      std::optional<mojo_base::BigBuffer> cached_metadata) override {
    double max_entry = LimitsFor(page_url_, &rules_).max_entry;
    if (head && head->content_length > 0 && max_entry > 0 &&
        static_cast<double>(head->content_length) > max_entry) {
      skip_persist_ = true;
      if (downstream_) {
        downstream_->OnReceiveResponse(std::move(head), std::move(body),
                                       std::move(cached_metadata));
      }
      body_done_ = true;
      response_sent_ = true;
      MaybeFinish();
      return;
    }
    head_ = std::move(head);
    cached_metadata_ = std::move(cached_metadata);
    if (head_ && head_->headers) {
      status_ = head_->headers->response_code();
      size_t iter = 0;
      std::string name, value;
      while (head_->headers->EnumerateHeaderLines(&iter, &name, &value)) {
        if (base::EqualsCaseInsensitiveASCII(name, "content-encoding"))
          content_encoding_ = value;
        if (SkipHeader(name))
          continue;
        headers_.Set(name, value);
      }
    }
    if (!body.is_valid()) {
      body_done_ = true;
      MaybeForwardResponse();
      MaybeFinish();
      return;
    }
    drainer_ = std::make_unique<mojo::DataPipeDrainer>(this, std::move(body));
  }

  void OnReceiveRedirect(const net::RedirectInfo& redirect_info,
                         network::mojom::URLResponseHeadPtr head) override {
    if (downstream_)
      downstream_->OnReceiveRedirect(redirect_info, std::move(head));
  }

  void OnUploadProgress(int64_t current_position,
                        int64_t total_size,
                        OnUploadProgressCallback ack_callback) override {
    if (downstream_) {
      downstream_->OnUploadProgress(current_position, total_size,
                                    std::move(ack_callback));
    }
  }

  void OnTransferSizeUpdated(int32_t transfer_size_diff) override {
    if (downstream_)
      downstream_->OnTransferSizeUpdated(transfer_size_diff);
  }

  void OnComplete(const network::URLLoaderCompletionStatus& status) override {
    complete_status_ = status;
    complete_received_ = true;
    MaybeFinish();
  }

  void OnDataAvailable(base::span<const uint8_t> data) override {
    body_.reserve(body_.size() + data.size());
    for (uint8_t b : data)
      body_.push_back(static_cast<char>(b));
  }

  void OnDataComplete() override {
    body_done_ = true;
    MaybeForwardResponse();
    MaybeFinish();
  }

 private:
  void MaybeForwardResponse() {
    if (response_sent_ || !body_done_ || !head_ || !downstream_)
      return;
    response_sent_ = true;
    PipeBodyToClient(downstream_, std::move(head_), body_,
                     std::move(cached_metadata_));
  }

  void MaybeFinish() {
    if (!body_done_ || !complete_received_ || finished_)
      return;
    finished_ = true;
    if (!response_sent_)
      MaybeForwardResponse();
    MaybePersist();
    if (downstream_)
      downstream_->OnComplete(*complete_status_);
  }

  void MaybePersist() {
    if (skip_persist_)
      return;
    if (!complete_status_ || complete_status_->error_code != net::OK)
      return;
    if (!StatusCacheable(status_, page_url_, &rules_))
      return;
    std::string persist_body = DecodePersistBody(body_, content_encoding_);
    double max_entry = LimitsFor(page_url_, &rules_).max_entry;
    if (max_entry > 0 &&
        static_cast<double>(persist_body.size()) > max_entry)
      return;
    if (!persist_runner_)
      return;
    int64_t encoded_len = complete_status_->encoded_body_length;
    if (encoded_len <= 0 ||
        encoded_len >= static_cast<int64_t>(persist_body.size())) {
      encoded_len = EncodedSizeForHit(persist_body, -1);
      if (encoded_len >= static_cast<int64_t>(persist_body.size()))
        encoded_len = 0;
    }
    double created =
        (base::Time::Now() - base::Time::UnixEpoch()).InSecondsF();
    std::string hex = FileHash(url_);
    auto merge = BindContextCacheMapMerge(bc_);
    persist_runner_->PostTaskAndReplyWithResult(
        FROM_HERE,
        base::BindOnce(&WritePersistFiles, dir_, url_, std::move(hex), status_,
                       headers_.Clone(), std::move(persist_body), created,
                       encoded_len),
        base::BindOnce(
            [](base::OnceCallback<void(std::string)> merge,
               base::OnceClosure notify_store, PersistWriteResult result) {
              if (!result.ok)
                return;
              if (notify_store)
                std::move(notify_store).Run();
              if (!merge.is_null())
                std::move(merge).Run(std::move(result.map_json));
            },
            std::move(merge),
            CallbackIfContextCacheAlive(
                bc_, base::BindOnce(
                         [](BrowserContext* bc, std::string request_id,
                            std::string page_url) {
                           DispatchCacheDecision(bc, request_id, page_url,
                                                 "store");
                         },
                         bc_.get(), devtools_request_id_, page_url_))));
  }

  raw_ptr<BrowserContext> bc_;
  std::string dir_;
  std::string url_;
  std::string page_url_;
  std::string devtools_request_id_;
  base::DictValue rules_;
  scoped_refptr<base::SequencedTaskRunner> persist_runner_;
  mojo::Remote<network::mojom::URLLoaderClient> downstream_;
  network::mojom::URLResponseHeadPtr head_;
  std::optional<mojo_base::BigBuffer> cached_metadata_;
  std::unique_ptr<mojo::DataPipeDrainer> drainer_;
  std::string body_;
  std::string content_encoding_;
  base::DictValue headers_;
  int status_ = 0;
  bool body_done_ = false;
  bool complete_received_ = false;
  bool response_sent_ = false;
  bool finished_ = false;
  bool skip_persist_ = false;
  std::optional<network::URLLoaderCompletionStatus> complete_status_;
};

class ContextMatchingURLLoaderFactory
    : public network::mojom::URLLoaderFactory {
 public:
  static void Create(
      BrowserContext* bc,
      mojo::PendingReceiver<network::mojom::URLLoaderFactory> receiver,
      mojo::PendingRemote<network::mojom::URLLoaderFactory> target) {
    new ContextMatchingURLLoaderFactory(bc, std::move(receiver),
                                        std::move(target));
  }

  void CreateLoaderAndStart(
      mojo::PendingReceiver<network::mojom::URLLoader> loader,
      int32_t request_id,
      uint32_t options,
      const network::ResourceRequest& request,
      mojo::PendingRemote<network::mojom::URLLoaderClient> client,
      const net::MutableNetworkTrafficAnnotationTag& traffic_annotation)
      override {
    const std::string url = request.url.spec();
    std::string doc_url, doc_html;
    if (bc_ && GetContextDocument(bc_, &doc_url, &doc_html) &&
        !doc_html.empty() && DocumentUrlMatch(url, doc_url)) {
      DispatchCacheDecision(bc_, DevToolsRequestId(request), url, "html");
      BindIdleLoader(std::move(loader));
      FinishServeHit(url,
                     "HTTP/1.1 200 OK\nContent-Type: text/html; charset=utf-8\n\n",
                     std::move(client), /*stored_encoded=*/-1, doc_html);
      return;
    }
    std::string dir, map_json, rules_json;
    if (!bc_ || !GetContextCache(bc_, &dir, &map_json, &rules_json)) {
      Forward(std::move(loader), request_id, options, request, std::move(client),
              traffic_annotation);
      return;
    }
    std::optional<base::DictValue> rules_v =
        rules_json.empty()
            ? std::nullopt
            : base::JSONReader::ReadDict(rules_json, /*options=*/0);
    std::optional<base::DictValue> map_v =
        map_json.empty()
            ? std::nullopt
            : base::JSONReader::ReadDict(map_json, /*options=*/0);
    const base::DictValue* rules = rules_v ? &*rules_v : nullptr;
    const base::DictValue* index = map_v ? &*map_v : nullptr;
    const std::string cache_key =
        CacheKey(request.method, url, RequestBodyBytes(request));
    const std::string action = MatchAction(url, cache_key, rules, index);
    DispatchMatch(bc_, action, url);
    DispatchCacheDecision(bc_, DevToolsRequestId(request), url, action);
    if (action == "hit") {
      const base::DictValue* entry = FindHitEntry(index, cache_key);
      BindIdleLoader(std::move(loader));
      ServeHit(dir, url, entry, std::move(client));
      return;
    }
    if (action == "block") {
      BindIdleLoader(std::move(loader));
      FailRequest(std::move(client), net::ERR_BLOCKED_BY_CLIENT);
      return;
    }
    if (ShouldPersist(request.method, url, dir, action, rules)) {
      ForwardPersist(std::move(loader), request_id, options, request,
                     std::move(client), traffic_annotation, dir,
                     rules_v ? std::move(*rules_v) : base::DictValue(),
                     cache_key);
      return;
    }
    Forward(std::move(loader), request_id, options, request, std::move(client),
            traffic_annotation);
  }

  void Clone(mojo::PendingReceiver<network::mojom::URLLoaderFactory> receiver)
      override {
    receivers_.Add(this, std::move(receiver));
  }

 private:
  ContextMatchingURLLoaderFactory(
      BrowserContext* bc,
      mojo::PendingReceiver<network::mojom::URLLoaderFactory> receiver,
      mojo::PendingRemote<network::mojom::URLLoaderFactory> target)
      : bc_(bc),
        target_(std::move(target)),
        persist_runner_(ContextCachePersistRunner()) {
    receivers_.Add(this, std::move(receiver));
    receivers_.set_disconnect_handler(base::BindRepeating(
        &ContextMatchingURLLoaderFactory::OnDisconnect, base::Unretained(this)));
    ScheduleContextCacheDiskLoad(bc_);
  }

  ~ContextMatchingURLLoaderFactory() override = default;

  void OnDisconnect() {
    if (receivers_.empty())
      delete this;
  }

  void Forward(
      mojo::PendingReceiver<network::mojom::URLLoader> loader,
      int32_t request_id,
      uint32_t options,
      const network::ResourceRequest& request,
      mojo::PendingRemote<network::mojom::URLLoaderClient> client,
      const net::MutableNetworkTrafficAnnotationTag& traffic_annotation) {
    if (!target_) {
      BindIdleLoader(std::move(loader));
      FailRequest(std::move(client), net::ERR_FAILED);
      return;
    }
    target_->CreateLoaderAndStart(std::move(loader), request_id, options,
                                  request, std::move(client),
                                  traffic_annotation);
  }

  void ForwardPersist(
      mojo::PendingReceiver<network::mojom::URLLoader> loader,
      int32_t request_id,
      uint32_t options,
      const network::ResourceRequest& request,
      mojo::PendingRemote<network::mojom::URLLoaderClient> client,
      const net::MutableNetworkTrafficAnnotationTag& traffic_annotation,
      const std::string& dir,
      base::DictValue rules,
      const std::string& cache_key) {
    if (!target_) {
      BindIdleLoader(std::move(loader));
      FailRequest(std::move(client), net::ERR_FAILED);
      return;
    }
    mojo::PendingRemote<network::mojom::URLLoaderClient> persist_remote;
    mojo::PendingReceiver<network::mojom::URLLoaderClient> persist_receiver =
        persist_remote.InitWithNewPipeAndPassReceiver();
    mojo::MakeSelfOwnedReceiver(
        std::make_unique<PersistClient>(
            bc_, dir, cache_key, request.url.spec(), DevToolsRequestId(request),
            std::move(rules), persist_runner_, std::move(client)),
        std::move(persist_receiver));
    target_->CreateLoaderAndStart(std::move(loader), request_id, options,
                                  request, std::move(persist_remote),
                                  traffic_annotation);
  }

  raw_ptr<BrowserContext> bc_;
  mojo::Remote<network::mojom::URLLoaderFactory> target_;
  mojo::ReceiverSet<network::mojom::URLLoaderFactory> receivers_;
  scoped_refptr<base::SequencedTaskRunner> persist_runner_;
};

}  // namespace

std::string ExplainContextCache(BrowserContext* browser_context,
                                const std::string& method,
                                const std::string& url,
                                const std::string& body_sha256) {
  if (!browser_context)
    return "pass";
  std::string doc_url, doc_html;
  if (GetContextDocument(browser_context, &doc_url, &doc_html) &&
      !doc_html.empty() && DocumentUrlMatch(url, doc_url)) {
    return "html";
  }
  std::string dir, map_json, rules_json;
  if (!GetContextCache(browser_context, &dir, &map_json, &rules_json))
    return "pass";
  std::optional<base::DictValue> rules_v =
      rules_json.empty()
          ? std::nullopt
          : base::JSONReader::ReadDict(rules_json, /*options=*/0);
  std::optional<base::DictValue> map_v =
      map_json.empty()
          ? std::nullopt
          : base::JSONReader::ReadDict(map_json, /*options=*/0);
  const base::DictValue* rules = rules_v ? &*rules_v : nullptr;
  const base::DictValue* index = map_v ? &*map_v : nullptr;
  std::string m = base::ToUpperASCII(method);
  std::string cache_key = url;
  if (!m.empty() && m != "GET" && m != "HEAD") {
    cache_key = m + " " + url;
    if (!body_sha256.empty()) {
      cache_key.push_back(' ');
      cache_key.append(base::ToLowerASCII(body_sha256));
    }
  }
  return MatchAction(url, cache_key, rules, index);
}

bool MaybeInstallContextRequestInterceptor(
    DevToolsAgentHostImpl* agent_host,
    StoragePartition* storage_partition,
    network::mojom::URLLoaderFactoryOverride* intercepting_factory) {
  if (!agent_host || !storage_partition || !intercepting_factory)
    return false;
  BrowserContext* bc = agent_host->GetBrowserContext();
  if (!bc)
    return false;
  MaybeLoadContextCacheFile(bc);
  std::string dir, map, rules, doc_url, doc_html;
  if (!GetContextCache(bc, &dir, &map, &rules) &&
      !GetContextDocument(bc, &doc_url, &doc_html))
    return false;

  if (!intercepting_factory->overriding_factory) {
    intercepting_factory->overridden_factory_receiver =
        intercepting_factory->overriding_factory.InitWithNewPipeAndPassReceiver();
  }
  mojo::PendingRemote<network::mojom::URLLoaderFactory> target_remote;
  auto overridden_factory_receiver =
      target_remote.InitWithNewPipeAndPassReceiver();
  ContextMatchingURLLoaderFactory::Create(
      bc, std::move(intercepting_factory->overridden_factory_receiver),
      std::move(target_remote));
  intercepting_factory->overridden_factory_receiver =
      std::move(overridden_factory_receiver);
  return true;
}

}  // namespace content
