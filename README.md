# Chromium 151.0.7907.0 Windows 组件构建

基线 `fdadfe85a4cf993308b77a9324bd31b79df69ba3`。这版包含第一次 release 的指纹、Context、WebRTC，第二次 release 的缓存规则，以及两条代理都生效的改法：`Context.setContextOverrides.proxy` 和 `Target.createBrowserContext` 的 `proxyServer`（地址只用 `http://host:port`，账号不要写进 URL）。

缓存规则的 `include` 为空时不进缓存，也不命中旧条目。要全站缓存，写一条 `*`。

产物是 Windows 组件构建，`chrome.exe` 在 `out/Default`。发布包见本仓库的 Release，不进 git。没有替换 Linux 上正在给服务用的浏览器。

## 补丁

三个补丁都相对上面的基线，用 `git apply`：

- `chromium.patch`：打在 Chromium 源码根目录。含新增的 `context_handler`、`context_proxy_support`、`context_request_interceptor` 和 `Context.pdl`。
- `devtools-frontend.patch`：打在 `third_party/devtools-frontend/src`。
- `webrtc.patch`：打在 `third_party/webrtc`。

## 这台机器上的回归

2026-11-17，96 线程编完，`ninja` 退出码 0。

- reese：通过。直连出口是编译机自己的地址，`set.proxy` 后出口换成了代理地址。
- kasada：通过。
- 阿里滑块：通过。
- `website` 里的 Context 冒烟、Android surface、缓存命中：通过。`proxyServer` 必须是不带账号的 `http://host:port`，账号由代理认证单独给。把账号写进 URL 会得到 `ERR_NO_SUPPORTED_PROXIES`。
- `verify.py` 只缺 WebGL2 的 `EXT_texture_norm16`。headless / SwiftShader 本身没有这个扩展，交集之后少这一项是预期结果。
