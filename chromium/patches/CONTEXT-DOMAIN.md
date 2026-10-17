# Context 域（取代 Fingerprint，并入 proxy）

套完 `fp_full.diff` 后跑：

```bash
python3 scripts/patch_context_domain.py /path/to/chromium/src
```

脚本会：

1. 用 `src-new/` 的 `Context.pdl` + `context_handler.{cc,h}` 替换 Fingerprint 协议文件
2. BUILD.gn / browser_protocol.pdl / DevToolsSession / RenderFrameDevToolsAgentHost 改挂 `ContextHandler`
3. 在 `WebContentsImpl` 旁增加 `SetBrowserContextProxy` / `GetBrowserContextProxy`
4. 插入 URLLoaderThrottle：对该 BrowserContext 的代理请求预发 `Proxy-Authorization: Basic`（无 407）

## 命令

```
Context.setContextOverrides
  fingerprint?: string   # 原 Fingerprint blob，空串清画像
  proxy?: { endpoint, username, password }  # endpoint 空串清代理
```

省略的字段保持上次值。

## 代理路由

`Target.createBrowserContext` **不再**传 `proxyServer`。隔离 context 直连创建后，由本命令的 `proxy.endpoint` 写到该 BrowserContext 的 NetworkContext（`net::ProxyConfig` + `StoragePartitionImpl`）。

若 `SetConfiguredProxy` / `NetworkContext::SetProxy` 在 151 树上签名不同，编译报错点就在脚本插入的 `// CONTEXT_PROXY_APPLY` 块，按本树 mojom 改那一处即可。账密不走 Fetch。

## 验证

Python `new_context(proxy=..., fingerprint=...)` 只打这一条 CDP。`scripts/verify.py` 已改 `Context.setContextOverrides`。
