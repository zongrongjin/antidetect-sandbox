# Chromium 151.0.7907.0 · Firefox 152.0.5

补丁在这个仓库里。Release 只放两个 Windows 安装包和 `SHA256SUMS`，不放补丁文件。

Chromium 基线 `fdadfe85a4cf993308b77a9324bd31b79df69ba3`。Firefox 用官方 `firefox-152.0.5.source.tar.xz`。这版包含指纹、Context、WebRTC、缓存规则，以及两条代理：`Context.setContextOverrides.proxy` 和 `Target.createBrowserContext` 的 `proxyServer`。地址只用 `http://host:port`，账号不要写进 URL。

产物是 Windows 组件构建，`chrome.exe` 在 `out/Default`，要和旁边的 DLL 放一起。安装包不进 git。

## 目录

```
chromium/patches/fp_full.diff       打在 Chromium 源码根
chromium/patches/fp_webrtc.diff     打在 third_party/webrtc
chromium/patches/fp_devtools.diff   打在 third_party/devtools-frontend/src
chromium/scripts/apply.sh
chromium/args.gn
firefox/patches/fp_all.diff         打在 firefox-152.0.5
firefox/scripts/fp_apply.sh
firefox/mozconfig
```

`src-new/` 和 `firefox/patches/bidi-module/` 是从 diff 抽出的新增文件，方便看。脚本不拷它们。

只打上面四份 diff。不要叠开源仓库的 `fp_full.diff`，也不要跑那边的 `patch_context_domain.py`、`patch_context_module.py`、`patch_android_surface.py`、`patch_input_trusted.py`、`patch_offscreen_webgl.py`。那些改动已经在完整 diff 里。这里没有 `fp_p0_capabilities.diff` 这类阶段审计 diff，构建时也不打。

## 从源码套用

Chromium：检出 `fdadfe85`，`gclient sync` 之后执行 `bash chromium/scripts/apply.sh /path/to/chromium/src`。把 `chromium/args.gn` 写到 `out/Default/args.gn`，再 `gn gen out/Default` 和 `autoninja -C out/Default chrome mini_installer`。

Firefox：解压官方源码包后执行 `bash firefox/scripts/fp_apply.sh /path/to/firefox-152.0.5`，把 `firefox/mozconfig` 复制成源码根的 `mozconfig`，然后 `./mach build` 和 `./mach package`。安装包在 `obj-release/dist/firefox-152.0.5.en-US.win64.installer.exe`。

## 缓存

`include` 为空时不进缓存，也不命中旧条目。要全站缓存，写一条 `*`。

## 回归

2026-11-17，96 线程编完，`ninja` 退出码 0。

- reese：通过。直连出口是编译机自己的地址，`set.proxy` 后出口换成了代理地址。
- kasada：通过。
- 阿里滑块：通过。
- Context 冒烟、Android surface、缓存命中：通过。`proxyServer` 必须是不带账号的 `http://host:port`。把账号写进 URL 会得到 `ERR_NO_SUPPORTED_PROXIES`。
- `verify.py` 只缺 WebGL2 的 `EXT_texture_norm16`。headless / SwiftShader 本身没有这个扩展，少这一项是预期结果。
