# `moz:context.setContextOverrides` 完整字段契约

本文档描述 Firefox zzbrowser `152.0.5` 当前实现实际接受的画像 JSON。机器可读版本见
[`schemas/fingerprint.schema.json`](../schemas/fingerprint.schema.json)。

## 调用外壳

BiDi 扩展命令的 `fingerprint` 参数是 JSON **字符串**，另用 `userContexts` 指定作用域：

```python
profile = {
    "userAgent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
        "Gecko/20100101 Firefox/152.0"
    ),
    "platform": "Win32",
    "oscpu": "Windows NT 10.0; Win64; x64",
    "fontFamilies": ["Arial", "Segoe UI"],
    "fontAliases": {"system-ui": "Segoe UI"},
}

bidi.call("moz:context.setContextOverrides", {
    "fingerprint": json.dumps(profile, separators=(",", ":")),
    "userContexts": [user_context_id],
})
```

等价 wire message：

```json
{
  "id": 1,
  "method": "moz:context.setContextOverrides",
  "params": {
    "fingerprint": "{\"platform\":\"Win32\",\"oscpu\":\"Windows NT 10.0; Win64; x64\"}",
    "userContexts": ["<user-context-id>"]
  }
}
```

画像存储在 `BrowsingContext` synced field，并按 userContext 传播到之后创建的页面、远程
子框架和 worker snapshot。所有字段均可选；字段缺失、类型不符或对应子键未命中时，相关
读取点回退 Firefox 原生行为。

## 支持层级

- **内核直接消费**：只调用 `moz:context.setContextOverrides` 即可生效。
- **内核 + BC**：内核读取画像，同时 BC 另发 BiDi/window 命令同步实际窗口和 viewport。
- **BC-only**：共享 `Fingerprint` 契约会序列化，但不是本命令的读取点。
- **能力描述 / 原生**：用于 BC 自洽检查；Firefox 保持原生 API。
- **共享契约未实现**：BC 可以携带，但当前 Firefox 补丁明确不消费。

## Firefox 身份、语言与硬件

| 字段 | 类型 | 层级 | 行为 |
|---|---|---|---|
| `userAgent` | string | 内核 | `navigator.userAgent`、请求与 worker |
| `platform` | string | 内核 | `navigator.platform` |
| `oscpu` | string | 内核 | `navigator.oscpu` |
| `appVersion` | string | 内核 | `navigator.appVersion` |
| `acceptLanguages` | string | 内核 | `navigator.language(s)` 与请求头；JS 数组自动剥 q 值 |
| `locale` | string | 内核 | Intl locale 与 BrowsingContext locale override |
| `timezone` | string | 内核 | Intl IANA timezone 与 BrowsingContext timezone override |
| `hardwareConcurrency` | integer ≥ 1 | 内核 | window 与 worker |
| `referrer` | string | 内核 | 顶层文档 `document.referrer` |

Firefox 不接受也不应传：

- `uaPlatform`
- `uaBrands` / `uaFullBrands` / `uaFullVersion`
- `platformVersion` / `architecture` / `model` / `mobile` / `bitness` / `wow64`
- `deviceMemory`

真实 Firefox 没有 UA-CH 和 `navigator.userAgentData`，也没有
`navigator.deviceMemory`。为这些 API 造返回值反而会成为特征。

## 屏幕、窗口与输入

| 字段 | 类型 | 层级 | 行为 |
|---|---|---|---|
| `screenWidth` / `screenHeight` | integer ≥ 0 | 内核 | `screen.width/height` |
| `availWidth` / `availHeight` | integer ≥ 0 | 内核 | screen 可用区域 |
| `availLeft` / `availTop` | integer | 内核 | screen 可用区偏移 |
| `colorDepth` | integer > 0 | 内核 | `colorDepth` 与 `pixelDepth` |
| `dpr` | number > 0 | 内核 + BC | `devicePixelRatio` 与 CSS `(resolution)` / `(-moz-device-pixel-ratio)`，经 `overrideDPPX`；缺 presContext 时也从画像回退 |
| `maxTouchPoints` | integer ≥ 0 | 内核 | maxTouchPoints、TouchEvents、pointer/hover、orientation |
| `outerWidth` / `outerHeight` | integer ≥ 0 | 内核 + BC | JS 属性由内核覆盖，BC 同步真实窗口 bounds |
| `viewportWidth` / `viewportHeight` | integer ≥ 0 | BC-only | BC 另发 `browsingContext.setViewport` |

只手动发画像不会改变实际 layout viewport。需要另外发送：

```json
{
  "method": "browsingContext.setViewport",
  "params": {
    "context": "<top-browsing-context-id>",
    "viewport": {
      "width": 1280,
      "height": 634
    }
  }
}
```

BC `new_context(fingerprint=...)` 会同步 outer bounds 和 viewport。

## WebRTC 与 context 代理

| 字段 | 类型 | 行为 |
|---|---|---|
| `webRTC` | `0 / 1 / 2` | 映射到 per-context `NrIceCtx::Policy` |
| `webRTCPublicIP` | string | 在 nICEr srflx candidate 生成路径覆盖公网地址 |

策略含义：

- `0`：禁止非代理 UDP；本地测试不产生 host/srflx candidate。
- `1`：默认路由，保留 mDNS host，STUN 可达时产生 srflx。
- `2`：仅默认路由，隐藏 host。

`webRTC=0` 下没有 srflx，因此 `webRTCPublicIP` 不会生效。公网覆盖需在授权 STUN
环境验证 candidate、SDP、`.address` 和 `getStats()`。

代理、缓存、假页、cookie 都不是 fingerprint JSON 字段。走同一条
`moz:context.setContextOverrides`：

```json
{
  "method": "moz:context.setContextOverrides",
  "params": {
    "fingerprint": "<json string>",
    "proxy": {"endpoint": "host:port", "username": "", "password": ""},
    "cache": {"dir": "/abs/cache", "map": "{}", "rules": "{}"},
    "cookies": [{"name": "a", "value": "b", "domain": "example.com", "path": "/"}],
    "url": "https://example.com/",
    "html": "<!doctype html><html>...</html>",
    "userContexts": ["<user-context-id>"]
  }
}
```

`cache.map` / `cache.rules` 是 JSON **字符串**，匹配顺序与 Chromium 相同：
captures > callbacks > HIT > blocks > allow-miss > observe > pass。
HIT 与 `url`+`html` 假首页用 `nsIReplacedHttpResponse`，状态行固定 `HTTP/1.1`，不发网。
`headersList` 不做（Firefox 请求头本就是发出顺序）。`canvasBlobReplay` 不做。

## WebGL

| 字段 | 类型 | 行为 |
|---|---|---|
| `webglVendor` / `webglRenderer` | string | masked/unmasked 可见身份按 Firefox 路径覆盖 |
| `webglExtensions` | string[] | WebGL1 期望扩展 |
| `webgl2Extensions` | string[] | WebGL2 期望扩展 |
| `webglParameters` | parameter map | WebGL1 `getParameter()` |
| `webgl2Parameters` | parameter map | WebGL2 `getParameter()` |
| `webglShaderPrecision` | precision map | WebGL1 shader precision |
| `webgl2ShaderPrecision` | precision map | WebGL2 shader precision |

parameter map 的键是十进制 GLenum：

```json
{
  "webglParameters": {
    "3379": {"type": "int", "value": 16384},
    "33901": {"type": "float32", "value": [1, 1024]},
    "37445": {"type": "string", "value": "Mozilla"}
  }
}
```

支持的 typed value：

| type | value |
|---|---|
| `bool` | boolean |
| `int` | integer |
| `uint` | non-negative integer |
| `float` | number |
| `string` | string |
| `int32` | integer[] |
| `float32` | number[] |

shader precision 键为 `shaderType:precisionType`，值为
`[rangeMin, rangeMax, precision]`：

```json
{
  "webgl2ShaderPrecision": {
    "35632:36338": [127, 127, 23]
  }
}
```

扩展画像按 WebGL1/2 分开；缺字段时各自原生回退。不能用一套数组同时冒充 WebGL1 和
WebGL2。

## WebGPU

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

- adapter 缺少的字段保持真实值。
- features 取画像与真实支持集的交集。
- limits 只允许向更保守方向收敛。
- 无真实 WebGPU adapter 时不能靠画像创建 adapter。
- SSH/headless 软件渲染环境可能只有 `preferredCanvasFormat` 可验证。

## 字体与 Speech

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
      "voiceURI": "urn:fp:Microsoft Zira",
      "localService": true,
      "default": true
    }
  ]
}
```

- `fontFamilies` 控制字体可用性查询。
- `fontAliases` 进入 Gecko 实际字体选择层。
- document、DOM/Range、Canvas/TextMetrics 与 worker OffscreenCanvas 使用同一结果。
- 名称映射不等于节点已有目标字体文件；真实 metrics 仍需要字体包。
- `speechVoices` 覆盖五个 voice 字段，不模拟真实 `voiceschanged` 时序。

## CSS 媒体特性

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

## 媒体能力与设备

```json
{
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
  ]
}
```

- content type 是 exact string key；未命中时回退原生。
- `mediaSource` 是严格允许列表，空数组表示全部不支持。
- decodingInfo 合并 audio/video 结果，DRM/keySystem 查询保持原生。
- `mediaDevices` 只覆盖 `enumerateDevices()` 的预授权视图。
- 不伪造 `getUserMedia()` 成功、权限状态或实际摄像头/麦克风。

## 读回噪声与固定回放

| 字段 | 当前 Firefox 行为 |
|---|---|
| `readbackSeed` | Canvas/WebGL/Audio 确定性微扰 |
| `canvasDataReplay` | base64 RGBA bytes，已实现 |
| `canvasUrlReplay` | 完整 data URL，已实现 |
| `canvasBlobReplay` | **共享 BC 契约字段，当前 Firefox 未实现** |
| `glReadReplay` | base64 RGBA bytes，已实现 |
| `audioReplay` | base64 little-endian float32，已实现 |
| `analyserFloatReplay` | base64 float32，已实现 |
| `analyserByteReplay` | base64 bytes，已实现 |

replay 字段是字符串数组，按调用顺序取值并循环。已实现读取点的优先级：

```text
fixed replay > readbackSeed noise > native
```

## BC 能力描述、android-surface 与原生 PDF 面

以下字段可由共享 BC Profile 序列化。android-surface 之后，plugins /
pdfViewerEnabled / connection 已是内核读取点：

| 字段 | 状态 |
|---|---|
| `viewportWidth` / `viewportHeight` | BC 通过 BiDi `setViewport` 应用 |
| `productCapabilities` | BC 自洽元数据，Firefox 内核忽略 |
| `plugins` / `mimeTypes` | **内核**：空数组或 Android/iOS UA → length 0；非空列表仍走原生 5 PDF / 2 MIME |
| `pdfViewerEnabled` | **内核**：显式优先；Android/iOS 缺省 true |
| `keyboard` | 真 Firefox 无 Keyboard API；键忽略 |
| `connection` | **内核**：false / iOS 隐藏属性；对象或 Android UA 露出 `navigator.connection.type` |
| `canvasBlobReplay` | 共享契约保留，当前 Firefox 未实现 |

桌面画像不传 plugins/connection 时保持现代 Firefox 原生：5 PDF plugins、2 MIME types、`pdfViewerEnabled=true`、无 `navigator.connection`、无 `navigator.keyboard`。

## 完整示例

```json
{
  "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
  "platform": "Win32",
  "oscpu": "Windows NT 10.0; Win64; x64",
  "appVersion": "5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
  "hardwareConcurrency": 8,
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
  "webglVendor": "Mozilla",
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
      "voiceURI": "urn:fp:Microsoft Zira",
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
  "glReadReplay": ["<base64 RGBA bytes>"],
  "audioReplay": ["<base64 little-endian float32 samples>"],
  "analyserFloatReplay": ["<base64 float32 samples>"],
  "analyserByteReplay": ["<base64 bytes>"],
  "referrer": ""
}
```

## 清除与更新

再次调用会替换目标 userContext 的完整画像，不做深度合并。恢复原生行为：

```json
{
  "fingerprint": "{}",
  "userContexts": ["<user-context-id>"]
}
```

只更新单个字段时，应由调用方先在本地合并完整画像，再重新发送。
