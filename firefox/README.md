# Firefox 引擎 — per-context 指纹定制（Gecko 152.0.5）

本目录是 [antidetect-sandbox](https://github.com/zongrongjin/antidetect-sandbox)
里的 **Firefox** 引擎。Chromium 引擎在 [`../chromium/`](../chromium/README.md)。

对 **Firefox 152.0.5 (Gecko)** 的一套指纹定制补丁：给 `BrowsingContext` 增加一个
`FingerprintProfile`（JSON blob）synced field，并在 Gecko 各指纹读取点消费它，从而对
**每个 userContext / BrowsingContext** 下发**任意**一份指纹画像。新增一个 WebDriver BiDi
模块 `moz:context.setContextOverrides`——**一条命令**即可下发指纹与 per-context 上游代理
（支持账密）。该 context 的主页面 / iframe / 跨源 OOPIF / dedicated·shared·service worker
全部继承同一份指纹；指纹与出口 IP 一一对应。桌面 / **移动（安卓）** 画像通吃。

画像契约与 [`../chromium/`](../chromium/README.md) 对齐，
**去掉全部 UA-CH**（真实 Firefox 不发 `sec-ch-ua`、无 `navigator.userAgentData`）。

> ⚠️ 仅用于**授权的安全研究 / 反检测研究 / 隐私测试**。不含任何整棵 Gecko 源码，
> 只有补丁与脚本——按下面步骤拉官方 Firefox 源码后套用即可。

## 基础版本（必须一致）

| 项 | 值 |
|---|---|
| Firefox 版本 | **152.0.5** |
| 源码 | 官方 source tarball（gecko-dev git 无 release tag） |
| 平台 | Windows x64 / Linux x64 |

源码 tarball：`https://ftp.mozilla.org/pub/firefox/releases/152.0.5/source/firefox-152.0.5.source.tar.xz`
（Mozilla 官方，GFW 内可直连）。补丁基于该 tarball 解压后的工作区，`git init` 建 baseline 再套用。

## 仓库结构

```
patches/fp_all.diff         # 最终完整补丁（构建先应用这一份）
patches/fp_p0_capabilities.diff       # P0 阶段差异，仅作审计
patches/fp_consistency_followup.diff  # 一致性阶段差异，仅作审计
patches/fp_offscreen_webgl.diff       # OffscreenCanvas WebGL + masked Mozilla（由 Python 套用）
src-new/dom/base/FingerprintAndroidSurface.h
scripts/fp_apply.sh         # git apply fp_all + android/context/isTrusted/offscreen
scripts/patch_android_surface.py
scripts/patch_context_module.py       # moz:context.setContextOverrides
scripts/patch_input_trusted.py        # BiDi widget isTrusted=true；页面 JS 不改
scripts/patch_offscreen_webgl.py      # window OffscreenCanvas + masked RENDERER=Mozilla
scripts/fp_sync_verify.py
scripts/fp_webrtc_verify.py
scripts/kasada_demo.py      # Arc'teryx Kasada：url+html 假页，/tl 含 reload 为过
windows/                    # Windows 构建配方
docs/FINGERPRINT-SCHEMA.md
schemas/fingerprint.schema.json
```

## 从零构建

### Linux（Ubuntu 22.04，`mach build` 约 48min–1h）

```bash
# 0) 依赖：git、python3、curl、7z(p7zip) 等
# 1) 拉源码 tarball 并解压
curl -LO https://ftp.mozilla.org/pub/firefox/releases/152.0.5/source/firefox-152.0.5.source.tar.xz
tar xf firefox-152.0.5.source.tar.xz && cd firefox-152.0.5

# 2) bootstrap（拉 clang/rust/cbindgen；★不接受 --no-interactive，装完 Rust 需把
#    ~/.cargo/bin 加进 PATH 再跑一次）
./mach bootstrap --application-choice browser

# 3) 套补丁（git init baseline 后 git apply）
bash /path/to/this-repo/firefox/scripts/fp_apply.sh   # 内部 cd 到源码根

# 4) mozconfig
cat > mozconfig <<'EOF'
ac_add_options --enable-application=browser
ac_add_options --enable-optimize
ac_add_options --disable-debug
ac_add_options --enable-release
ac_add_options --disable-warnings-as-errors
ac_add_options --enable-bootstrap
export MOZILLA_OFFICIAL=1
EOF

# 5) 编译 + 打包
PYTHONUTF8=1 ./mach build          # 产物 obj-*/dist/bin/firefox
./mach package                     # 生成 installer/tarball

# 6) 验证
python3 /path/to/this-repo/firefox/scripts/fp_sync_verify.py obj-*/dist/bin/firefox
python3 /path/to/this-repo/firefox/scripts/fp_webrtc_verify.py obj-*/dist/bin/firefox
```

### Windows x64

见 **`windows/BUILD-WINDOWS.md`**（完整步骤与踩坑）。要点：

- **MozillaBuild** + **VS2022 BuildTools**（VCTools + Win11 SDK + ATL）+ **Rust/cargo/cbindgen**。
- 源码 tarball 用 `C:\mozilla-build\bin\7z.exe` **两步**解压（`.tar.xz`→`.tar`→文件）。
- mozconfig 用 `--enable-bootstrap=no-update`（复用现成 VS2022，别让它自动下 VS）；
  需要 **NSIS 3.x** 做 installer，且 `MAKENSISU` 要给绝对路径（PATH 里的可能被 vcvars 打乱）。
- `PYTHONUTF8=1` 全程（补丁含中文注释）。产物 `obj-release\dist\bin\firefox.exe`。

Latest Release 放 Windows 预编译：`firefox_zzbrowser_152.0.5_win64_installer.exe`。

## Kasada demo

和 Chromium 同一条路径：`moz:context.setContextOverrides` 一次下发指纹、代理、
cookie、`url`+`html`。假页是真实 `nsHttpChannel` 导航，不是 innerHTML。
PASS 当且仅当 `/tl` body 含 `reload`。不要 `Runtime.enable`，不要打印 ct/h。

```bash
pip install websocket-client
export KASADA_PROXY='http://user:pass@host:port'
export DISPLAY=:97    # headed Xvfb / 真屏
python3 firefox/scripts/kasada_demo.py /path/to/firefox
# 期望: kasada pjs=200 tl_status=200 body_len=15 reload=True
#       KASADA PASS
```

## 用法：一条 BiDi 命令下发指纹

连上 Firefox 的 WebDriver BiDi（`firefox -headless --remote-debugging-port 9223`，
连 `ws://127.0.0.1:9223/session`，`session.new`），对目标 userContext 发送：

```
moz:context.setContextOverrides  { "fingerprint": "<下面 JSON 的字符串>",
                                   "proxy": {"endpoint": "host:port", "username": "", "password": ""},
                                   "cache": {"dir": "/abs/cache", "map": "{}", "rules": "{}"},
                                   "cookies": [{"name":"a","value":"b","domain":"example.com"}],
                                   "url": "https://example.com/",
                                   "html": "<!doctype html>...",
                                   "userContexts": ["<userContext id>"] }
```

该 context 的所有页面（含之后新建 tab）与三种 worker 自动继承。用 WebDriver BiDi
直连即可（`websocket-client`）。

`fingerprint` 是 JSON **字符串**，不是 typed BiDi object。完整字段类型、WebGL typed
value、WebGPU/media 嵌套结构，以及“内核直接消费 / BC-only / 原生保持 / 共享契约未实现”
的边界见 [`docs/FINGERPRINT-SCHEMA.md`](docs/FINGERPRINT-SCHEMA.md)；机器校验使用
[`schemas/fingerprint.schema.json`](schemas/fingerprint.schema.json)。尤其注意：
`viewportWidth/viewportHeight` 需要 BC 另发 `browsingContext.setViewport`。
`plugins:[]` / Android UA 会清空 PDF 插件面；`connection` 可在安卓画像下露出
`navigator.connection`。`keyboard` 真 Firefox 没有，内核忽略。
`canvasBlobReplay` 不做（Firefox 自身 canvas 加噪 + `readbackSeed` 已覆盖 toBlob）。
`headersList` 不做（Firefox 请求头本身就是发出顺序）。

`cache` / `url`+`html` / `cookies` 与 Chromium `Context.setContextOverrides` 对齐：HIT 与内存假首页走 `nsIReplacedHttpResponse`（HTTP/1.1，不发网）。BiDi `input.performActions` 保持 widget 路径（`isTrusted=true`）；页面 JS `dispatchEvent`/`new Event` 不改，仍按真 Firefox 为 `false`。

### 配套：per-context 上游代理

`proxy` 与 `fingerprint` 在同一条 `moz:context.setContextOverrides` 里下发，
让指纹与出口 IP 成对（避免"指纹是安卓、IP 落地却全一样"这类交叉破绽）：

```
moz:context.setContextOverrides  { "proxy": {"endpoint": "host:port",
                                             "username": "<可选>", "password": "<可选>"},
                                   "userContexts": ["<userContext id>"] }
```

按 userContext 建路由表，账密随 endpoint 一起下发（支持 `user:pass@host:port` 代理）。
指纹和代理必须走同一条 `moz:context.setContextOverrides`，不要拆成旧的 `moz:fingerprint` + `moz:proxy`。

### 指纹 JSON 画像（示例：Windows / 法国 / NVIDIA）

```jsonc
{
  "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
  "platform": "Win32",
  "oscpu": "Windows NT 10.0; Win64; x64",
  "appVersion": "5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
  "acceptLanguages": "fr-FR,fr;q=0.9,en;q=0.8",
  "locale": "fr-FR",
  "timezone": "Europe/Paris",
  "hardwareConcurrency": 8,
  "referrer": "",
  "screenWidth": 1920,
  "screenHeight": 1080,
  "availWidth": 1920,
  "availHeight": 1040,
  "availLeft": 0,
  "availTop": 0,
  "colorDepth": 24,
  "dpr": 1,
  "maxTouchPoints": 0,
  "outerWidth": 1920,
  "outerHeight": 1040,
  "viewportWidth": 1920,
  "viewportHeight": 953,
  "webRTCPublicIP": "203.0.113.7",
  "webRTC": 1,
  "webglVendor": "Google Inc. (NVIDIA)",
  "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "webglExtensions": [
    "ANGLE_instanced_arrays",
    "EXT_blend_minmax",
    "EXT_texture_filter_anisotropic",
    "WEBGL_debug_renderer_info"
  ],
  "webgl2Extensions": [
    "EXT_color_buffer_float",
    "EXT_texture_filter_anisotropic",
    "WEBGL_debug_renderer_info",
    "WEBGL_multi_draw"
  ],
  "webglParameters": {
    "3379": {"type": "int", "value": 16384},
    "33901": {"type": "float32", "value": [1, 1024]},
    "36347": {"type": "int", "value": 4096}
  },
  "webgl2Parameters": {
    "3379": {"type": "int", "value": 16384},
    "36183": {"type": "int", "value": 4},
    "36347": {"type": "int", "value": 4096}
  },
  "webglShaderPrecision": {
    "35632:36338": [127, 127, 23]
  },
  "webgl2ShaderPrecision": {
    "35632:36338": [127, 127, 23]
  },
  "webGPU": {
    "adapter": {
      "vendor": "NVIDIA",
      "architecture": "",
      "device": "",
      "description": "NVIDIA GeForce RTX 3060",
      "backend": "d3d12",
      "type": "discrete-gpu",
      "isFallbackAdapter": false,
      "subgroupMinSize": 32,
      "subgroupMaxSize": 32
    },
    "features": ["texture-compression-bc", "timestamp-query"],
    "limits": {
      "maxTextureDimension2D": 16384,
      "maxBindGroups": 4,
      "minUniformBufferOffsetAlignment": 256
    },
    "preferredCanvasFormat": "bgra8unorm"
  },
  "fontFamilies": ["Arial", "Segoe UI", "Consolas"],
  "fontAliases": {
    "system-ui": "Segoe UI",
    "sans-serif": "Arial",
    "monospace": "Consolas"
  },
  "speechVoices": [
    {
      "name": "Microsoft Denise",
      "lang": "fr-FR",
      "voiceURI": "urn:fp:Microsoft Denise",
      "localService": true,
      "default": true
    }
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
      "video/webm; codecs=\"vp8\"": "probably",
      "video/mp4; codecs=\"avc1.42E01E\"": "probably"
    },
    "mediaSource": [
      "video/webm; codecs=\"vp8\"",
      "video/mp4; codecs=\"avc1.42E01E\""
    ],
    "decodingInfo": {
      "video/webm; codecs=\"vp8\"": {
        "supported": true,
        "smooth": true,
        "powerEfficient": false
      }
    }
  },
  "mediaDevices": [
    {"kind": "audioinput", "deviceId": "default", "groupId": "", "label": ""},
    {"kind": "audiooutput", "deviceId": "default", "groupId": "", "label": ""}
  ],
  "readbackSeed": 77777,
  "canvasDataReplay": ["<base64 RGBA bytes>"],
  "canvasUrlReplay": ["<complete data:image/... URL>"],
  "glReadReplay": ["<base64 RGBA bytes>"],
  "audioReplay": ["<base64 little-endian float32 samples>"],
  "analyserFloatReplay": ["<base64 float32 samples>"],
  "analyserByteReplay": ["<base64 bytes>"]
}
```

这是完整字段形状示例，不是要求每次全部传入；没有真机采样值的可选项应直接删掉，让
对应读取点走原生回退。`viewportWidth/viewportHeight` 由 BC 另发
`browsingContext.setViewport` 才会改变实际 viewport，outer bounds 也由 BC 同步。
`fontAliases` 负责选择，但节点仍需安装对应字体文件才能得到真实 metrics。
`mediaDevices` 只覆盖授权前 `enumerateDevices()` 视图，不伪造权限或硬件。

安卓画像应显式传 `plugins: []`、`mimeTypes: []`、`pdfViewerEnabled: true`，并按需传
`connection`。桌面画像不传这些键时保持现代 Firefox 原生固定 PDF 面（5 plugins、
2 MIME types）且没有 `navigator.connection`。`productCapabilities` 只是 BC
自洽元数据；`canvasBlobReplay` 虽属于共享 BC 契约，但当前 Firefox 内核尚未消费。

> **与 Chromium 画像的差异**：去掉 `uaBrands`/`uaFullBrands`/`uaPlatform`/`deviceMemory`
> （Firefox 不发 UA-CH、不实现 `navigator.deviceMemory`——加了反成特征）；新增 `oscpu`。
> 其余键含义与 Chromium 一致。

> **WebRTC**：`webRTCPublicIP` 覆盖 srflx candidate 上报的公网地址，让 WebRTC 层与 HTTP
> 代理出口 IP 一致。host candidate 不动——Firefox 已用 mDNS（`xxxx.local`）混淆，同 Chromium。
> 不传该字段时 WebRTC 行为与原版相同。Firefox **不用 libwebrtc 的 P2P**（那是死代码），
> 用自研 nICEr，且跑独立 socket process，故覆盖经 IPDL 跨进程传到 nICEr。

> **噪声 vs 固定回放**：`readbackSeed` 在真机基础上加确定性微扰（够用、体积小）；
> `*Replay` 直接回放真机采集的原值（能过"已知真机值白名单"，但需真机采集、体积大）。
> 同一读回点：**回放存在时优先回放，否则走噪声，再否则 native**。

## 覆盖的指纹维度

| 维度 | 键 | 覆盖面 |
|---|---|---|
| navigator.userAgent | `userAgent` | 主/iframe/OOPIF/三种 worker |
| navigator.platform | `platform` | 全上下文 |
| navigator.oscpu | `oscpu` | 全上下文 |
| navigator.appVersion | `appVersion` | 全上下文（与 `userAgent` 自洽，移动画像需一并给） |
| navigator.languages + Accept-Language 头 | `acceptLanguages` | 全上下文；**自动剥 q 值**（`languages` 里绝不含 `;q=`） |
| Intl locale / 时区 | `locale` / `timezone` | 全上下文 |
| navigator.hardwareConcurrency | `hardwareConcurrency` | 全上下文 |
| screen 宽高 | `screenWidth`/`screenHeight` | 主/iframe |
| screen 可用区域 | `availWidth`/`availHeight`/`availLeft`/`availTop` | 不传按 `platform` 推导，**不可与整屏相同**（真实桌面有任务栏/菜单栏） |
| screen.colorDepth / pixelDepth | `colorDepth` | 同上（Gecko 里两属性同映射一个函数） |
| screen.orientation type/angle | 由 `screenWidth`/`screenHeight` + `maxTouchPoints` 推导 | 主/iframe/OOPIF；type 按伪装屏幕宽高给朝向（竖屏画像=`portrait-primary`），**不再跟宿主机显示器**（默认路径安卓竖屏会漏成 landscape）。angle 按**设备类**判自然朝向：桌面（`maxTouchPoints==0`）自然横屏→landscape=0°/portrait=90°；移动自然竖屏→portrait=0°/landscape=90°（单一 `宽>高?90:0` 规则只对手机成立，桌面会反） |
| window.devicePixelRatio | `dpr` | 全上下文；0 尺寸 / null 主体子文档（sandbox srcdoc）拿不到 presContext 时回退画像 dpr |
| maxTouchPoints / TouchEvents / pointer·hover | `maxTouchPoints` | 统一驱动 `maxTouchPoints`、`ontouchstart`、`(pointer:coarse)`/`(hover:none)`——移动画像四者自洽。pointer/hover 由 `maxTouchPoints` 设备类**盖过宿主 LookAndFeel**：桌面(`==0`)=`fine`+`hover`、移动(`>0`)=`coarse`+无 hover，无鼠标云 VM 也不会在桌面 UA 下漏 coarse/none（落点 `nsMediaFeatures.cpp`，primary 与 any-* 同源） |
| WebRTC srflx 公网 IP | `webRTCPublicIP` | candidate 字符串 / `.address` / SDP，经 nICEr srflx 回调覆盖 |
| WebGL UNMASKED + MASKED vendor/renderer | `webglVendor`/`webglRenderer` | 主/iframe/OOPIF + 三种 worker；masked `RENDERER` 也走画像（原泄漏宿主 ANGLE/D3D），masked `VENDOR` 恒 "Mozilla"（真安卓一致） |
| WebGL 扩展列表 | `webglExtensions` / `webgl2Extensions` | 内核 `GetSupportedExtensions` 按上下文 `mIsWebGL2` 分键：webgl1 读 `webglExtensions`、webgl2 读 `webgl2Extensions`。真机两套集合不同，必须分开下发（合并即 webgl1==webgl2，本身是破绽）；缺任一键则该版本干净回退原生枚举 |
| WebGL 能力 / shader precision | `webglParameters` / `webgl2Parameters` / `webglShaderPrecision` / `webgl2ShaderPrecision` | typed value schema；缺键原生回退 |
| 系统字体与别名 | `fontFamilies` / `fontAliases` | 字体查询 + Gecko 实际字体选择；Canvas/TextMetrics、DOM/Range 与 worker OffscreenCanvas 共用结果 |
| Speech voices | `speechVoices` | name/lang/voiceURI/localService/default |
| WebGPU | `webGPU` | adapter、features（与原生支持集取交集）、limits（只向保守方向收敛）、preferredCanvasFormat |
| 窗口与 viewport | `outerWidth`/`outerHeight`/`viewportWidth`/`viewportHeight` | outer 属性由 BrowsingContext 画像覆盖；BC 用 BiDi setViewport 同步实际 viewport/DPR |
| CSS 媒体特性 | `cssMedia` | color-gamut、dynamic-range/HDR、forced-colors、prefers-contrast、prefers-reduced-motion |
| 媒体能力 | `mediaCodecs` | canPlayType、MSE 与 decodingInfo exact-content-type 矩阵；DRM/keySystem 保持原生 |
| 媒体设备 | `mediaDevices` | enumerateDevices 的 per-context 预授权视图 |
| PDF 兼容面 | `plugins` / `mimeTypes` / `pdfViewerEnabled` | 空数组或 Android/iOS UA → 空插件面 + pdfViewerEnabled 缺省 true；桌面不传保持原生 5 PDF |
| Network Information | `connection` | false/iOS 隐藏；对象或 Android UA 露出 `connection.type`（桌面 Firefox 默认无此 API） |
| Keyboard API | `keyboard` | 真 Firefox 无此 API，键忽略 |
| 读回**噪声** | `readbackSeed` | canvas getImageData/toDataURL、WebGL readPixels、toBlob、OfflineAudioContext/AnalyserNode |
| 读回**固定回放** | `canvas*Replay` / `glReadReplay` / `audioReplay` / `analyser*Replay` | 按调用序回放真机值，优先于噪声 |

Windows 无硬件 GPU/RDP 节点需在启动 profile 的 `user.js` 写入：
`webgl.force-enabled=true`、`gfx.webrender.software=true`、
`webgl.angle.force-warp=true`。这三项已用于 WebGL1/WebGL2 的
A/B/原生 userContext 隔离实测；它们不保证 WebGPU adapter 可用。

存储为 **BrowsingContext synced field**（parent 设、IPC 广播到所有 content 进程含跨源
OOPIF）；worker 经 `WorkerLoadInfo`/`ClientInfo` 快照带入。

`scripts/fp_apply.sh` 先应用最终 `fp_all.diff`，再跑
`scripts/patch_android_surface.py`（plugins / pdfViewer / connection）。
两个阶段差异文件不能叠加应用，因为少量源文件存在重叠。`fp_all.diff` 由
Firefox 152.0.5 pristine tarball 与实际通过编译和运行验证的源码重新生成。
android-surface 目前以 patcher 为准，尚未从编译树回导出独立 diff。

## 4 个 Firefox 专属反检测点

- **`navigator.webdriver` → false**（BiDi 连接本会置 true）。落点 `Navigator::Webdriver()`。
- **`document.visibilityState` → "visible"**。落点 `Document::VisibilityState/Hidden`。
- **`document.hasFocus()` = true + `document.hidden` = false**。落点 `Document::HasFocus` +
  `nsDocShell::ShouldOverrideHasFocus` + `nsFocusManager`。
- **Shadow DOM 原生穿透**（chrome-only `Element.openOrClosedShadowRoot`，不用 JS 猴补丁，
  避免 `attachShadow.toString()` 露馅）。

## 与 Chromium 功能同步状态

| 功能 | Chromium | Firefox |
|---|---|---|
| UA / platform / locale / timezone / screen / WebGL / canvas·audio 读回 | ✅ | ✅ |
| navigator.languages 剥 q 值 | ✅ | ✅ |
| screen 可用区域推导 / colorDepth | ✅ | ✅ |
| WebRTC srflx 公网 IP 覆盖（`webRTCPublicIP`） | ✅ | ✅（经 nICEr + IPDL） |
| WebRTC 路由策略开关（`webRTC` 0/1/2） | ✅ | ✅（per-context IPC 透传到 `NrIceCtx::Policy`） |
| per-context 上游代理（`moz:context.setContextOverrides` 的 `proxy`） | ✅ | ✅（按 userContext 路由表，支持账密） |
| 移动（安卓）画像：appVersion / maxTouchPoints / screen.orientation / dpr / masked WebGL | ✅ | ✅ |
| android-surface：空 plugins + pdfViewerEnabled + connection | ✅（`wip/ds6797` / android-surface tag） | ✅（本分支 `wip/android-surface`；无 Keyboard API） |
| UA-CH（`uaBrands` 等） | ✅ | — 不适用（Firefox 不发 UA-CH） |
| deviceMemory | ✅ | — 不做（Firefox 不实现该 API） |
| `cache` HIT / captures / blocks | ✅ | ✅（`nsIReplacedHttpResponse`，HTTP/1.1） |
| `url` + `html` 内存假首页 | ✅ | ✅ |
| 同条命令种 `cookies` | ✅ | ✅（`Services.cookies` + userContextId） |
| `headersList` | ✅ | — 不做（Firefox 头序本真） |
| `canvasBlobReplay` | ✅ | — 不做（原生加噪 + `readbackSeed`） |
| BiDi/CDP 输入 `isTrusted` | widget 真输入 | widget 真输入；页面 JS 事件不改 |

## 已验证

- `scripts/fp_sync_verify.py`：languages 剥 q、availHeight≠height（Win 扣任务栏 / Mac 扣菜单栏）、
  colorDepth 覆盖、跨 userContext 隔离 —— 真实编译的 Firefox 上 BiDi 实测 `ALL PASSED`。
- `scripts/fp_webrtc_verify.py`：下发 `webRTCPublicIP` 后 srflx 报 fakeIP、SDP 不含真实 IP、
  host 仍 mDNS —— 退出码 0。

## 许可

补丁基于 Firefox / Gecko（MPL-2.0）。新增文件沿用 Gecko 头部许可声明。
