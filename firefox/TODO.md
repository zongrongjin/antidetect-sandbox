# TODO：跨设备指纹一致性

目标：在单个 Firefox 进程中按 userContext / BrowsingContext 切换设备画像，并保证
各可观察 API 之间自洽。这里不重复已经完成的 UA、platform、oscpu、语言、时区、
屏幕、触摸、WebRTC 公网 IP、Canvas/WebGL/Audio readback 和 per-context 代理。

## P0：字体画像与排版一致性

- [x] 在 fingerprint JSON 中增加 per-context 字体列表（`fontFamilies`）。
- [ ] 覆盖字体可用性查询：
  - [x] `document.fonts.check()`
  - [x] `FontFaceSet`
  - Local Font Access API（可用时）
- [x] `fontAliases` 在 Gecko 实际字体选择层生效，因此 Canvas `measureText()` /
  `TextMetrics`、DOM 排版和 `Range.getClientRects()` 共用同一字体。
- [x] system-ui / serif / sans-serif / monospace 覆盖 document 与 worker
  OffscreenCanvas。
- [ ] 安装或随包提供目标平台真实字体文件，并补齐精确 emoji fallback。
- [ ] 为 Windows、macOS、Linux、Android 建立版本化字体画像。
- [x] dedicated worker / OffscreenCanvas 与主页面字体结果一致。
- [ ] 补齐同源/跨源 iframe、远程子框架、shared worker、service worker 自动化矩阵。

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

## P0：WebRTC 路由策略

- [x] 在 fingerprint JSON 中增加 `webRTC` 策略字段。
- [x] 将策略映射到 Firefox 已有的 `NrIceCtx::Policy`：
  - `0`：禁止非代理 UDP，不产生 candidate
  - `1`：默认行为，保留 host(mDNS) + srflx
  - `2`：仅默认路由，隐藏 host candidate
- [ ] 明确 `webRTC` 与 `webRTCPublicIP` 的组合规则。
- [ ] 验证 candidate 字符串、SDP、`.address` 与 `getStats()` 的结果一致。
- [ ] 验证策略与 per-context 上游代理之间不串扰。

## P1：媒体与外设能力

- [x] `canPlayType()`、MSE 与 `MediaCapabilities.decodingInfo()` 共用
  exact-content-type 画像；DRM/keySystem 查询保持原生。
- [ ] 核对 Widevine/EME 的可用性和错误行为。
- [x] `mediaDevices.enumerateDevices()` 支持 per-context 预授权视图，且显式画像不再被
  后台 focus gate 卡住。
- [ ] 核对音频输出、摄像头、麦克风权限前后的返回差异。
- [x] 核对现代 Firefox 原生固定 5 个 PDF plugin、2 个 PDF MIME type 和
  `pdfViewerEnabled`；不额外注入旧 NPAPI 数据。
- [x] android-surface：空 `plugins`/`mimeTypes`、Android/iOS `pdfViewerEnabled=true`、
  按画像露出或隐藏 `navigator.connection`（`wip/android-surface`）。

## P1：窗口、系统 UI 与 CSS 媒体特性

- [x] `outerWidth/outerHeight` 按 BrowsingContext 覆盖；BC 用
  `browsingContext.setViewport` 同步 viewport/DPR。
- [ ] 覆盖或约束滚动条宽度、系统控件、系统颜色和 emoji 渲染。
- [x] 按 context 覆盖并验证以下媒体特性：
  - `color-gamut`
  - HDR / dynamic range
  - `forced-colors`
  - `prefers-contrast`
  - `prefers-reduced-motion`
- [x] Android viewport 由 BC 的 BiDi viewport 与画像同步。
- [ ] GeckoView/桌面 Firefox 的产品差异、虚拟键盘和传感器仍需真机数据。
- [ ] 在真实 152.0.5 树上编译并跑 `scripts/verify_android_surface.py`。

## P1：网络与产品能力一致性

- [ ] 校验 TLS、HTTP/2、HTTP/3/QUIC 与 Firefox/UA 版本匹配。
- [ ] 校验桌面 Firefox 与 Android GeckoView 的产品能力差异。
- [ ] 确认 context 代理、WebRTC 公网 IP、语言和时区属于同一地域画像。
- [ ] 核对 WebAuthn、Credential API、权限 API 等硬件相关能力的返回形态。

## P2：真实数据与硬件行为

- [ ] 采集 Windows/macOS/Ubuntu 24.04/Android 真机的字体文件版本、字体 metrics、
  emoji fallback、GPU/WebGPU 能力和 speech `voiceschanged` 时序。
- [ ] 在真实摄像头、麦克风、音频输出、HDR 显示器和传感器环境验证权限迁移。
- [ ] 在授权的真实 STUN/代理组合验证 srflx candidate、SDP、`.address`、`getStats()`。
- [ ] 单独采集 Android GeckoView 产品面；桌面 Firefox 改 UA 不能自动变成 GeckoView。

## Firefox 边界

- [ ] 不实现 UA-CH：真实 Firefox 不发送 `sec-ch-ua`，也没有
  `navigator.userAgentData`。
- [ ] 不实现 `navigator.deviceMemory`：真实 Firefox 没有该 API。
- [ ] 保持 `oscpu`、`appVersion`、UA、platform 和设备类别自洽。
- [x] 所有新增覆盖必须保持纯净启动零影响：字段缺失时回退 Firefox 原生行为。

## 2026-07 P0 实现说明

- 补丁：`patches/fp_p0_capabilities.diff`。
- 字体可用性、speech voices、WebGL limits/shader precision 和原生回退已通过两个
  userContext + 一个原生 context 的 BiDi 运行验证，且 A 在 B 创建后复读不变。
- Windows 无硬件 GPU/RDP 节点在 profile 写入 `webgl.force-enabled=true`、
  `gfx.webrender.software=true`、`webgl.angle.force-warp=true` 后，WebGL1/WebGL2
  均已完整运行验证；A/B 的 limits 与 shader precision 独立，原生 context 回退
  WARP 值，A 在 B 创建后复读不变。
- `webRTC=0/1/2` 已沿 IPC 透传到 `NrIceCtx::Policy`，本地无 STUN 验证结果分别为：
  0 无 host/srflx、1 有 mDNS host、2 隐藏 host。公网 srflx 与代理组合仍需在明确
  授权的 STUN 测试环境验证。
- WebGPU 的 context 隔离和 `preferredCanvasFormat` 已运行验证；当前 SSH/headless
  构建机拿不到 adapter，因此 adapter info/features/limits 完成增量编译验证，仍需
  在有可用 GPU 的交互会话复测。
- WebGPU features 只保留画像与底层支持集的交集，limits 只向更保守方向收敛。
- 实际字体选择、Canvas/DOM metrics 已在 follow-up 中完成；Local Font Access、精确
  emoji fallback 和目标平台真实字体文件尚未实现。

## 2026-07 一致性 follow-up

- `patches/fp_all.diff` 已从官方 pristine tarball 与最终编译源码重新生成，是构建时唯一
  需要应用的补丁；`fp_p0_capabilities.diff` 和 `fp_consistency_followup.diff` 仅作审计。
- 字体别名已进入 Gecko 实际字体选择层，并通过 `FontVisibilityProvider` 覆盖 document
  与 worker OffscreenCanvas；缺真实目标字体文件时仍不能冒充真实 metrics 数据库。
- 新增 outer window、CSS media（含 forced-colors）、codec/MSE/decodingInfo 和
  mediaDevices 的 per-context 覆盖。
- Windows x64 两轮增量编译均为 0 warning。A/B/原生 BiDi 矩阵覆盖字体、worker、
  speech、outer/CSS、codec/MSE/MediaCapabilities、mediaDevices、WebGL1/2；
  A 在 B 创建后复读不变，原生 context 干净回退。
- WebRTC `0/1/2` 本地策略回归通过；公网 srflx 与代理组合保留给授权 STUN 环境。

## 验收

- [ ] 每个维度都验证主页面、同源/跨源 iframe、OOPIF 和三种 worker。
- [ ] 同一画像跨重启结果稳定；不同 userContext 之间无数据串扰。
- [ ] Windows/macOS/Linux/Android 画像分别与对应真机采集结果对比。
- [ ] 增加自动化一致性测试，检查跨 API 矛盾，而不只比较最终 hash。
- [ ] 分开验证桌面 Firefox 画像切换与桌面 Firefox → Android 画像切换。
- [ ] 缺少画像字段时必须干净回退原生行为，不能产生半覆盖状态。
