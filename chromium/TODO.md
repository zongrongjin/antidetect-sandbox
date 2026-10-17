# TODO：跨设备指纹一致性

目标：在单个 Chromium 进程中按 BrowserContext 切换设备画像，并保证各可观察 API
之间自洽。这里不重复已经完成的 UA/UA-CH、语言、时区、屏幕、触摸、WebRTC、
Canvas/WebGL/Audio readback 等覆盖。

## P0：字体画像与排版一致性

- [x] 在 fingerprint JSON 中增加 per-context 字体列表（`fontFamilies`）。
- [ ] 覆盖字体可用性查询：
  - [x] `document.fonts.check()`
  - [x] `FontFaceSet`
  - Local Font Access API（可用时）
- [x] `fontAliases` 在真实字体选择层生效，因此 Canvas `measureText()` /
  `TextMetrics`、DOM 元素宽高/换行与 `Range.getClientRects()` 共用同一字体。
- [x] system-ui / serif / sans-serif / monospace 在主线程与 worker 中按 context 映射。
- [ ] 安装或随包提供各目标平台的真实字体文件，并补齐精确 emoji fallback。
- [ ] 为 Windows、macOS、Linux、Android 建立版本化字体画像。
- [x] dedicated worker / OffscreenCanvas 与主页面字体结果一致。
- [ ] 补齐同源 iframe、跨源 OOPIF、shared worker、service worker 的自动化矩阵。

> Canvas 最终 readback spoof 不能替代字体覆盖：字体可用性、文字度量和 DOM 排版在
> 生成像素之前就可以被读取。

## P0：WebGL 能力向量与 WebGPU

- [ ] 扩充 WebGL1/WebGL2 的 per-context capability profile：
  - `getParameter()` limits
  - texture/renderbuffer/viewport/uniform/vector limits
  - aliased line/point ranges
  - compressed texture formats
- [x] 覆盖 `getShaderPrecisionFormat()`。
- [x] 确保扩展列表、扩展对象和实际调用行为一致（画像列表与原生支持集取交集）。
- [ ] 校验 WebGL1/WebGL2、vendor/renderer、limits、extensions 之间的 GPU 型号自洽。
- [x] 增加 WebGPU per-context 覆盖（字段缺失原生回退）：
  - `navigator.gpu`
  - adapter info
  - features
  - limits
  - preferred canvas format
- [ ] 为常见 NVIDIA、AMD、Intel、Apple、Android GPU 建立成套能力画像。

## P0：Speech Synthesis

- [x] 增加 per-context speech voice profile。
- [x] 覆盖 `speechSynthesis.getVoices()` 返回的：
  - `name`
  - `lang`
  - `voiceURI`
  - `localService`
  - `default`
- [ ] 模拟真实的 voice 顺序与 `voiceschanged` 触发时序。
- [ ] 为 Windows、macOS、Linux、Android 维护与 locale 对应的 voice 集合。
- [ ] 验证 iframe/OOPIF 下结果与主页面一致。

## P1：媒体与外设能力

- [x] `canPlayType()`、MSE 与 `MediaCapabilities.decodingInfo()` 共用 exact-content-type
  画像；字段缺失或 DRM/keySystem 查询保持原生。
- [x] `mediaDevices.enumerateDevices()` 支持 per-context 预授权视图。
- [ ] 核对音频输出、摄像头、麦克风权限前后的返回差异。
- [x] 核对现代 Chromium 固定 5 个 PDF plugin、2 个 PDF MIME type 和
  `pdfViewerEnabled`；保持原生实现。

## P1：窗口、系统 UI 与 CSS 媒体特性

- [x] `outerWidth/outerHeight` 可按 context 覆盖；BC 同时用
  `Emulation.setDeviceMetricsOverride` 同步 viewport/DPR。
- [ ] 覆盖或约束滚动条宽度、系统控件、系统颜色和 emoji 渲染。
- [x] 按 context 覆盖并验证以下媒体特性：
  - `color-gamut`
  - HDR / dynamic range
  - `forced-colors`
  - `prefers-contrast`
  - `prefers-reduced-motion`
- [x] Android viewport 由 BC 的 device metrics 与画像同步。
- [ ] Android 虚拟键盘与传感器行为仍需真机数据和硬件事件验证。

## P1：网络与产品能力一致性

- [ ] 校验 TLS、HTTP/2、HTTP/3/QUIC 与 Chromium/UA 版本匹配。
- [ ] 校验 Chrome、Edge、Chromium 品牌画像与实际产品能力：
  - codecs
  - [x] codecs、PDF viewer
  - [x] BC 在魔改 Chromium profile 启动前从显式目录或已安装 Chrome/Edge
    自动复制 WidevineCdm；不公开分发专有 CDM。
  - [ ] 在有 DRM 授权链的环境验证 Widevine license/session 行为。
  - component availability
  - Chrome/Edge 专属对象与行为
- [ ] 确认 context 代理、WebRTC 公网 IP、语言和时区属于同一地域画像。

## P2：真实数据与硬件行为

- [ ] 采集 Windows/macOS/Ubuntu 24.04/Android 真机的字体文件版本、字体 metrics、
  emoji fallback、GPU limits/extensions/WebGPU adapter 和 speech 时序。
- [ ] 在带摄像头、麦克风、音频输出、HDR 显示器和传感器的机器验证权限状态迁移。
- [ ] 在授权的真实 STUN、HTTP/3/QUIC、Widevine 环境验证网络与 DRM 出口。
- [ ] 将真机采集结果版本化，按 OS/浏览器/GPU/设备族绑定，不能拆字段随机拼接。

## 验收

- [ ] 每个维度都验证主页面、同源/跨源 iframe、OOPIF 和三种 worker。
- [ ] 同一画像跨重启结果稳定；不同 context 之间无数据串扰。
- [ ] Windows/macOS/Linux/Android 画像分别与对应真机采集结果对比。
- [ ] 增加自动化一致性测试，检查跨 API 矛盾，而不只比较最终 hash。
- [x] 缺少画像字段时必须干净回退原生行为，不能产生半覆盖状态。

## 2026-07 P0 实现说明

- 补丁：`patches/fp_p0_capabilities.diff`。
- WebGL limits、shader precision、扩展对象一致性，字体可用性和 speech voices 已通过
  三个 BrowserContext（A/B/原生）运行验证，A 在 B 创建后复读不变。
- WebGPU 已在 Windows RDP 交互会话用 Microsoft WARP adapter 完整运行验证：
  A/B/原生三个 BrowserContext 的 adapter info、features、limits、
  `preferredCanvasFormat` 均正确隔离，A 在 B 创建后复读不变。无 GPU 节点应使用
  `--enable-unsafe-webgpu --ignore-gpu-blocklist`，不能强制
  `--use-webgpu-adapter=swiftshader` + Vulkan；后者在该环境会把 WebGPU 标记为
  `unavailable_software`。
- WebGPU features 只暴露“画像期望 ∩ 底层真实支持”，limits 只向更保守方向收敛，
  避免 `requestDevice()` 与可见能力矛盾。
- 字体查询之后已在 follow-up 中补到实际字体选择层；Local Font Access、精确 emoji
  fallback 和目标平台真实字体文件仍未完成。

## 2026-07 一致性 follow-up

- `patches/fp_full.diff` 已从最终编译源码重新导出，是构建时唯一需要应用的 Chromium
  主仓补丁；`fp_p0_capabilities.diff` 和 `fp_consistency_followup.diff` 仅保留作审计。
- 字体别名已移到真实字体选择层，并覆盖 worker OffscreenCanvas；Canvas、DOM、Range
  会自然走同一字体。缺少目标平台真实字体文件时仍不等于真实设备 metrics。
- 新增 per-context outer window、CSS media、media codec/MSE/decodingInfo 和
  mediaDevices 读取点。
- Windows x64 增量编译通过。A/B/原生三 context 验证覆盖字体、worker、speech、
  outer/CSS、codec/MSE/MediaCapabilities、mediaDevices、WebGL 和 WebRTC policy=0；
  A 在 B 创建后复读不变，原生 context 干净回退。
- SSH/headless 会话没有 WebGPU adapter，但 `preferredCanvasFormat` 隔离正常；adapter
  完整矩阵已在此前 RDP/WARP 交互会话验证。
