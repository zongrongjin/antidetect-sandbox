# zzbrowser 本次修改说明（2026-08-26）

基线：Chromium **151.0.7907.0** / commit `fdadfe85a4cf993308b77a9324bd31b79df69ba3`  
补丁仓：`Chromium_zzbrowser`（`fp_full.diff` + `fp_webrtc.diff` + **本次 android surface**）  
机器：DS6797（80 核 / 125G RAM）  
对照文档：`zzbrowser-指纹字段传值.md`

本次**没有**改 UA / TLS / JA3。只补 DataDome 无感会采、原先 CDP 画像盖不到的四块接口，让「Windows 宿主扮安卓」时 JS 和 CSS 不再自相矛盾。

---

## 1. 改了什么

标记：`//BROWSER_FINGERPRINT_ANDROID_SURFACE`  
入口：`scripts/patch_android_surface.py`（`apply.sh` 末尾会跑）  
JSON 仍走现有 `RendererPreferences.fingerprint` + CDP `Fingerprint.setContextOverrides`，**不新增键名**。

| 字段 | 无感在采 | 本次行为 |
|---|---|---|
| `dpr` | CSS `resolution` / `-webkit-device-pixel-ratio`（CreepJS 也会采） | `MediaValues::CalculateDevicePixelRatio` 在 `dpr>0` 时返回同一值，与 `window.devicePixelRatio` 对齐 |
| `plugins` / `mimeTypes` | 空=`empty`，桌面 5 PDF 门面 | 显式 `plugins:[]` 或 `uaPlatform` 为 Android/iOS 且未传 → 空数组；桌面不传则原生 5 PDF |
| `pdfViewerEnabled` | 布尔 | 显式优先；Android/iOS 缺省 **true**（真机如此，空插件 + true 配套） |
| `keyboard` | 安卓应 `NA`（接口不存在） | `keyboard===false` 或 Android/iOS 缺省 → `navigator.keyboard === null`（IDL 改成 `Keyboard?`） |
| `connection` | iOS 应没有；安卓有 4g/10/50 | `connection===false` 或 iOS 缺省 → 接口不存在；对象则覆盖 `effectiveType/downlink/rtt/saveData` |

### 动到的文件（Blink）

- `third_party/blink/renderer/core/css/media_values.cc` — CSS dpr
- `third_party/blink/renderer/modules/plugins/dom_plugin_array.cc` — 空 plugins
- `third_party/blink/renderer/modules/plugins/navigator_plugins.cc` — `pdfViewerEnabled`
- `third_party/blink/renderer/modules/keyboard/navigator_keyboard.{cc,idl}` — 隐藏 keyboard
- `third_party/blink/renderer/modules/netinfo/network_information.cc` + `navigator_network_information.idl` — connection 可删/可覆盖

### 故意没做

- 不造半残 `Plugin` 对象（非空 plugins 仍走原生 5 PDF）
- 不造假 `KeyboardLayoutMap`
- 不给 `connection` 写 1.37 / 123 这种「很真」的小数
- 不改 TLS / HTTP2 / JA3

---

## 2. 画像怎么写

桌面（Win/macOS/Linux，三项接口不传）：

```jsonc
{ "uaPlatform": "Windows", "dpr": 1.5, "maxTouchPoints": 0 }
```

安卓（PrizePicks 401 浏览器用过）：

```jsonc
{
  "uaPlatform": "Android",
  "mobile": true,
  "dpr": 2.625,
  "maxTouchPoints": 5,
  "plugins": [],
  "mimeTypes": [],
  "pdfViewerEnabled": true,
  "keyboard": false
}
```

---

## 3. Release 产物（本机构建）

| | 目录 | 目标 | 说明 |
|---|---|---|---|
| Linux x64 | `src/out/Release/chrome` | official / 非 component | DS6797 80 核正在编 |
| Windows x64 交叉 | `src/out/Release_win/chrome.exe` | `target_os="win"` | **工具链被 Google 桶拦住**（`chrome-wintoolchain` 401 Anonymous）。需要一台已装 VS2022 的 Windows 跑 `depot_tools/win_toolchain/package_from_installed.py`，把 zip 放到云机后再编。 |

GN 共性：`is_official_build=true` `is_debug=false` `is_component_build=false` `symbol_level=0` `chrome_pgo_phase=0` `proprietary_codecs=true` `ffmpeg_branding="Chrome"` `enable_widevine=true`

原先 `out/Default` 是 **component 开发构建**（`chrome` 只是壳 + 一堆 so），**不要当 Release 交付**。

---

## 4. 和 PrizePicks 测试的关系

安卓画像 + 这份补丁后，浏览器里点登录可以打出 `POST /users/sign_in` **401**（`Email/password was incorrect`）。  
那是浏览器会话有效，不是协议复用 cookie 有效。协议仍受 TLS/头序/CF IP 影响，不在本次 Chromium 改动范围。
