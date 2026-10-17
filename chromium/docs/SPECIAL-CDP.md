# zzbrowser 特殊 CDP 用法

相对官方 Chrome 多出来的协议，以及 `fingerprint` JSON 的完整字段契约。产品号 `151.0.7907.0`，当前 Windows 包 tag `chrome-v151.0.7907.0-20260911`。Official `chrome.exe` 约 **3.8MB**；1.6MB 是 component stub，不是本构建。

机器可读画像 schema：[`schemas/fingerprint.schema.json`](../schemas/fingerprint.schema.json)。

Windows 预编译：

```
windows/chromium_zzbrowser_151.0.7907.0_win64_mini_installer.exe
```

系统级安装后二进制在 `C:\Program Files\Chromium\Application\chrome.exe`。启动调试口：

```bat
chrome.exe --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=%TEMP%\zz-cdp
```

无硬件 GPU / RDP 时加 `--enable-unsafe-webgpu --ignore-gpu-blocklist`。不要叠 SwiftShader Vulkan。

---

## 和官方 Chrome 的差别

| | 官方 Chrome | zzbrowser |
|---|---|---|
| 隔离 context 代理 | `Target.createBrowserContext({proxyServer})` + 常要 `Fetch.enable` 处理 407 | **不要**传 `proxyServer`。代理走 `Context.setContextOverrides.proxy`，内核预发 `Proxy-Authorization`，无 407 |
| 指纹 | 没有 per-context 原生画像 | 一条 `Context.setContextOverrides`，`fingerprint` 是 **JSON 字符串** |
| 缓存 / 假页 / 种 cookie / 导航 | Fetch 拦截、`Network.setCookies`、`Page.navigate` | 同一条 `Context.setContextOverrides` 的 `cache` / `html` / `cookies` / `url` |
| 请求头顺序 | `headers` 是 JSON 对象，被字母序打乱 | `Fetch.requestPaused` 与 `Network.requestWillBeSentExtraInfo` 另有 **`headersList`**，保真实顺序 |

这条路上 **不要** `Fetch.enable` `urlPattern: "*"`。代理、缓存、html 假页都由内核做。需要 Abort/改包时再对白名单开 Fetch，不要对整个 Context 开 `*`。

遗留域 `Fingerprint.setContextOverrides` 仍可能存在，只收 `fingerprint` 字符串。新代码只用 `Context`。

---

## 会话怎么开

对 **Browser** websocket（`/json/version` 的 `webSocketDebuggerUrl`），按顺序：

1. `Target.createBrowserContext` — **不带** `proxyServer`
2. `Target.createTarget` `{url:"about:blank", browserContextId}`
3. `Target.attachToTarget` `{targetId, flatten:true}` → `sessionId`
4. 用这个 `sessionId` 发 `Context.setContextOverrides`

命令作用域是当前 target 所属 **BrowserContext**。之后该 context 的主页面、iframe、OOPIF、dedicated/shared/service worker 都继承同一份指纹和代理。省略的字段保持上次值；空串清画像 / 清代理。

探测是否为本构建：对已 attach 的 session 发 `Context.setContextOverrides` `{}`，成功即有 Context 域。

---

## `Context.setContextOverrides`

```
method: Context.setContextOverrides
sessionId: <page session>
params:
  fingerprint?: string          # 画像 JSON 序列化后的字符串；"" 清画像
  proxy?: {
    endpoint?: string           # "http://host:port" / "socks5://host:port" / "host:port"；"" 清代理
    username?: string
    password?: string
  }
  cache?: {
    dir?: string                # 绝对目录；索引在 <dir>/_map.json
    map?: string                # JSON 字符串：url -> {file,status,headers,created_at}
    rules?: string              # JSON 字符串，见下
  }
  cookies?: CookieParam[]       # 种进该 context 的 cookie 罐
  url?: string                  # 覆盖生效后导航（先应用 proxy）
  html?: string                 # 与 url 一起：首文档是内存假页，不走网
```

### fingerprint

必须是字符串，不能把画像字段摊在 CDP params 顶层。完整字段见下文「fingerprint 字段契约」。

```python
session.call("Context.setContextOverrides", {
    "fingerprint": json.dumps(profile, separators=(",", ":")),
})
```

`viewportWidth` / `viewportHeight` 改 JS 侧 viewport；**真实 layout** 还要另发：

```
Emulation.setDeviceMetricsOverride
  width, height, deviceScaleFactor(=dpr), mobile, screenWidth, screenHeight
```

Chrome 151 GREASE：`Not=A?Brand` / `99`，顺序 grease → Google Chrome → Chromium。brand 短键是 `{"b","v"}`，不是 `brand`/`version`。

### proxy

隔离 context **直连创建**，再由本字段写到该 BrowserContext 的 NetworkContext。账密不走 Fetch。`endpoint` 空串清除。

### cache

`map` 和 `rules` 都是 **JSON 字符串**（和 fingerprint 一样，不是 typed object）。

`rules` 对象：

```json
{
  "captures": ["https://example.com/secret.js"],
  "callbacks": ["*/api/*"],
  "blocks": ["*/telemetry/*"],
  "allowMiss": [],
  "observe": ["*.png"],
  "include": ["*"],
  "exclude": ["*/api/*"],
  "ttl": 0,
  "maxEntry": 0,
  "cacheableStatus": [200]
}
```

匹配顺序（先命中先生效）：

**captures > callbacks > HIT > blocks > allow-miss > observe > pass**

- **HIT**：`map` 里有条目则内核直接 fulfill，不发网。
- **MISS** 且 GET 2xx：把解码后的 body 写到 `dir`，并更新 `_map.json`。
- **captures**：走网，但匹配的响应可被内核抓住。
- **callbacks**：内核发 `Context.callback` 事件，把 URL 交给上层。
- **blocks**：拦截。
- **observe**：正常走网，发 `Context.observed`。

对应事件：

| 事件 | 参数 |
|---|---|
| `Context.callback` | `{url}` |
| `Context.observed` | `{url}` |
| `Context.captured` | `{url}` |

### cookies

字段与 `Network.setCookie` 对齐：`name` `value`，可选 `url` `domain` `path` `secure` `httpOnly` `sameSite`（`Strict`/`Lax`/`None`）`expires`（unix 秒，省略即 session）。

### url / html

| 传参 | 行为 |
|---|---|
| 只有 `url` | 代理生效后 **真导航** |
| `url` + `html` | 该 URL 的 **首文档是内存假页**，不走网；页面里的子资源仍按 cache/proxy 走 |
| 都不传 | 停在 `about:blank`，之后自己 `Page.navigate` |

Kasada 这类「先给文档再等 `/tl`」用 `url`+`html`，不要用 Fetch 把文档 fulfill 进去。

---

## `headersList`（请求头真顺序）

官方 `Network.Headers` 是对象，底层按 key 字母序。本构建在两个回调上额外给 **有序数组**，原 `headers` 对象仍在。

- `Fetch.requestPaused` → `params.request.headersList`
- `Network.requestWillBeSentExtraInfo` → `params.headersList`（最终 wire 序）

形状：`[{ "name": "Accept", "value": "..." }, ...]`，保留重复头。反检测看头序时读这个，不要读 `headers` 对象。

---

## 原始 CDP 最小例子

```python
import json
from websocket import create_connection

# 1) GET http://127.0.0.1:9222/json/version → webSocketDebuggerUrl
ws = create_connection(browser_ws)
_id = 0

def call(method, params=None, session_id=None):
    global _id
    _id += 1
    msg = {"id": _id, "method": method, "params": params or {}}
    if session_id:
        msg["sessionId"] = session_id
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id:
            if "error" in r:
                raise RuntimeError(r["error"])
            return r.get("result", {})

ctx = call("Target.createBrowserContext")["browserContextId"]
tid = call("Target.createTarget", {
    "url": "about:blank", "browserContextId": ctx,
})["targetId"]
sess = call("Target.attachToTarget", {
    "targetId": tid, "flatten": True,
})["sessionId"]

fp = {
    "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "platform": "Win32",
    "uaPlatform": "Windows",
    "hardwareConcurrency": 8,
    "formFactors": ["Desktop"],
}
call("Context.setContextOverrides", {
    "fingerprint": json.dumps(fp, separators=(",", ":")),
    "proxy": {
        "endpoint": "http://host:port",
        "username": "user",
        "password": "pass",
    },
    "cookies": [{
        "name": "_vid", "value": "abc",
        "domain": ".example.com", "path": "/", "secure": True,
    }],
    "url": "https://example.com/",
    # "html": "<html><body>first document</body></html>",
}, session_id=sess)

call("Emulation.setDeviceMetricsOverride", {
    "width": 1920, "height": 1080,
    "deviceScaleFactor": 1, "mobile": False,
    "screenWidth": 1920, "screenHeight": 1080,
}, session_id=sess)
```

wire：

```json
{
  "id": 4,
  "method": "Context.setContextOverrides",
  "sessionId": "<page-session>",
  "params": {
    "fingerprint": "{\"platform\":\"Win32\",\"hardwareConcurrency\":8}",
    "proxy": {"endpoint": "http://host:port", "username": "u", "password": "p"}
  }
}
```

---

## Python BC 封装

`browser_controller` 探测到 Context 域后，`new_context(...)` **只打这一条 CDP**：

```python
from browser_controller import connect

root = connect(port=9222)
ctx = root.new_context(
    proxy="user:pass@host:port",
    fingerprint=profile.fingerprint,  # Fingerprint / dict，内部 json.dumps
    cache=cache,                      # 编成 cache.dir / map / rules
    cookies=[{"name": "a", "value": "1", "domain": ".example.com"}],
    url="https://example.com/",
    html=None,                        # 与 url 同传则假页
)
```

官方 Chrome 没有 Context 域时：代理仍绑 `createBrowserContext.proxyServer`，指纹走遗留 `Fingerprint.setContextOverrides`，cookie 走 `Network.setCookies`，url 走 `Page.navigate`。

---

## 不要做的事

- 对 zzbrowser Context 路径 `Fetch.enable` `*`（Kasada / 缓存 / 假页会烂）。
- `Target.createBrowserContext` 带 `proxyServer`（本构建代理不走这条）。
- 把画像字段直接放在 CDP params 顶层（必须先 `json.dumps`）。
- 只靠 `Context.setContextOverrides` 改真实窗口 layout（还要 `Emulation.setDeviceMetricsOverride`）。
- 用 `chrome://version` 的 Revision 判断包（本构建 LASTCHANGE 常为 `00000000-00000000`）。看 GitHub tag 和 `chrome.exe` 大小。

---

## fingerprint 字段契约

`Context.setContextOverrides` 的 `fingerprint` 参数是 **JSON 字符串**。画像对象必须先序列化，不能把字段直接放到 CDP `params` 顶层。遗留 `Fingerprint.setContextOverrides` 同样只收这一份字符串。

命令以当前 target 所属 `BrowserContext` 为作用域。之后在该 BrowserContext 创建的页面、OOPIF 和 worker 通过 `RendererPreferences` / worker creation params 继承画像。所有字段均可选；字段缺失、类型不符或对应子键缺失时，相关读取点回退 Chromium 原生行为。

再次调用会 **替换整个** BrowserContext JSON，不是与旧画像深度合并。只改单个字段时，调用方应先在本地合并完整画像再重发。恢复全部原生：`fingerprint` 传空串 `""`，或传 `"{}"`。

### 支持层级

- **内核直接消费**：只调用 `Context.setContextOverrides` 即可生效。
- **内核 + BC**：内核读取画像，同时 BC 还会发 CDP Emulation 命令同步真实 viewport。
- **BC-only**：字段会被 `browser_controller.Fingerprint` 序列化，但不是本命令的读取点。
- **能力描述 / 原生**：用于 BC 自洽检查；当前浏览器保持原生 API。

### 身份、UA 与语言

| 字段 | 类型 | 层级 | 行为 |
|---|---|---|---|
| `userAgent` | string | 内核 | `navigator.userAgent`、导航/子资源 UA、所有 worker |
| `uaPlatform` | string | 内核 | UA-CH `platform` 与 `sec-ch-ua-platform` |
| `uaBrands` | `[{b,v}]` | 内核 | 低熵 brands 与 `sec-ch-ua` |
| `uaFullBrands` | `[{b,v}]` | 内核 | `fullVersionList` 与高熵请求头 |
| `uaFullVersion` | string | 内核 | UA-CH full version |
| `platform` | string | 内核 | `navigator.platform` |
| `platformVersion` | string | 内核 | UA-CH platformVersion |
| `architecture` | string | 内核 | UA-CH architecture |
| `model` | string | 内核 | UA-CH model |
| `mobile` | boolean | 内核 | UA-CH mobile |
| `bitness` | string | 内核 | UA-CH bitness |
| `wow64` | boolean | 内核 | UA-CH wow64 |
| `formFactors` | `string[]` | 内核 | UA-CH `formFactors` 与 `sec-ch-ua-form-factors`；缺省时 `mobile`/Android→`["Mobile"]`，否则 `["Desktop"]` |
| `acceptLanguages` | string | 内核 | `navigator.language(s)` 与导航/子资源 `Accept-Language` |
| `locale` | string | 内核 | Intl locale override |
| `timezone` | string | 内核 | Intl IANA timezone override |
| `hardwareConcurrency` | integer ≥ 1 | 内核 | window 与 worker |
| `deviceMemory` | number > 0 | 内核 | JS 属性以及 Device-Memory/CH 请求头 |
| `referrer` | string | 内核 | 顶层文档 `document.referrer` |

直接调用协议时，brand 项必须使用短键：

```json
{
  "uaBrands": [
    {"b": "Not=A?Brand", "v": "99"},
    {"b": "Google Chrome", "v": "151"},
    {"b": "Chromium", "v": "151"}
  ],
  "uaFullBrands": [
    {"b": "Not=A?Brand", "v": "99.0.0.0"},
    {"b": "Google Chrome", "v": "151.0.7907.0"},
    {"b": "Chromium", "v": "151.0.7907.0"}
  ]
}
```

BC Python API 接受 `{"brand": ..., "version": ...}`，序列化时自动转换为 `b/v`。

### 屏幕、窗口与输入

| 字段 | 类型 | 层级 | 行为 |
|---|---|---|---|
| `screenWidth` / `screenHeight` | integer ≥ 0 | 内核 | `screen.width/height` |
| `availWidth` / `availHeight` | integer ≥ 0 | 内核 | `screen.availWidth/Height` |
| `availLeft` / `availTop` | integer | 内核 | screen 可用区偏移 |
| `colorDepth` | integer > 0 | 内核 | `colorDepth` 与 `pixelDepth` |
| `dpr` | number > 0 | 内核 + BC | `devicePixelRatio`；BC 另同步 device metrics |
| `maxTouchPoints` | integer ≥ 0 | 内核 | touch、pointer/hover media、自洽 orientation 派生 |
| `outerWidth` / `outerHeight` | integer ≥ 0 | 内核 | `window.outerWidth/outerHeight` |
| `viewportWidth` / `viewportHeight` | integer ≥ 0 | 内核 | layout viewport：`innerWidth/Height`、`visualViewport`、WebView `Resize`（CSS `matchMedia` / `getBoundingClientRect`）。缺省回落 `screenWidth/Height`。真实窗口 layout 另发 `Emulation.setDeviceMetricsOverride`。 |

### WebRTC

| 字段 | 类型 | 行为 |
|---|---|---|
| `webRTC` | `0 / 1 / 2` | `0` 禁止非代理 UDP；`1` 默认；`2` 仅默认路由、隐藏 host |
| `webRTCPublicIP` | string | 仅覆盖 srflx 公网地址 |

`webRTC=0` 不生成 srflx，因此与 `webRTCPublicIP` 实际互斥。不传字段时不改变原生 WebRTC。公网 IP 覆盖目标包括 candidate 字符串、`.address`、SDP 和 `getStats()`。

### WebGL

| 字段 | 类型 | 行为 |
|---|---|---|
| `webglVendor` / `webglRenderer` | string | UNMASKED vendor/renderer |
| `webglExtensions` | string[] | WebGL1 期望扩展 |
| `webgl2Extensions` | string[] | WebGL2 期望扩展 |
| `webglParameters` | parameter map | WebGL1 `getParameter()` |
| `webgl2Parameters` | parameter map | WebGL2 `getParameter()` |
| `webglShaderPrecision` | precision map | WebGL1 shader precision |
| `webgl2ShaderPrecision` | precision map | WebGL2 shader precision |

扩展只暴露“画像期望 ∩ 当前构建真实可实例化扩展”，不会虚构不可调用的扩展。空数组与缺字段均回退原生；若要收窄扩展，请传非空目标列表。

parameter map 的键是十进制 GLenum，值为 typed object：

```json
{
  "webglParameters": {
    "3379": {"type": "int", "value": 16384},
    "33901": {"type": "float32", "value": [1, 1024]},
    "36347": {"type": "int", "value": 4096},
    "37445": {"type": "string", "value": "Google Inc. (NVIDIA)"}
  }
}
```

支持的 `type`：

| type | value |
|---|---|
| `bool` | boolean |
| `int` | integer |
| `uint` | non-negative integer |
| `float` | number |
| `string` | string |
| `int32` | integer[]，返回 `Int32Array` |
| `float32` | number[]，返回 `Float32Array` |

shader precision 的键为 `shaderType:precisionType` 两个十进制 GLenum，值依次为 `[rangeMin, rangeMax, precision]`：

```json
{
  "webglShaderPrecision": {
    "35632:36338": [127, 127, 23]
  }
}
```

### WebGPU

```json
{
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
    "features": [
      "texture-compression-bc",
      "timestamp-query"
    ],
    "limits": {
      "maxTextureDimension2D": 16384,
      "maxBindGroups": 4,
      "minUniformBufferOffsetAlignment": 256
    },
    "preferredCanvasFormat": "bgra8unorm"
  }
}
```

- adapter 缺少的字段保持真实 adapter 值。
- features 取画像与底层支持集的交集。
- `max*` limits 只能向更小、更保守方向覆盖。
- `min*` alignment limits 只能向更大、更保守方向覆盖。
- 无真实 adapter 时不能仅靠画像创造一个 adapter。

### 字体与 Speech

```json
{
  "fontFamilies": ["Arial", "Segoe UI", "Consolas"],
  "fontAliases": {
    "system-ui": "Segoe UI",
    "sans-serif": "Arial",
    "monospace": "Consolas"
  },
  "speechVoices": [
    {
      "name": "Microsoft Zira",
      "lang": "en-US",
      "voiceURI": "Microsoft Zira",
      "localService": true,
      "default": true
    }
  ]
}
```

- `fontFamilies` 控制字体可用性查询。
- `fontAliases` 在实际字体选择层生效，DOM、Range、Canvas/TextMetrics 与 worker OffscreenCanvas 共用结果。
- 字体名称映射不等于已经具备目标字体二进制；真实 metrics 仍需要节点字体包。
- `speechVoices` 覆盖 `getVoices()` 的五个可观察字段；真实 `voiceschanged` 时序不在本字段契约内。

### CSS 媒体特性

```json
{
  "cssMedia": {
    "colorGamut": "p3",
    "dynamicRange": "high",
    "forcedColors": "none",
    "prefersContrast": "no-preference",
    "prefersReducedMotion": "no-preference"
  }
}
```

允许值：

- `colorGamut`: `srgb | p3 | rec2020`
- `dynamicRange`: `standard | high`
- `forcedColors`: `none | active`
- `prefersContrast`: `no-preference | more | less | custom`
- `prefersReducedMotion`: `no-preference | reduce`

### 媒体能力与设备

```json
{
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
    {
      "kind": "audioinput",
      "deviceId": "default",
      "groupId": "",
      "label": ""
    }
  ]
}
```

- content type 是 exact string key；调用值未命中时回退原生。
- `mediaSource` 字段存在时是严格允许列表，空数组表示全部不支持。
- `decodingInfo` 同时带 audio/video 时合并两项布尔结果。
- 带 `keySystemConfiguration` 的 DRM 查询始终保持原生。
- `mediaDevices` 只覆盖 `enumerateDevices()` 的预授权可见视图，不伪造 `getUserMedia()` 成功、权限状态或真实硬件。

### 读回噪声与固定回放

| 字段 | 内容 |
|---|---|
| `readbackSeed` | integer，确定性 Canvas/WebGL/Audio 微扰 |
| `canvasDataReplay` | base64 RGBA byte strings |
| `canvasUrlReplay` | 完整 data URL strings |
| `canvasBlobReplay` | base64 encoded-image byte strings |
| `glReadReplay` | base64 RGBA byte strings |
| `audioReplay` | base64 little-endian float32 strings |
| `analyserFloatReplay` | base64 float32 strings |
| `analyserByteReplay` | base64 byte strings |

所有 replay 字段都是数组，按调用序取值并循环。优先级为：

```text
fixed replay > readbackSeed noise > native
```

`*Replay` 没有采集数据就不要传。

### BC 能力描述与原生 PDF 面

以下字段可由 BC Profile 序列化，但当前不是 Chromium renderer override：

| 字段 | 状态 |
|---|---|
| `productCapabilities` | BC 自洽元数据，浏览器内核忽略 |
| `plugins` / `mimeTypes` / `pdfViewerEnabled` | 画像元数据；桌面不传走原生 5 PDF。Android/iOS 缺省空插件、`pdfViewerEnabled=true` |
| `keyboard` / `connection` | Android 缺省隐藏 keyboard；connection 可删或覆盖 effectiveType/downlink/rtt |

现代 Chromium 原生暴露固定 5 个 PDF compatibility plugins、2 个 PDF MIME types。不要把上述元数据误认为本命令已经覆盖这些对象。

### 完整示例

```json
{
  "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7907.0 Safari/537.36",
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
  "platform": "Win32",
  "platformVersion": "15.0.0",
  "architecture": "x86",
  "model": "",
  "mobile": false,
  "bitness": "64",
  "wow64": false,
  "formFactors": ["Desktop"],
  "hardwareConcurrency": 8,
  "deviceMemory": 8,
  "acceptLanguages": "en-US,en;q=0.9",
  "locale": "en-US",
  "timezone": "America/New_York",
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
  "viewportHeight": 954,
  "webRTC": 1,
  "webRTCPublicIP": "203.0.113.7",
  "webglVendor": "Google Inc. (NVIDIA)",
  "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
  "webglExtensions": [
    "ANGLE_instanced_arrays",
    "EXT_texture_filter_anisotropic",
    "WEBGL_debug_renderer_info"
  ],
  "webgl2Extensions": [
    "EXT_color_buffer_float",
    "EXT_texture_filter_anisotropic",
    "WEBGL_debug_renderer_info"
  ],
  "webglParameters": {
    "3379": {"type": "int", "value": 16384}
  },
  "webgl2Parameters": {
    "3379": {"type": "int", "value": 16384},
    "36183": {"type": "int", "value": 4}
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
      "name": "Microsoft Zira",
      "lang": "en-US",
      "voiceURI": "Microsoft Zira",
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
      "video/webm; codecs=\"vp8\"": "probably"
    },
    "mediaSource": [
      "video/webm; codecs=\"vp8\""
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
    {
      "kind": "audioinput",
      "deviceId": "default",
      "groupId": "",
      "label": ""
    }
  ],
  "readbackSeed": 77777,
  "canvasDataReplay": ["<base64 RGBA bytes>"],
  "canvasUrlReplay": ["<complete data:image/... URL>"],
  "canvasBlobReplay": ["<base64 encoded image bytes>"],
  "glReadReplay": ["<base64 RGBA bytes>"],
  "audioReplay": ["<base64 little-endian float32 samples>"],
  "analyserFloatReplay": ["<base64 float32 samples>"],
  "analyserByteReplay": ["<base64 bytes>"],
  "referrer": ""
}
```
