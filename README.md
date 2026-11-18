# Chromium 151.0.7907.0 Windows 组件构建

基线 `fdadfe85a4cf993308b77a9324bd31b79df69ba3`。这版包含第一次 release 的指纹、Context、WebRTC，第二次 release 的缓存规则，以及两条代理都生效的改法：`Context.setContextOverrides.proxy` 和 `Target.createBrowserContext` 的 `proxyServer`（地址只用 `http://host:port`，账号不要写进 URL）。

缓存规则的 `include` 为空时不进缓存，也不命中旧条目。要全站缓存，写一条 `*`。

产物是 Windows 组件构建，`chrome.exe` 在 `out/Default`。发布包见本仓库的 Release，不进 git。没有替换 Linux 上正在给服务用的浏览器。

## 补丁

Chromium 三个补丁相对基线 `fdadfe85`，用 `git apply`：

- `chromium.patch`：打在 Chromium 源码根目录。含新增的 `context_handler`、`context_proxy_support`、`context_request_interceptor` 和 `Context.pdl`。
- `devtools-frontend.patch`：打在 `third_party/devtools-frontend/src`。
- `webrtc.patch`：打在 `third_party/webrtc`。

`firefox.patch` 相对官方 Firefox 152.0.5 源码包，在解压后的 `firefox-152.0.5` 目录里 `git apply`。里面是第一版指纹、Context、WebRTC，加上 Linux 上已经改好的缓存，以及 Windows 缓存路径按 `\` 拼接。补丁在那棵官方基线上做过 `git apply --reverse --check`。

别人从官方源码打出同一版浏览器：

Chromium：检出 `fdadfe85`，`gclient sync` 之后，在三个目录分别 `git apply` 上面三份补丁。把 `chromium.args.gn` 写到 `out/Default/args.gn`，再 `gn gen out/Default` 和 `autoninja -C out/Default chrome mini_installer`。不要再叠开源仓库里拆开的 `fp_full.diff`。

Firefox：解压官方 `firefox-152.0.5.source.tar.xz`，进入 `firefox-152.0.5`，执行 `git apply firefox.patch`，把 `firefox.mozconfig` 复制成 `mozconfig`，然后 `./mach build` 和 `./mach package`。安装包在 `obj-release/dist/firefox-152.0.5.en-US.win64.installer.exe`。

## 这台机器上的回归

2026-11-17，96 线程编完，`ninja` 退出码 0。

- reese：通过。直连出口是编译机自己的地址，`set.proxy` 后出口换成了代理地址。
- kasada：通过。
- 阿里滑块：通过。
- `website` 里的 Context 冒烟、Android surface、缓存命中：通过。`proxyServer` 必须是不带账号的 `http://host:port`，账号由代理认证单独给。把账号写进 URL 会得到 `ERR_NO_SUPPORTED_PROXIES`。
- `verify.py` 只缺 WebGL2 的 `EXT_texture_norm16`。headless / SwiftShader 本身没有这个扩展，交集之后少这一项是预期结果。
