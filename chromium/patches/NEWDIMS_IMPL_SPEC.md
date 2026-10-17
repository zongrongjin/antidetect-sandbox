# 新增指纹维度实现规范（webgl2Extensions + 移动端自洽）

> 与 Firefox 定制版对齐，给 Chromium 补齐 4 个维度。**纯读侧**：指纹是不透明 JSON blob，
> `RendererPreferences.fingerprint` 携带、各读点自行 parse。不动 CDP handler / PDL / 管线。
> 契约键名与 `bc/browser_controller/fingerprint.py` 的 `_FIREFOX_KEYS` 一致：`dpr`、`maxTouchPoints`、`webgl2Extensions`。
>
> 基线 commit：`fdadfe85a4cf993308b77a9324bd31b79df69ba3`。以下行号对 **pristine** 源；构建机若已套
> `fp_full.diff` 需按实际偏移。**落地方式**：在 .63 真实签出里直接编辑源文件 → `git diff` 重生成
> `patches/fp_full.diff`（合并进现有补丁）→ 编译 → 自验 → 提交。

## 通用读法
window：`WebLocalFrameImpl::FromFrame(frame)->ViewImpl()->GetRendererPreferences().fingerprint`；
worker：`WorkerGlobalScope::Fingerprint().Utf8()`。解析 `base::JSONReader::Read(fp, base::JSON_PARSE_RFC)` → `->GetDict().FindString/FindInt/FindDouble/FindList`。
各 .cc 需补 include：`base/json/json_reader.h`、`base/values.h`、`core/exported/web_view_impl.h`、`core/frame/web_local_frame_impl.h`（worker 场景另加 `core/workers/worker_global_scope.h`）。

---
## 1) dpr — `core/frame/local_dom_window.cc`
锚点：`double LocalDOMWindow::devicePixelRatio() const`（pristine L1832-1837）。
```cpp
double LocalDOMWindow::devicePixelRatio() const {
  if (!GetFrame())
    return 0.0;
  // //BROWSER_FINGERPRINT: dpr 覆盖（读 fingerprint "dpr"，>0 生效）。GetFrame() 已非空，
  // 天然覆盖 0 尺寸/无 presContext 子帧（与 Firefox dpr-sandbox-iframe-fix 对齐）。
  if (WebLocalFrameImpl* fp_wf = WebLocalFrameImpl::FromFrame(GetFrame())) {
    if (WebViewImpl* fp_wv = fp_wf->ViewImpl()) {
      const std::string& fp = fp_wv->GetRendererPreferences().fingerprint;
      if (!fp.empty()) {
        std::optional<base::Value> v =
            base::JSONReader::Read(fp, base::JSON_PARSE_RFC);
        if (v && v->is_dict()) {
          if (std::optional<double> dpr = v->GetDict().FindDouble("dpr");
              dpr && *dpr > 0.0)
            return *dpr;
        }
      }
    }
  }
  return GetFrame()->DevicePixelRatio();
}
```
注：`FindDouble` 对 JSON int（1/2）与 double（1.5）都成立（base::Value GetIfDouble 兼 int）。

---
## 2) pointer/hover 自洽 — `core/css/media_values.cc`（核心内核改）
锚点：4 个静态 `Calculate*`（pristine L352-383），全部 `frame->GetSettings()->Get*`。
先加文件内匿名 ns helper：
```cpp
namespace {
// //BROWSER_FINGERPRINT: 从 frame 的 fingerprint 取 maxTouchPoints（nullopt=走宿主原值）
std::optional<int> FpMaxTouchPoints(LocalFrame* frame) {
  if (!frame) return std::nullopt;
  WebLocalFrameImpl* wf = WebLocalFrameImpl::FromFrame(frame);
  if (!wf || !wf->ViewImpl()) return std::nullopt;
  const std::string& fp = wf->ViewImpl()->GetRendererPreferences().fingerprint;
  if (fp.empty()) return std::nullopt;
  std::optional<base::Value> v = base::JSONReader::Read(fp, base::JSON_PARSE_RFC);
  if (!v || !v->is_dict()) return std::nullopt;
  return v->GetDict().FindInt("maxTouchPoints");
}
}  // namespace
```
Primary（返回单枚举，逻辑确定）：
- `CalculatePrimaryPointerType`：`mtp>0 → kPointerCoarseType`，`==0 → kPointerFineType`，否则原值。
- `CalculatePrimaryHoverType`：`mtp>0 → kHoverNone`，`==0 → kHoverHover`，否则原值。

Available（返回 **bitmask int** —— ⚠️ **必须在 .63 上核实位编码**：查 `core/frame/settings.h` 的
`GetAvailablePointerTypes/GetAvailableHoverTypes` 返回值约定与 `ui/base/pointer/pointer_device.h`
的 `POINTER_TYPE_*`/`HOVER_TYPE_*` 位常量）。设备类目标：`mtp>0 → 仅 coarse/none 位`，`==0 → 仅 fine/hover 位`。
别用 `static_cast<int>(枚举)` 当掩码，用真实位常量 OR。

---
## 3) screen.orientation type + angle — `modules/screen_orientation/screen_orientation.cc`
锚点：`type()`（L90-92 读 `type_`）、`angle()`（L94-96 读 `angle_`）。在函数顶按画像派生：
- 取 fp（`GetExecutionContext()` → `To<LocalDOMWindow>` → `GetFrame()` → WebViewImpl → fingerprint）。
- `landscape = screenWidth >= screenHeight`；`desktop = (maxTouchPoints==0)`（缺键当桌面）。
- `type()`：有 screenWidth/Height → `landscape ? kLandscapePrimary : kPortraitPrimary`（转 V8 枚举）。
- `angle()`：`desktop ? (landscape?0:90) : (landscape?90:0)`（与 Firefox ScreenOrientation.cpp 一致）。
缺画像键则回退 `type_`/`angle_` 原值。

---
## 4) webgl2Extensions 分键 — `modules/webgl/webgl_rendering_context_base.cc`
锚点：`getSupportedExtensions()`（补丁后 ~L4571），现有：
```cpp
Vector<String> fp_ext =
    FingerprintWebGLList(Host()->GetTopExecutionContext(), "webglExtensions");
if (!fp_ext.empty()) return fp_ext;
```
改为按版本分键（`IsWebGL2()` 已确认存在，见 .h L1321/1663；亦可 `ContextType()==Platform::kWebGL2ContextType`）：
```cpp
const char* fp_key = IsWebGL2() ? "webgl2Extensions" : "webglExtensions";
Vector<String> fp_ext =
    FingerprintWebGLList(Host()->GetTopExecutionContext(), fp_key);
if (!fp_ext.empty()) return fp_ext;
```
缺键 → 空 list → 原生回退（现有行为）。webgl1/webgl2 各读各键，避免合并集破绽。

---
## 5) navigator.maxTouchPoints（JS 属性本身）
其实现文件不在 `core/frame/navigator.{cc,h}` 也不在 `navigator_base.*`（partial interface，来自某 module）。
**.63 上 `git grep -n "maxTouchPoints\|MaxTouchPoints" third_party/blink/renderer` 一秒定位**。
读点逻辑最简：`FindInt("maxTouchPoints")`，`>=0` 生效，否则原值。

---
## bc 契约同步（另一 repo：`bc/browser_controller/fingerprint.py`）
`_CHROME_KEYS` 补 3 键（`_FIREFOX_KEYS` 已有，slot 属性已存在）：
```python
"dpr": "dpr",
"max_touch_points": "maxTouchPoints",
"webgl2_extensions": "webgl2Extensions",
```
与内核 release 同步提交（未支持前下发为惰性，Chrome 忽略未知键，安全）。

## .63 上执行顺序
1. `git -C <src> log --oneline -1` 确认基线 `fdadfe85`；`git -C <src> diff --stat` 看 fp_full.diff 是否已套。
2. 按上 5 处编辑真实源文件（Available bitmask、maxTouchPoints 文件先核实）。
3. `git -C <src> diff -- <5 files> ` 重生成，合并进 `patches/fp_full.diff`（UTF-8，勿 PowerShell `>`）。
4. 编译（component build，改动落 blink_core / content）；自验（raw-CDP 起 context 下发含新键的 fingerprint，验 dpr/maxTouchPoints/pointer:coarse/hover:none/orientation.angle/webgl2 扩展）。
5. 更新 `patches/fp_full.diff` + `README.md` 提交；打包 `mini_installer.exe` 传 release；同步 bc `_CHROME_KEYS`。
