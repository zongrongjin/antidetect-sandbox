# Chromium 引擎 — per-BrowserContext 指纹定制（151.0.7907.0）

本目录是 [antidetect-sandbox](https://github.com/zongrongjin/antidetect-sandbox)
里的 **Chromium** 引擎。Firefox 引擎在 [`../firefox/`](../firefox/README.md)。

对 **Chromium 151.0.7907.0** 的一套指纹定制补丁：给 `RendererPreferences` 增加一个
`fingerprint`（JSON blob）字段，并在浏览器各指纹读取点消费它，从而对**每个
BrowserContext** 下发**任意**一份指纹画像。新增一个原生 CDP 域
`Context.setContextOverrides`——**一条命令**即可下发指纹与 per-context 代理。
该 context 的主页面 / iframe / 跨源 OOPIF / dedicated·shared·service worker 全部继承同一份指纹。

> ⚠️ 仅用于**授权的安全研究 / 反检测研究 / 隐私测试**。不含任何整棵 Chromium 源码，
> 只有补丁与新增文件——按下面步骤拉基础 Chromium 后套用即可。

## 基础版本（必须一致）

| 项 | 值 |
|---|---|
| Chromium 版本 | **151.0.7907.0** |
| 基础 commit | **`fdadfe85a4cf993308b77a9324bd31b79df69ba3`** |
| 平台 | Windows x64（已编译/运行验证）与 Linux x64 |

补丁是对该 commit 的工作区 diff，**必须 checkout 到这个确切 commit** 才能干净套用
（注意：它不是发布 tag `151.0.7907.0`，那是另一个 commit）。

产品号始终是 **151.0.7907.0**。不同构建靠 **GitHub Release tag** 区分，不要用
`chrome://version` 的 Revision 判断（本构建 LASTCHANGE 常为 `00000000-00000000`）。

## 预编译产物

Latest：https://github.com/zongrongjin/antidetect-sandbox/releases/latest

当前 Latest：`chrome-v151.0.7907.0-20261014`（只放 Windows 预编译）。

| 资源 | 用途 |
|---|---|
| `chromium_zzbrowser_151.0.7907.0_win64_mini_installer.exe` | Windows x64 官方安装包 |
| `SHA256SUMS` | 校验 |

## 仓库结构

```
patches/fp_full.diff      # 指纹补丁。先套这份，再跑 patch_context_domain.py
patches/cache_rules_install.diff      # 改名之后：把缓存源文件编进 BUILD.gn，并挂上拦截器
patches/cache_rules_protocol.diff     # Context 域补上 getCacheState / explainCache / cacheDecision
patches/cache_rules_devtools.diff     # devtools-frontend 的网络面板缓存规则表单
patches/fp_p0_capabilities.diff       # P0 阶段差异，仅作审计
patches/fp_consistency_followup.diff  # 一致性阶段差异，仅作审计
patches/fp_webrtc.diff    # third_party/webrtc 补丁：4 个改动文件（DEPS 独立仓库，需单独套）
src-new/                  # 新增 CDP 文件（也已含于 diff，单独放便于阅读）
scripts/apply.sh          # 套 Chromium 补丁
scripts/build.sh          # gn gen + 编译
scripts/verify.py         # 独立验证（raw CDP，仅依赖 websocket-client）
scripts/kasada_demo.py    # Arc'teryx Kasada：url+html 假页，/tl 含 reload 为过
windows/                  # Windows 构建
docs/SPECIAL-CDP.md        # 特殊 CDP + fingerprint 字段契约
schemas/fingerprint.schema.json
```

## 从零复现

```bash
# 0) depot_tools（GFW 内需自备代理，设 https_proxy 后再执行）
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git ~/depot_tools
export PATH=$HOME/depot_tools:$PATH

# 1) 拉基础源码到确切 commit（浅拉，只取该快照）
mkdir -p ~/chromium && cd ~/chromium
cat > .gclient <<'EOF'
solutions = [{"name":"src","url":"https://chromium.googlesource.com/chromium/src.git",
              "managed":False,"custom_deps":{},"custom_vars":{}}]
target_os = ["linux"]
EOF
git init -q src && cd src
git remote add origin https://chromium.googlesource.com/chromium/src.git
git fetch --depth 1 origin fdadfe85a4cf993308b77a9324bd31b79df69ba3
git checkout -f FETCH_HEAD
cd .. && gclient sync --no-history --shallow --nohooks -D && gclient runhooks
cd src && ../../src/build/install-build-deps.sh --no-prompt   # 补 pkg-config 等系统依赖

# 2) 套补丁
bash /path/to/this-repo/chromium/scripts/apply.sh ~/chromium/src

# 3) 编译（32 核约 1.5h；产物 out/Default/chrome）
bash /path/to/this-repo/chromium/scripts/build.sh ~/chromium/src

# 4) 验证
python3 /path/to/this-repo/chromium/scripts/verify.py ~/chromium/src/out/Default/chrome
```

> **专有编解码器（务必开）**：`scripts/build.sh` 的 args.gn 已含
> `proprietary_codecs = true` + `ffmpeg_branding = "Chrome"`。开源 Chromium 默认**不带**
> H.264/H.265/AAC，而我们的 UA 自称 `Google Chrome` —— 不开这两项，`canPlayType('...avc1...')`
> 会返回空串，被检测为「开源编译/反检测浏览器」（Chromium-not-Chrome tell）。开启后与正版
> Chrome 逐项一致。改这两项只需 `gn gen` + 增量重编 ffmpeg/media + 重链，约 0.5–1h，不必全量。

> **Widevine / EME（务必开）**：`scripts/build.sh` 的 args.gn 已含 `enable_widevine = true`。
> 默认 `enable_widevine=false` 时 Widevine 被编译掉，`chrome://components` 无条目、
> `navigator.requestMediaKeySystemAccess('com.widevine.alpha')` 抛 `NotSupportedError`（只剩
> ClearKey）—— UA 自称 Chrome 却不支持 Widevine 是仅次于 H.264 的 tell。开启后注册 Widevine
> 组件。**CDM 本体不含在本仓库**（专有二进制），两种拿法：① 让组件更新器联网从 Google 拉取
> （首次需通 `clients2.google.com`）；② 离线：从真 Chrome/Edge 安装目录把整个 `WidevineCdm\`
> 拷到 profile 的 `<UserDataDir>/WidevineCdm/<版本>/`（含 `manifest.json` +
> `_platform_specific/<plat>/`），启动时组件更新器会离线注册该版本。实测拷 Edge 的
> `WidevineCdm 4.10.2934.0` 到 profile 后，`requestMediaKeySystemAccess` + `createMediaKeys`
> 均通过（L3 软件级；硬件级 L1 依赖真实平台，云 VM 无）。此改动约 1–2min 增量重编。

GFW 内拉源码/工具链需要能通 Google 的代理（`chromium.googlesource.com` /
`commondatastorage.googleapis.com`）。本仓库不含任何代理配置。

## Kasada demo

Arc'teryx：内核用 `url`+`html` 做成真实导航假页，再让页面自己拉 `/p.js`。
**不要** `Fetch.enable *`，**不要** `Runtime.enable`。PASS 当且仅当 `/tl` body 含 `reload`（不打印 ct/h）。

```bash
pip install websocket-client
export KASADA_PROXY='http://user:pass@host:port'   # 美/加住宅，短期内 IP 稳定
python3 chromium/scripts/kasada_demo.py /path/to/chrome
# 期望: kasada pjs=200 tl_status=200 body_len=15 reload=True
#       KASADA PASS
```

默认 headed。代理只从环境变量读，脚本只打印 host:port。

## 用法

### 跑预编译包

Windows（用户级，不覆盖系统 Chromium）：

```bat
chromium_zzbrowser_151.0.7907.0_win64_mini_installer.exe --do-not-launch-chrome
"%LOCALAPPDATA%\Chromium\Application\chrome.exe" --remote-debugging-port=9222
```

系统级把 installer 加上 `--system-level`，二进制在
`C:\Program Files\Chromium\Application\chrome.exe`。

Linux android-surface：

```bash
tar -xJf chromium-linux-x64-v151.0.7907.0-android-surface.tar.xz
./chrome --no-sandbox --remote-debugging-port=9222
```

无硬件 GPU / RDP 时加 `--enable-unsafe-webgpu --ignore-gpu-blocklist`。
不要叠 `--use-webgpu-adapter=swiftshader --enable-features=Vulkan --use-vulkan=swiftshader`。

### 一条 CDP 命令下发指纹

对目标 context 的会话发送：

```
Context.setContextOverrides  { "fingerprint": "<下面这份 JSON 的字符串>",
                               "proxy": {"endpoint": "host:port", "username": "", "password": ""} }
```

该 context 的所有页面（含之后新建 target）与三种 worker 自动继承。

`fingerprint` 是一个 JSON **字符串**，不是 typed CDP object。特殊 CDP（`Context.setContextOverrides` /
`headersList` / 不要 Fetch `*`）以及完整字段契约见
[`docs/SPECIAL-CDP.md`](docs/SPECIAL-CDP.md)；机器校验用
[`schemas/fingerprint.schema.json`](schemas/fingerprint.schema.json)。

`viewportWidth` / `viewportHeight` 改实际 layout 还需另发
`Emulation.setDeviceMetricsOverride`。`formFactors` 不传时：`mobile` 或 Android →
`["Mobile"]`，否则 `["Desktop"]`。`plugins` / `mimeTypes` / `pdfViewerEnabled` /
`keyboard` / `connection` 由 android-surface 覆盖：Android/iOS 缺省空插件、
`pdfViewerEnabled=true`、`navigator.keyboard === null`。

调用时把下面对象 `json.dumps` 成字符串，放进 `params.fingerprint`。字段都可选；
没有真机值的键删掉即回退原生。`*Replay` 没有采集数据就不要传。
`viewportWidth` / `viewportHeight` 另发 `Emulation.setDeviceMetricsOverride` 才会改实际 layout。

Chrome 151 GREASE：`Not=A?Brand` / `99`，顺序 grease → Google Chrome → Chromium。

### Windows 全参（Chrome / Win11 / NVIDIA）

桌面不要传 `plugins: []`，不传或非空都走原生 5 PDF 门面。`architecture`/`bitness` 用 `x86`/`64`。

```json
{
  "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
  "platform": "Win32",
  "uaPlatform": "Windows",
  "uaBrands": [
    {"b": "Not=A?Brand", "v": "99"},
    {"b": "Google Chrome", "v": "151"},
    {"b": "Chromium", "v": "151"}
  ],
  "uaFullBrands": [
    {"b": "Not=A?Brand", "v": "99.0.0.0"},
    {"b": "Google Chrome", "v": "151.0.7907.0"},
    {"b": "Chromium", "v": "151.0.7907.0"}
  ],
  "uaFullVersion": "151.0.7907.0",
  "platformVersion": "15.0.0",
  "architecture": "x86",
  "model": "",
  "mobile": false,
  "bitness": "64",
  "wow64": false,
  "formFactors": ["Desktop"],
  "acceptLanguages": "en-US,en;q=0.9",
  "locale": "en-US",
  "timezone": "America/New_York",
  "hardwareConcurrency": 16,
  "deviceMemory": 8,
  "referrer": "",
  "screenWidth": 1920,
  "screenHeight": 1080,
  "availWidth": 1920,
  "availHeight": 1032,
  "availLeft": 0,
  "availTop": 0,
  "colorDepth": 24,
  "dpr": 1,
  "maxTouchPoints": 0,
  "outerWidth": 1920,
  "outerHeight": 1032,
  "viewportWidth": 1920,
  "viewportHeight": 946,
  "pdfViewerEnabled": true,
  "webRTC": 1,
  "webRTCPublicIP": "203.0.113.7",
  "webglVendor": "Google Inc. (NVIDIA)",
  "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "webglExtensions": [
    "ANGLE_instanced_arrays",
    "EXT_blend_minmax",
    "EXT_color_buffer_half_float",
    "EXT_float_blend",
    "EXT_texture_filter_anisotropic",
    "OES_element_index_uint",
    "OES_standard_derivatives",
    "OES_vertex_array_object",
    "WEBGL_debug_renderer_info",
    "WEBGL_lose_context"
  ],
  "webgl2Extensions": [
    "EXT_color_buffer_float",
    "EXT_color_buffer_half_float",
    "EXT_float_blend",
    "EXT_texture_filter_anisotropic",
    "OES_draw_buffers_indexed",
    "WEBGL_debug_renderer_info",
    "WEBGL_lose_context",
    "WEBGL_multi_draw"
  ],
  "webglParameters": {
    "3379": {"type": "int", "value": 16384},
    "33901": {"type": "float32", "value": [1, 1024]},
    "34024": {"type": "int", "value": 16384},
    "34930": {"type": "int", "value": 32},
    "35661": {"type": "int", "value": 32},
    "36347": {"type": "int", "value": 4096},
    "36349": {"type": "int", "value": 1024}
  },
  "webgl2Parameters": {
    "3379": {"type": "int", "value": 16384},
    "34024": {"type": "int", "value": 16384},
    "34921": {"type": "int", "value": 16},
    "34930": {"type": "int", "value": 32},
    "35660": {"type": "int", "value": 16},
    "35661": {"type": "int", "value": 32},
    "36183": {"type": "int", "value": 4},
    "36347": {"type": "int", "value": 4096},
    "36349": {"type": "int", "value": 1024}
  },
  "webglShaderPrecision": {
    "35633:36338": [127, 127, 23],
    "35632:36338": [127, 127, 23]
  },
  "webgl2ShaderPrecision": {
    "35633:36338": [127, 127, 23],
    "35632:36338": [127, 127, 23]
  },
  "webGPU": {
    "adapter": {
      "vendor": "nvidia",
      "architecture": "",
      "device": "",
      "description": "NVIDIA GeForce RTX 3060",
      "backend": "d3d12",
      "type": "discrete-gpu",
      "isFallbackAdapter": false,
      "subgroupMinSize": 32,
      "subgroupMaxSize": 32
    },
    "features": ["texture-compression-bc", "timestamp-query", "depth32float-stencil8"],
    "limits": {
      "maxTextureDimension2D": 16384,
      "maxBindGroups": 4,
      "minUniformBufferOffsetAlignment": 256
    },
    "preferredCanvasFormat": "bgra8unorm"
  },
  "fontFamilies": ["Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Georgia", "Segoe UI", "Tahoma", "Times New Roman", "Verdana"],
  "fontAliases": {
    "system-ui": "Segoe UI",
    "sans-serif": "Arial",
    "serif": "Times New Roman",
    "monospace": "Consolas"
  },
  "speechVoices": [
    {"name": "Microsoft David - English (United States)", "lang": "en-US", "voiceURI": "Microsoft David - English (United States)", "localService": true, "default": true},
    {"name": "Microsoft Zira - English (United States)", "lang": "en-US", "voiceURI": "Microsoft Zira - English (United States)", "localService": true, "default": false}
  ],
  "cssMedia": {
    "colorGamut": "srgb",
    "dynamicRange": "standard",
    "forcedColors": "none",
    "prefersContrast": "no-preference",
    "prefersReducedMotion": "no-preference"
  },
  "mediaCodecs": {
    "canPlayType": {
      "audio/mpeg": "probably",
      "audio/mp4; codecs=\"mp4a.40.2\"": "probably",
      "video/webm; codecs=\"vp8\"": "probably",
      "video/webm; codecs=\"vp9\"": "probably",
      "video/mp4; codecs=\"avc1.42E01E\"": "probably",
      "video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"": "probably"
    },
    "mediaSource": [
      "audio/mpeg",
      "audio/mp4; codecs=\"mp4a.40.2\"",
      "video/webm; codecs=\"vp8\"",
      "video/webm; codecs=\"vp9\"",
      "video/mp4; codecs=\"avc1.42E01E\""
    ],
    "decodingInfo": {
      "video/webm; codecs=\"vp8\"": {"supported": true, "smooth": true, "powerEfficient": false},
      "video/mp4; codecs=\"avc1.42E01E\"": {"supported": true, "smooth": true, "powerEfficient": true}
    }
  },
  "mediaDevices": [
    {"kind": "audioinput", "deviceId": "default", "groupId": "", "label": ""},
    {"kind": "videoinput", "deviceId": "default", "groupId": "", "label": ""},
    {"kind": "audiooutput", "deviceId": "default", "groupId": "", "label": ""}
  ],
  "readbackSeed": 77777,
  "canvasDataReplay": ["<base64 RGBA bytes>"],
  "canvasUrlReplay": ["<complete data:image/... URL>"],
  "canvasBlobReplay": ["<base64 encoded image bytes>"],
  "glReadReplay": ["<base64 RGBA bytes>"],
  "audioReplay": ["<base64 little-endian float32 samples>"],
  "analyserFloatReplay": ["<base64 float32 samples>"],
  "analyserByteReplay": ["<base64 bytes>"]
}
```

### Android 全参（Chrome / Pixel 3 / Adreno 630）

`architecture` / `bitness` 用空字符串（真机 UA-CH）。`plugins` / `mimeTypes` 必须是 `[]`。
`pdfViewerEnabled` 为 `true`。`keyboard: false` 让 `navigator.keyboard === null`。

```json
{
  "userAgent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
  "platform": "Linux armv8l",
  "uaPlatform": "Android",
  "uaBrands": [
    {"b": "Not=A?Brand", "v": "99"},
    {"b": "Google Chrome", "v": "151"},
    {"b": "Chromium", "v": "151"}
  ],
  "uaFullBrands": [
    {"b": "Not=A?Brand", "v": "99.0.0.0"},
    {"b": "Google Chrome", "v": "151.0.7907.0"},
    {"b": "Chromium", "v": "151.0.7907.0"}
  ],
  "uaFullVersion": "151.0.7907.0",
  "platformVersion": "10.0.0",
  "architecture": "",
  "model": "Pixel 3",
  "mobile": true,
  "bitness": "",
  "wow64": false,
  "formFactors": ["Mobile"],
  "acceptLanguages": "en-US,en;q=0.9",
  "locale": "en-US",
  "timezone": "America/Los_Angeles",
  "hardwareConcurrency": 8,
  "deviceMemory": 4,
  "referrer": "",
  "screenWidth": 393,
  "screenHeight": 786,
  "availWidth": 393,
  "availHeight": 786,
  "availLeft": 0,
  "availTop": 0,
  "colorDepth": 24,
  "dpr": 2.75,
  "maxTouchPoints": 5,
  "outerWidth": 393,
  "outerHeight": 786,
  "viewportWidth": 392,
  "viewportHeight": 632,
  "plugins": [],
  "mimeTypes": [],
  "pdfViewerEnabled": true,
  "keyboard": false,
  "connection": {
    "effectiveType": "4g",
    "downlink": 10,
    "rtt": 50,
    "saveData": false
  },
  "webRTC": 1,
  "webRTCPublicIP": "203.0.113.8",
  "webglVendor": "Google Inc. (Qualcomm)",
  "webglRenderer": "ANGLE (Qualcomm, Adreno (TM) 630, OpenGL ES 3.2)",
  "webglExtensions": [
    "ANGLE_instanced_arrays",
    "EXT_blend_minmax",
    "EXT_color_buffer_half_float",
    "EXT_float_blend",
    "EXT_texture_filter_anisotropic",
    "OES_element_index_uint",
    "OES_standard_derivatives",
    "OES_vertex_array_object",
    "WEBGL_debug_renderer_info",
    "WEBGL_lose_context"
  ],
  "webgl2Extensions": [
    "EXT_color_buffer_float",
    "EXT_color_buffer_half_float",
    "EXT_float_blend",
    "EXT_texture_filter_anisotropic",
    "OES_draw_buffers_indexed",
    "WEBGL_debug_renderer_info",
    "WEBGL_lose_context",
    "WEBGL_multi_draw"
  ],
  "webglParameters": {
    "3379": {"type": "int", "value": 4096},
    "33901": {"type": "float32", "value": [1, 1024]},
    "34024": {"type": "int", "value": 4096},
    "34930": {"type": "int", "value": 16},
    "35661": {"type": "int", "value": 16},
    "36347": {"type": "int", "value": 1024},
    "36349": {"type": "int", "value": 256}
  },
  "webgl2Parameters": {
    "3379": {"type": "int", "value": 4096},
    "34024": {"type": "int", "value": 4096},
    "34921": {"type": "int", "value": 16},
    "34930": {"type": "int", "value": 16},
    "35660": {"type": "int", "value": 16},
    "35661": {"type": "int", "value": 16},
    "36183": {"type": "int", "value": 4},
    "36347": {"type": "int", "value": 1024},
    "36349": {"type": "int", "value": 256}
  },
  "webglShaderPrecision": {
    "35633:36338": [127, 127, 23],
    "35632:36338": [127, 127, 23]
  },
  "webgl2ShaderPrecision": {
    "35633:36338": [127, 127, 23],
    "35632:36338": [127, 127, 23]
  },
  "webGPU": {
    "adapter": {
      "vendor": "qualcomm",
      "architecture": "",
      "device": "",
      "description": "Adreno (TM) 630",
      "backend": "vulkan",
      "type": "integrated-gpu",
      "isFallbackAdapter": false,
      "subgroupMinSize": 32,
      "subgroupMaxSize": 32
    },
    "features": ["texture-compression-astc", "texture-compression-etc2"],
    "limits": {
      "maxTextureDimension2D": 4096,
      "maxBindGroups": 4,
      "minUniformBufferOffsetAlignment": 256
    },
    "preferredCanvasFormat": "rgba8unorm"
  },
  "fontFamilies": ["Roboto", "Noto Sans", "Noto Sans CJK SC", "Droid Sans Mono"],
  "fontAliases": {
    "system-ui": "Roboto",
    "sans-serif": "Roboto",
    "serif": "Noto Serif",
    "monospace": "Droid Sans Mono"
  },
  "speechVoices": [
    {"name": "English United States", "lang": "en-US", "voiceURI": "English United States", "localService": true, "default": true}
  ],
  "cssMedia": {
    "colorGamut": "srgb",
    "dynamicRange": "standard",
    "forcedColors": "none",
    "prefersContrast": "no-preference",
    "prefersReducedMotion": "no-preference"
  },
  "mediaCodecs": {
    "canPlayType": {
      "audio/mpeg": "probably",
      "audio/mp4; codecs=\"mp4a.40.2\"": "probably",
      "video/webm; codecs=\"vp8\"": "probably",
      "video/webm; codecs=\"vp9\"": "probably",
      "video/mp4; codecs=\"avc1.42E01E\"": "probably",
      "video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"": "probably"
    },
    "mediaSource": [
      "audio/mpeg",
      "audio/mp4; codecs=\"mp4a.40.2\"",
      "video/webm; codecs=\"vp8\"",
      "video/webm; codecs=\"vp9\"",
      "video/mp4; codecs=\"avc1.42E01E\""
    ],
    "decodingInfo": {
      "video/webm; codecs=\"vp8\"": {"supported": true, "smooth": true, "powerEfficient": true},
      "video/mp4; codecs=\"avc1.42E01E\"": {"supported": true, "smooth": true, "powerEfficient": true}
    }
  },
  "mediaDevices": [
    {"kind": "audioinput", "deviceId": "default", "groupId": "", "label": ""},
    {"kind": "videoinput", "deviceId": "default", "groupId": "", "label": ""},
    {"kind": "audiooutput", "deviceId": "default", "groupId": "", "label": ""}
  ],
  "readbackSeed": 424242,
  "canvasDataReplay": ["<base64 RGBA bytes>"],
  "canvasUrlReplay": ["<complete data:image/... URL>"],
  "canvasBlobReplay": ["<base64 encoded image bytes>"],
  "glReadReplay": ["<base64 RGBA bytes>"],
  "audioReplay": ["<base64 little-endian float32 samples>"],
  "analyserFloatReplay": ["<base64 float32 samples>"],
  "analyserByteReplay": ["<base64 bytes>"]
}
```

`*Replay` 没有真机采集就删掉这些键，只留 `readbackSeed`。`fontAliases` 要机器上真有对应字体。
`mediaDevices` 只覆盖授权前 `enumerateDevices()`，不伪造权限或硬件。
`productCapabilities` 不是内核覆盖字段。

> **WebRTC**：`webRTCPublicIP` 只覆盖 srflx（公网反射地址）。host candidate 不动 ——
> Chromium 默认已用随机 mDNS（`xxxx.local`）把它挡住，实测同 context 内稳定、跨 context
> 与跨重启均不重复，真实内网 IP 从不出现在任何 JS 可读位置；改成裸私网 IP 反而偏离
> 真实 Chrome 的默认形态。`raddr` 保持 Chromium 抹成的 `0.0.0.0 rport 0`。
> 不传该字段时 WebRTC 行为与原版逐字节一致。

> **WebRTC 三种模式（实测）**
> | 值 | candidate | 适用 |
> |---|---|---|
> | 不传 / `1` | `host(mDNS)` + `srflx` | 最像真实家用机；配 `webRTCPublicIP` 即可骗过读 candidate 的脚本 |
> | `2` | **只有 `srflx`，host 全无** | 多网卡机器怕暴露网卡数；但形态偏离常见桌面 |
> | `0` | **零 candidate**，`iceGatheringState` 立即 complete | 站点自建 STUN/TURN 从网络层嗅探真实 IP 时的唯一解 |
>
> 模式 0 会连带禁掉 UDP/STUN/UDP-relay（见 `platform/p2p/port_allocator.cc`），
> WebRTC 退到 TCP，而 P2P TCP 走代理（`services/network/p2p/socket_tcp.cc`）；
> 代价是只配 STUN 的页面拿不到任何 candidate。

> **噪声 vs 固定回放**：`readbackSeed` 是在真机基础上加确定性微扰（够用、体积小）；
> `*Replay` 是直接回放真机采集的原值（能过"已知真机值白名单"，但需真机采集、体积大）。
> 同一读回点：**回放存在时优先回放，否则走噪声，再否则 native**。

## 覆盖的指纹维度

| 维度 | 键 | 覆盖面 |
|---|---|---|
| navigator.userAgent + 全部 UA 请求头 | `userAgent` | 主/iframe/OOPIF/三种 worker |
| navigator.platform | `platform` | 全上下文 |
| sec-ch-ua-platform / userAgentData.platform | `uaPlatform` | JS 平面 + 导航/子资源请求头 |
| sec-ch-ua / userAgentData.brands | `uaBrands` | JS 平面 + 请求头 |
| sec-ch-ua-full-version-list / fullVersionList | `uaFullBrands` | JS 平面 + 请求头 |
| sec-ch-ua-form-factors / userAgentData.formFactors | `formFactors` | JS 平面 + 请求头；缺省 Mobile/Desktop 见上 |
| navigator.language(s) + Accept-Language 头 | `acceptLanguages` | 全上下文 |
| Intl locale | `locale` | 全上下文 |
| Intl 时区 | `timezone` | 全上下文 |
| navigator.hardwareConcurrency | `hardwareConcurrency` | 全上下文 |
| screen 宽高 | `screenWidth`/`screenHeight` | 主/iframe |
| devicePixelRatio | `dpr` | 主/iframe；`>0` 生效，不传回退真机 DPR |
| navigator.maxTouchPoints | `maxTouchPoints` | 主/iframe；`>=0` 生效 |
| pointer / hover 媒体特性（派生） | 由 `maxTouchPoints` 派生 | `mtp>0`→`pointer:coarse`+`hover:none`（触屏），`mtp==0`→`pointer:fine`+`hover:hover`（桌面）；`any-pointer`/`any-hover` 同步单值自洽，不传则回退内核 settings |
| screen.orientation type/angle（派生） | 由 `screenWidth/Height`+`maxTouchPoints` 派生 | 横竖由屏宽高判定，桌面横屏=0°/竖屏=90°、移动横屏=90°/竖屏=0°；缺屏尺寸键回退真机 |
| screen 可用区域 | `availWidth`/`availHeight`/`availLeft`/`availTop` | 同上；不传按 `uaPlatform` 推导，**不可与整屏相同**（真实桌面有任务栏/菜单栏） |
| screen.colorDepth / pixelDepth | `colorDepth` | 同上 |
| navigator.deviceMemory | `deviceMemory` | 主/iframe/跨域 iframe/blob/isolated world + 三种 worker；**同时覆盖 `Device-Memory` 与 `Sec-CH-Device-Memory` 请求头**（导航 + 子资源两条独立代码路径） |
| WebRTC srflx 公网 IP | `webRTCPublicIP` | candidate 字符串 / `.address` / SDP 的 `a=candidate` 与 `c=` 行 / `getStats()` 四个出口 |
| WebRTC 路由策略 | `webRTC` | `0`/`1`/`2`，见下方说明；与 `webRTCPublicIP` **互斥**（模式 0 不产生 srflx） |
| WebGL UNMASKED vendor/renderer | `webglVendor`/`webglRenderer` | 主/iframe/OOPIF + 三种 worker |
| WebGL 扩展列表 | `webglExtensions` | 同上（webgl1 上下文） |
| WebGL2 扩展列表 | `webgl2Extensions` | 同上（webgl2 上下文，`getSupportedExtensions()` 按 `IsWebGL2()` 分键；缺键该版本干净回退原生枚举，不会拿 webgl1 数组顶 webgl2） |
| WebGL 能力 / shader precision | `webglParameters` / `webgl2Parameters` / `webglShaderPrecision` / `webgl2ShaderPrecision` | typed value schema；缺键原生回退 |
| 系统字体与别名 | `fontFamilies` / `fontAliases` | 字体查询 + 实际字体选择；Canvas/TextMetrics、DOM/Range 与 worker OffscreenCanvas 共用同一选择结果 |
| Speech voices | `speechVoices` | name/lang/voiceURI/localService/default |
| WebGPU | `webGPU` | adapter、features（与原生支持集取交集）、limits（只向保守方向收敛）、preferredCanvasFormat |
| 窗口与 viewport | `outerWidth`/`outerHeight`/`viewportWidth`/`viewportHeight` | outer 由内核读画像；实际 layout 另发 `Emulation.setDeviceMetricsOverride` |
| CSS 媒体特性 | `cssMedia` | color-gamut、dynamic-range/HDR、forced-colors、prefers-contrast、prefers-reduced-motion |
| 媒体能力 | `mediaCodecs` | canPlayType、MSE 与 decodingInfo exact-content-type 矩阵；DRM/keySystem 保持原生 |
| 媒体设备 | `mediaDevices` | enumerateDevices 的 per-context 预授权视图 |
| PDF / 插件 | `plugins` / `mimeTypes` / `pdfViewerEnabled` | 显式数组或 Android/iOS 缺省空插件 + `pdfViewerEnabled=true`；桌面不传走原生 5 PDF |
| keyboard / connection | `keyboard` / `connection` | Android 缺省隐藏 keyboard；connection 可删或覆盖 effectiveType/downlink/rtt |
| 读回**噪声** | `readbackSeed` | canvas getImageData/toDataURL、WebGL1/2 readPixels、toBlob、convertToBlob、OfflineAudioContext/AnalyserNode |
| 读回**固定回放** | `canvasDataReplay` / `canvasUrlReplay` / `canvasBlobReplay` / `glReadReplay` / `audioReplay` | getImageData / toDataURL / (toBlob·convertToBlob) / (WebGL1/2 readPixels) / OfflineAudioContext；按调用序回放真机值，优先于噪声 |

Windows 无硬件 GPU/RDP 节点要让 Dawn 自动选 D3D/WARP：使用
`--enable-unsafe-webgpu --ignore-gpu-blocklist`，不要再叠加
`--use-webgpu-adapter=swiftshader --enable-features=Vulkan --use-vulkan=swiftshader`。
后者能提供软件 WebGL，但会令本构建的 WebGPU adapter 不可用。

存储为 **per-BrowserContext**（`SupportsUserData`），经 `RendererPreferences` 的
`SyncRendererPrefs` 传播到该 context 每个 renderer（含 OOPIF 与新建 target），
worker 经既有 renderer_preferences / GlobalScopeCreationParams 通道继承。

`scripts/apply.sh` 只应用最终 `fp_full.diff`（相对基线 `fdadfe85` 的完整工作区，
含 android-surface / formFactors / 最外层 layout / JS 剥 q）；两个阶段差异文件和
`scripts/patch_*.py` 都不能叠加应用。最终补丁从 DS6797 编译树对原始 Chromium
导出，`git apply --reverse --check` 通过（86 个文件，3 个新增）。

## 附加：CDP 回调按真实顺序给请求头（headersList）

`Fetch.requestPaused` 与 `Network.requestWillBeSentExtraInfo` 原生把请求头放进
`Network.Headers`（JSON 对象，底层 `base::Value::Dict` 按 key **字母序**重排），真实
wire 头序丢失——而**请求头顺序本身是反检测指纹信号**。本补丁在这两个回调各新增一个
**有序数组字段 `headersList`**（`[{name,value},...]`，保留真实顺序与重复头；原 `headers`
对象保持不变，向后兼容）：

- `Fetch.requestPaused` → `params.request.headersList`（拦截时刻的构造序）
- `Network.requestWillBeSentExtraInfo` → `params.headersList`（**最终 wire 序**——已用裸
  TCP server 抓 socket 原始字节比对，与 `headersList` 逐项完全一致）

改动仅 `Network.pdl`（新增 `HeaderEntry` 类型 + 两处 `headersList` 字段）与
`network_handler.cc`（两个有序 helper，直接从本就保序的 `net::HttpRequestHeaders` /
`HttpRawHeaderPair` 建数组，绕开会排序的 `base::DictValue`）。

## 实现要点（补丁改了哪些层）

- **CDP 域**：`Fingerprint.pdl` + `fingerprint_handler.{cc,h}` + `browser_protocol.pdl`(include) +
  `content/browser/{,devtools/}BUILD.gn`(两处显式 outputs/编译清单) + `protocol_config.json` +
  `devtools_session.h`(白名单) + `render_frame_devtools_agent_host.cc`(注册)
- **存储/传播**：`web_contents_impl.{cc,h}`（per-BrowserContext + `GetRendererPrefs` 填充）
- **JS 值平面**：`navigator_base.cc`(platform/hwConcurrency/userAgent) `screen.cc`
  `navigator_language.cc` `frame_loader.cc`(UA/UA-CH metadata) `webgl_rendering_context_base.cc`
  `web_view_impl.cc`(locale/时区)
- **移动端自洽（读侧派生）**：`local_dom_window.cc`(`devicePixelRatio`←`dpr`)
  `navigator_events.cc`(`maxTouchPoints`) `media_values.cc`(pointer/hover 由 `maxTouchPoints` 派生)
  `screen_orientation.cc`(`type`/`angle` 由 `screenWidth/Height`+`maxTouchPoints` 派生)；
  全部守卫式：缺键即原样回退真机值，纯净启动零影响
- **请求头平面**：`client_hints.cc`(导航 UA-CH) `frame_fetch_context.cc`/`worker_fetch_context.cc`(子资源/worker)
- **worker**：`worker_global_scope.{cc,h}` `global_scope_creation_params.h` `dedicated_worker.cc`
  + shared/service worker 若干（`web_shared_worker_impl.cc` `web_embedded_worker_impl.cc` 等）
- **读回噪声**：`base_rendering_context_2d.cc` `html_canvas_element.cc`
  `offline_audio_context.cc` `analyser_node.cc` `webgl_rendering_context_base.cc`
- **请求头真实顺序**：`Network.pdl`（新增 `HeaderEntry` + 两处 `headersList`）、
  `network_handler.cc`（`Fetch.requestPaused` 与 `requestWillBeSentExtraInfo` 额外输出有序头数组）

## 已验证

第三方指纹检测页（跨主页 / iframe / 跨源 iframe / blob·dedicated·shared·service worker
+ 请求头）实测 **inconsistencies = 0**，Edge/法国/NVIDIA 全上下文自洽。
`navigator.userAgentData` 仅在安全上下文（HTTPS/localhost）存在，`data:` URL 下为
undefined 属规范行为。

`scripts/verify.py`（raw CDP，仅依赖 `websocket-client`）对自编译 chrome 全绿，覆盖
UA/platform/screen/deviceMemory/WebRTC(0·1·2 三模式)/canvas·WebGL·audio 读回，以及本轮
新增的移动端自洽维度：

- **桌面画像**（`maxTouchPoints:0`）：`devicePixelRatio=1.5`、`maxTouchPoints=0`、
  `pointer:fine`+`any-pointer:fine`+`hover:hover`（`pointer:coarse`/`hover:none` 均 false）、
  `screen.orientation.type=landscape-primary`、`angle=0`。
- **触屏画像**（`maxTouchPoints:5`，竖屏尺寸）：`devicePixelRatio=3.5`、`maxTouchPoints=5`、
  `pointer:coarse`+`any-pointer:coarse`+`hover:none`（`pointer:fine`/`hover:hover` 均 false）、
  `screen.orientation.type=portrait-primary`、`angle=0`。
- **WebGL2 分键**：webgl1 与 webgl2 上下文的 `getSupportedExtensions()` 各自命中
  `webglExtensions` / `webgl2Extensions`，两者互不串味（`webgl1 != webgl2` 生效）。

## 许可

补丁基于 Chromium（BSD-3-Clause）。新增文件沿用 Chromium 头部许可声明。
