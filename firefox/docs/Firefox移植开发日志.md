# Firefox(Gecko) 指纹魔改移植 —— 开发日志

> 姊妹工程：Chromium 版已完成（`docs/开发文档/` 里的设计基线 / 实施 Plan / 补丁）。本文记录 Firefox 152 侧从零移植的进度。
> 方案全文见 `plan/移植方案.md`。

---

## 2026-07-13　P0 环境搭建（进行中）

### 前期调研结论（Phase 1，三路并行 + 云机只读侦察）
1. **传输载体**：Gecko 有等价于 Chromium `RendererPreferences` 的机制 —— **BrowsingContext synced field**（`docshell/base/BrowsingContext.h` 的 `MOZ_EACH_BC_FIELD`/`FIELD` 宏，parent 设、IPC 自动同步到所有 content 进程含跨源 OOPIF）。Playwright 的 Firefox patch 已证「加自定义 synced 字段承载覆盖值」可行。计划加 `FIELD(FingerprintProfile, nsString)`（JSON blob）。
2. **BiDi 可扩展**：命令 = JS 模块公有方法，root 模块跑 parent 进程有完整 chrome 特权。**已有 `emulation` 模块**（`setUserAgentOverride`/`setLocaleOverride`/`setTimezoneOverride`/`setScreenSettingsOverride`），Firefox 版 `moz:fingerprint` 模块 ≈ 照抄它 + 加维度。注册在 `ModuleRegistry.sys.mjs` 的 `moz` 命名空间 + `remote/jar.mn`。
3. **RFP 复用策略**：`nsRFPService` 已把绝大多数读取点选好址，但其值是固定 canonical + 每会话不可控随机（无 seed/replay/per-context）→ **复用选址、不复用值/随机化，自建注入层**（~15-20 处读取点）。
4. **replay 契约**：云机 `~/chromium/src` 完整实现了 7 个读回点（`//BROWSER_FINGERPRINT` 标记），值编码 = JSON 数组、按调用序取模回放：`canvasDataReplay`(RGBA)/`canvasUrlReplay`(dataURL)/`canvasBlobReplay`(base64)/`glReadReplay`(base64 RGBA)/`audioReplay`(采样)/`analyserFloat/ByteReplay`。Firefox 侧 1:1 镜像。

### 范围决策
- **丢弃 UA-CH**：真实 Firefox 152 不发 `sec-ch-ua`、无 `navigator.userAgentData`（Chromium 专属），发这些反而是破绽。画像不含 `uaBrands/uaFullBrands/uaPlatform`。
- **v1 含 replay**：读回面做全三态（replay > noise > native）。

### 环境落地
- **版本/取源**：Firefox **152.0.5**（当前 stable，UA `rv:152.0`）。gecko-dev git 无 release tag → 用官方 source tarball `ftp.mozilla.org/pub/firefox/releases/152.0.5/source/firefox-152.0.5.source.tar.xz`（800,076,384 字节）。
- **构建机**：内部 Linux 构建机（32核/61G/228G 空闲盘/Ubuntu 22.04），代理 mihomo `127.0.0.1:7890`。源码解压到 `~/firefox-152.0.5`。**注意** 另有一个 Chrome 发布构建在 `~/chromium/src/out/Release` 跑（别动），FF 重度编译需等它让核。
- **进度**：
  - ✅ tarball 下载（代理满速 ~33s）+ 解压。
  - ✅ `./mach --no-interactive bootstrap --application-choice browser`（装 watchman + Rust 到 `~/.cargo/bin`，~6 分钟）。
  - ✅ release mozconfig（`--enable-release` + `MOZILLA_OFFICIAL=1` + objdir `obj-release`）。
  - ⏳ stock `./mach build`：排队等 Chrome 让出 32 核（`p0_build.sh` 自动 gate；**已修坑**：bootstrap 的 Rust 装在 `~/.cargo/bin`，构建脚本须 `source ~/.cargo/env` 上 PATH，否则 `./mach build` 报 "Could not find a Rust compiler"）。

### 152.0.5 源码锚点核对（研究是对 mozilla-central tip 做的，已核对 152 存在）
- BiDi：`remote/webdriver-bidi/modules/root/emulation.sys.mjs`（setUserAgentOverride≈L629 等）、`ModuleRegistry.sys.mjs`（`root/windowglobal/windowglobal-in-root` 各有 `moz:{}` 命名空间）。
- BC：`BrowsingContext.h` `MOZ_EACH_BC_FIELD`(L118)、`FIELD(UserAgentOverride,nsString)`(L217)、`FIELD(PlatformOverride,nsString)`(L237)、`MOZ_DECL_SYNCED_CONTEXT`(L325)；`BrowsingContext.webidl` chrome-only `customPlatform`/`customUserAgent`/`languageOverride`/`timezoneOverride`。
- 读取点：`Navigator::GetPlatform`(L433/L2031)/`Webdriver`(L2352)/`GetOscpu`(L458)/`HardwareConcurrency`(L698)/`GetUserAgent`(L271/L2113)/`GetLanguages`(L413)；`Document::HasFocus`(L4730)/`UpdateVisibilityState`(L17161)；`Element.webidl openOrClosedShadowRoot`(L296)；`CanvasRenderingContext2D::GetImageBuffer`(L2261)+`RandomizePixels`(L2291/L6713)。
- 漂移：`dom/base/Screen.cpp` 路径变了（P2 时定位）。

### 同步/协作拓扑
- 本仓 `firefox_zzbrowser` 推送点在**本机 Windows**（github SSH 认证 OK）。云机能连 github:22 但没注册公钥（`Permission denied`），暂不能直接推 → 云机开发的补丁 scp/导出到本机再提交。
- 计划：P1 起 `git init` 云机 Gecko 树（`.gitignore` 排除 `obj-release`），用 `git diff` 导出 `fp_full.diff`（同 Chromium 工作流），存本仓 `patches/`。

### P1 实现规格已就绪（详见 `docs/P1实现规格.md`）
读全 152 源码后产出精确 file:line 规格，10 文件最小改动集：
- **BC 字段**：`BrowsingContext.h` 加 `FIELD(FingerprintProfile,nsString)`（L237 后）；照抄 `PlatformOverride` 的 CanSet(只许 top+parent)/DidSet(清 platform 缓存)/Set；加 chrome-only WebIDL `customFingerprint`(L123 后)。
- **BiDi**：新建 `root/moz/fingerprint.sys.mjs`(RootBiDiModule 子类) + 注册 `ModuleRegistry`/`webdriver-bidi/jar.mn` + `emulation.sys.mjs` 加导出 `setFingerprintProfileForBrowsingContext` + `_configuration.sys.mjs` 挂 `fingerprint-override` category(4 处)。走 SessionData 覆盖未来上下文。
- **读取点**：`Navigator::GetPlatform`(WebIDL 版 L433) 读 `bc->Top()->GetFingerprintProfile()`，`JS_ParseJSON`+`AutoJSAPI` 抽 platform 键。`[Cached]` 缓存靠 DidSet→`ClearCachedPlatform` 失效(复用现成链)。
- **关键结论**：顶层 BC 设一次，跨进程 OOPIF 自动继承（synced 机制 + 读 `Top()`）；顶层进程切换建议在 `CanonicalBrowsingContext::ReplacedBy` L321 旁补 `txn.SetFingerprintProfile(...)`。

### 协作
仓库 `firefox_zzbrowser` 初始脚手架已推送 `main`（README + 方案 + 开发文档归档 + P0 脚本 + P1 规格）。

### P0 构建环境攻坚（tarball 编 FF152 的工具链坑，已解，配方见 `scripts/p0_setup_env.sh`）
stock build 一开始连续 configure 失败，逐个啃下来：
1. **`Cannot find llvm-objdump` + 用了系统 g++**：tarball 非 VCS，`mach bootstrap` 只装 rust+watchman、没拉 Mozilla clang 工具链；`--enable-bootstrap`（靠 taskcluster revision）对 tarball 也拉不动。
2. **clang 版本**：FF152 要 clang≥17（`toolchain.configure:1494`），Ubuntu22.04 apt 只到 clang-15 → 从 **apt.llvm.org 装 clang-18**（18.1.8）。
3. **★代理关键坑**：给 apt 设【全局】`http_proxy` 会把【域内】腾讯云 Ubuntu 镜像也走 mihomo → **502 Bad Gateway**。正解：apt 对域内镜像**直连**，只用 `/etc/apt/apt.conf.d/95proxy` 的 **per-host** 代理给 apt.llvm.org；且**绝不 export http_proxy 给 apt**（`sudo -E` 也会把 env 代理带进 apt）。curl 拉 nodejs.org 时才 export 代理。
4. **libclang**：bindgen 需 `libclang.so` → 装 `libclang-18-dev`，mozconfig 加 `--with-libclang-path=/usr/lib/llvm-18/lib`。
5. **node**：FF152 要 node>12.22.12，Ubuntu 自带 12.22.9 太旧 → 装官方 **node v20.18.0** tarball，mozconfig `NODEJS` 指过去。
6. **X11/GTK dev 包**：`x11-xcb` 等缺 → 一批 `lib*-dev`（x11/xcb/xrandr/xcomposite/gtk-3/dbus-glib/pango/cairo/drm/ffi…）。
7. **wasi headers 缺**（RLBox wasm 沙箱）→ `--without-wasm-sandboxed-libraries`（纯内部安全加固，对 web 内容零指纹面，关掉无碍真机一致性）。
8. 另加 `--disable-warnings-as-errors`（防 clang-18 与 Mozilla 原用 clang 版本差异引入的新 `-Werror`）。

→ **`Configure complete!` (rc=0)**，32 核（Chrome 发布构建此时已编完）开始全量编译。最终 mozconfig 见 `scripts/p0_setup_env.sh` 第 [6] 段。

## 2026-07-13 傍晚　P0 完成 + P1 赌一把通宵编（用户关机）

- ✅ **P0 stock baseline 编译成功**（`[BUILD OK]`，~23min，`obj-release/dist/bin/firefox` 存在）。
- ✅ **P1 补丁应用**（`scripts/fp_patch.py`，11 hunk 全命中）：BrowsingContext `FingerprintProfile` synced field + WebIDL `customFingerprint` + BC.cpp(Set/DidSet/CanSet 照抄 PlatformOverride) + `Navigator::GetPlatform`(纯字符串取键 `FpExtractStr`，避开 JS 引擎降编译风险) + `Navigator::Webdriver`→false + BiDi `moz:fingerprint` 模块 + 注册。**范围只到 platform + webdriver**（其余维度后续批次）。
- ✅ 云机 Gecko 树已 `git init` baseline（可回退）。
- 🐛 **踩坑**：FIELD 续行反斜杠后跟注释破坏 `MOZ_EACH_BC_FIELD` 宏 → incomplete-type 满屏；已修（反斜杠须行尾最后一字符），`scripts/fp_patch.py` H1 已同步修正。
- ⏳ **overnight 增量重编运行中**（nohup，云机独立跑，日志 `~/ff_overnight.log`，标记 `[OVERNIGHT BUILD OK/FAIL]`）。FIELD 已修过墙，但 BC.cpp/Navigator.cpp 的 C++ 改动**未编译验证**，可能仍有错——通宵编是赌一把，明天看结果。

**恢复（明天「继续」，详见 memory `firefox-fingerprint-port`）**：`ssh` 云机看 `~/ff_overnight.log`；OK→冒烟验证 `moz:fingerprint.setContextOverrides` 的 platform/webdriver 覆盖（BiDi 模块 proof 版 API 可能要调）；FAIL→`grep error:` 修 C++（多半 BC.cpp CanSet/DidSet 或 Navigator FpExtractStr）迭代，或 `git checkout -- .` 回 baseline。之后补 SessionData/ReplacedBy + 扩展 P2 其余标量维度。

## 2026-07-14　P1 管线证明 ✅ 成功 + 铺开 P2/P3/P4

overnight 编译失败在 C++ 改动上（FIELD 宏修复已生效、过墙），今早接手迭代修通：
- **修 4 个 bug**：① FIELD 续行反斜杠后不能跟注释（破坏 `MOZ_EACH_BC_FIELD`）；② `Navigator::Webdriver()` 是静态函数、不能用 mWindow → 改 `return false`（始终隐藏自动化，实测生效）；③ BiDi 基类导入路径 → `chrome://remote/content/webdriver-bidi/modules/RootBiDiModule.sys.mjs`；④ `FpExtractStr` 容忍 `"key": "val"` 冒号后空白（json.dumps 默认带空格）。
- **BiDi 模块正确写法**：`lazy.TabManager.allTabs` + `getBrowserForTab(tab).browsingContext`，设 `bc.customFingerprint`（chrome-only WebIDL attr）。
- **✅ 冒烟实测生效**：`moz:fingerprint.setContextOverrides` 下发 `{"platform":"Win32"}` → 同文档 `navigator.platform` = Win32；`navigator.webdriver` = false。整条链路（BiDi→BC synced 字段→跨进程同步→C++ 读取→缓存失效）真实跑通。
- **导航后丢失**（规格 §5b 坑）：`CanonicalBrowsingContext::ReplacedBy` 没拷 FingerprintProfile → P2 批次补 `txn.SetFingerprintProfile`。

**P2/P3/P4 批量实现中**（一次编译）：ReplacedBy 修复 + oscpu/userAgent/hardwareConcurrency/languages/screen + WebGL vendor/renderer + Document visibility/hasFocus/hidden。locale/时区/读回/worker/shadow 留后续批次。

**下一步**：批量编译验证后，导出完整 diff 到 `patches/`，再做 locale/时区 + 读回面 + worker + shadow 穿透，最后 P8 收尾（SessionData + 框架 new_context + fp_verify 全回归）。

## 2026-07-27　移动（安卓火狐）画像补全 + per-context 代理补录 + diff 全量重生成

靶场 `secdev.solvermarket.com/fp-d7c41884426bc076` 对着**安卓 Firefox** 画像逐面对齐，补齐几处内核读取点；并发现仓库 `patches/fp_all.diff` 已落后于编译机真源码，按"以实际编出二进制的源码为准"重算了整份 diff。

- **本轮 4 个内核补丁**（编译机 `D:\ff\src\firefox-152.0.5`，改在实跑源码上）：
  - `dom/base/Navigator.cpp`：`navigator.appVersion` 读画像 `appVersion`（原漏，露宿主）。
  - `docshell/base/BrowsingContext.cpp`：`TouchEventsOverride()` 由画像 `maxTouchPoints` 推导，**一处驱动** `maxTouchPoints`/`ontouchstart`/`(pointer:coarse)`/`(hover:none)` 四者自洽。
  - `dom/base/ScreenOrientation.cpp`（**新文件进 diff**）：`screen.orientation.type/angle` 按画像 `screenWidth/Height` 给（`ViewportSizeToOrientationType`；角度自算，竖屏=0 横屏=90，不复用桌面版 `ViewportSizeToAngle`）。默认路径取**宿主机显示器**朝向 → 横屏编译机上安卓竖屏画像会漏成 `landscape-primary`，故必须补。
  - `dom/canvas/ClientWebGLContext.cpp`：masked `RENDERER` 也走画像 `webglRenderer`（原只改 UNMASKED，masked 仍露宿主 ANGLE/D3D）；masked `VENDOR` 恒 `"Mozilla"`。
- **对接层**（bc 仓库，仅此一处）：`browser.py` `new_context` 对移动画像自动 `set_bounds` 到画像屏幕宽高，让 `window.inner*` 与 `(orientation)` 媒体查询跟随伪装屏幕（`screen.orientation` 由上面内核补丁负责，这里补窗口这条线）。桌面画像不动。
- **实测覆盖到跨源 OOPIF**：主框架 vs `ranksbyai.com` 子框架的 UA/platform/screen/dpr/orientation/touch **逐项一致**（393×873, dpr 2.75, `portrait-primary`/0）——内核 fpj 走 synced field + `Top()`，CDP `setDeviceMetricsOverride` 覆盖不到的跨源 OOPIF 这里天然覆盖。
- **diff 全量重生成**（编译机源码无 VCS，无法直接 `git diff`）：拉官方 pristine `firefox-152.0.5.source.tar.xz` → `git init` baseline，只比对 `dom/docshell/remote` 三个子树（所有改动都在此），用真 git 生成，`git apply --check --ignore-whitespace` **通过**。
  - **文件数 41 → 44**。重算发现旧 diff 漏了三样：`remote/.../moz/proxy.sys.mjs`（**per-context 代理模块**，bc `moz:proxy.setContextOverrides` 一直在用，却从没进过 diff）、`dom/base/nsGlobalWindowInner.cpp`（**devicePixelRatio** 覆盖 + 0 尺寸 sandbox srcdoc 回退画像 dpr）、`dom/base/ScreenOrientation.cpp`（本轮新增）。旧 41 文件全部保留、无回归。
  - README 覆盖表补 appVersion / screen.orientation / devicePixelRatio / maxTouchPoints / masked WebGL / per-context 代理；文件计数与同步状态表同步更新。
- **结论**：除字体和渲染细节纹理上限外，本画像各内核可见面已与安卓 Firefox 自洽。剩余已知差距：codec（`canPlayType`/`isTypeSupported` 反映 Windows 后端）、`enumerateDevices`（服务器 VM 全 0，真机有麦/摄/扬声器）——均需再动内核。
