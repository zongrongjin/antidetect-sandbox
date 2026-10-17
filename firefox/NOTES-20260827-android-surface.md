# zzbrowser Firefox 本次修改说明（2026-08-27）

基线：Firefox **152.0.5**  
补丁仓：`firefox_zzbrowser` 分支 `wip/android-surface`  
对照：Chromium tag `chrome-v151.0.7907.0-android-surface`

从当前 `main`（已含 P0 + consistency）开分支，跟进 Chromium 8 月 26 日的
android-surface：DataDome 无感会采、原先画像盖不到的 plugins / pdfViewer /
connection。**没有**改 UA / TLS / JA3。CSS `dpr` 在 Firefox `main` 已经通过
`overrideDPPX` 同时驱动 JS `devicePixelRatio` 和 CSS `(resolution)` /
`(-moz-device-pixel-ratio)`，这次不再另开 Blink `MediaValues` 那种第二落点。

---

## 1. 改了什么

标记：`BROWSER_FINGERPRINT_ANDROID_SURFACE`  
入口：`scripts/patch_android_surface.py`（`fp_apply.sh` 末尾会跑）  
JSON 仍走现有 `BrowsingContext.FingerprintProfile` +
`moz:fingerprint.setContextOverrides`，**不新增键名**。Firefox 没有
`uaPlatform`，Android/iOS 缺省改看 `userAgent` / `platform` 里的 Android、
iPhone、iPad。

| 字段 | 无感在采 | 本次行为 |
|---|---|---|
| `dpr` | CSS `resolution` | **已在 main**：`overrideDPPX` 对齐 JS + CSS。本分支只在 verify 里回归。 |
| `plugins` / `mimeTypes` | 空=`empty`，桌面 5 PDF | 显式 `plugins:[]` 或 UA 含 Android/iOS 且未传 → 空数组；桌面不传则原生 5 PDF / 2 MIME |
| `pdfViewerEnabled` | 布尔 | 显式优先；Android/iOS 缺省 **true**（真机如此，空插件 + true 配套） |
| `keyboard` | 安卓 Chrome 应 `NA` | **真 Firefox 本来就没有 Keyboard API**。桌面/安卓 `'keyboard' in navigator === false`。字段保留给与 Chromium 画像兼容，内核忽略。 |
| `connection` | iOS 没有；安卓 Firefox 有 `type` | `connection===false` 或 iOS 缺省 → 属性不存在；对象或 Android 缺省 → 露出 `navigator.connection`（绕过全局 `dom.netinfo.enabled`）。Firefox 只有 `type`，把 Chromium 的 `effectiveType` 4g/3g/2g 映射成 `cellular`；也可直接传 `connection.type`。不造 downlink/rtt/saveData。 |

### 动到的文件（Gecko）

- `dom/base/FingerprintAndroidSurface.h`（新增共享 JSON helper）
- `dom/base/nsPluginArray.cpp` — 空 plugins
- `dom/base/nsMimeTypeArray.cpp` — 空 mimeTypes
- `dom/base/Navigator.cpp` — `pdfViewerEnabled`
- `dom/webidl/NetworkInformation.webidl` / `Navigator.webidl` / `WorkerNavigator.webidl` — Pref → per-context Func
- `dom/network/Connection.{h,cpp}` — Enabled + Type 覆盖

### 故意没做

- 不造半残 `Plugin` 对象（非空 plugins 仍走原生 5 PDF）
- 不实现 `navigator.keyboard`（真 Firefox 没有，造出来反而是特征）
- 不给 Firefox 补 Chromium 专属的 `effectiveType` / `downlink` / `rtt` / `saveData` 属性
- 不改 TLS / HTTP2 / JA3

---

## 2. 画像怎么写

桌面（Win/macOS/Linux，三项接口不传）：

```jsonc
{ "platform": "Win32", "dpr": 1.5, "maxTouchPoints": 0 }
```

安卓（对齐 Chromium PrizePicks 那份，去掉 uaPlatform / UA-CH）：

```jsonc
{
  "userAgent": "Mozilla/5.0 (Android 14; Mobile; rv:152.0) Gecko/152.0 Firefox/152.0",
  "platform": "Linux armv81",
  "oscpu": "Linux armv81",
  "appVersion": "5.0 (Android 14)",
  "dpr": 2.625,
  "maxTouchPoints": 5,
  "plugins": [],
  "mimeTypes": [],
  "pdfViewerEnabled": true,
  "keyboard": false,
  "connection": { "type": "wifi", "effectiveType": "4g" }
}
```

---

## 3. 怎么套

```bash
bash scripts/fp_apply.sh ~/firefox-152.0.5
# 内部：fp_all.diff + patch_android_surface.py
python3 scripts/verify_android_surface.py obj-*/dist/bin/firefox
```

本分支尚未在真实 152.0.5 树上编译验证。第一次 `mach build` 若 IDL/函数体漂移，
`patch_android_surface.py` 会 `die` 打出没命中的锚点。

---

## 4. 和 Chromium android-surface 的差异

| | Chromium | Firefox 本分支 |
|---|---|---|
| OS 缺省 | `uaPlatform` Android/iOS | `userAgent`/`platform` 含 Android/iPhone/iPad |
| CSS dpr | 另补 `MediaValues::CalculateDevicePixelRatio` | main 已有 `overrideDPPX` |
| keyboard | IDL 改成 `Keyboard?`，安卓返回 null | 真 Firefox 无此 API，不造 |
| connection | 桌面 Chrome 本来就有，可改值/可删 | 桌面 Firefox 默认没有；安卓画像才露出 |
| connection 字段 | effectiveType/downlink/rtt/saveData | 只消费 `type`，effectiveType 仅用来映射 cellular |
