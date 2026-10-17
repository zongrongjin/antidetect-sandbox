# Anti-Detect Sandbox

[English](README.en.md) · 中文

给 **Chromium** 和 **Firefox** 各打一套内核补丁。核心：

1. **隔离 context**：一个进程里开多套互不污染的环境，并发时省内存；每套环境的指纹和出口代理可以单独切。
2. **自定义响应 + 自定义缓存**：任何请求内核可控。用内存 HTML 当 HTTP 响应发出去，静态资源或与业务无关的getch请求等按规则走缓存或直接丢弃，少打网、加载更快、流量更省。

本仓库只有补丁和脚本，不含整棵浏览器源码。仅用于授权的安全研究、反检测研究和隐私测试。

```
antidetect-sandbox/
  chromium/    Chromium 151.0.7907.0 · CDP Context.setContextOverrides
  firefox/     Firefox 152.0.5        · BiDi moz:context.setContextOverrides
```

| | [chromium/](chromium/README.md) | [firefox/](firefox/README.md) |
|---|---|---|
| 基础版本 | 151.0.7907.0（commit `fdadfe85`） | 152.0.5 官方 tarball |
| 协议 | CDP `Context.setContextOverrides` | BiDi `moz:context.setContextOverrides` |
| 隔离单位 | `BrowserContext` | `userContext` / `BrowsingContext` |
| 预编译 | [Latest Release](https://github.com/zongrongjin/antidetect-sandbox/releases/latest) Windows mini_installer | [Latest Release](https://github.com/zongrongjin/antidetect-sandbox/releases/latest) Windows installer |
| Kasada 示例 | `chromium/scripts/kasada_demo.py` | `firefox/scripts/kasada_demo.py` |

针对不同内核做了额外补丁，例如 Chromium 的 brand 一致性，Gecko 的 `webdriver` / `isTrusted`等。

---

## 1. 隔离 context：并发省内存，指纹和代理可切换

官方 Chrome / Firefox，以及市面上常见的指纹浏览器（AdsPower / Multilogin / GoLogin / Dolphin{anty} 一类），都是 **一个进程一份环境**：一套身份对应一个浏览器进程（或一份独立 profile）。要跑 N 套身份就开 N 个进程，这会导致高并发的场景下内存和启动成本按并发数线性增长。

这里的隔离单位是 **context**（Chromium `BrowserContext`，Firefox `userContext` / `BrowsingContext`）：

- **一个进程、多套环境**。页面、cookie 罐、缓存、代理、指纹都绑在 context 上，互不污染。并发任务共用同一份浏览器进程，省的是进程级的 GPU / 网络栈 / 代码页，不是再克隆一整份浏览器。
- **指纹和代理跟 context 走，可以切换**。换一套画像、换一个出口 IP，发同一条 `setContextOverrides` 即可；不必重启浏览器，也不必新开进程。
- 主页面、iframe、跨源 OOPIF、dedicated / shared / service worker 从同一块 context 状态继承，保持同context的指纹一致性。

指纹本身是 context 上的一份 JSON 画像（UA、platform、语言、时区、屏幕、硬件并发、WebGL、WebRTC 公网 IP、字体、canvas/audio 读回等）。字段可选，不传就保持原生。

代理也在同一条命令里：账密跟 endpoint 一起下发，内核预发 `Proxy-Authorization`。

---

## 2. 自定义响应 + 自定义缓存：省流量，加载更快

目标站首页和重复的 JS/CSS/图片，没必要每次都走住宅代理。这两条补丁改的是网络栈：

| | 做什么 | 换来什么 |
|---|---|---|
| **`url` + `html` 自定义响应** | 地址栏是目标 URL，正文是内存里的 HTML，走 HTTP 替换响应（Chromium 伪装成 live HTTP/1.1；Firefox `nsIReplacedHttpResponse`） | 目标站首屏可以不打网。目标站点html里的脚本自定义加载。 |
| **自定义缓存** | 按 URL 规则 HIT / block / 放行。HIT 由内核直接给响应，不发网 | 重复资源零 RTT；telemetry / 埋点可以 block。流量和等待时间都下来。 |

cookie 种进该 context 的罐，不污染别的 context。缓存规则、假首页、cookie 和指纹/代理一样，都是这条命令的一部分。

---

## 用来干什么

- 同一进程里跑多套互不污染的环境（例如 Windows 桌面 + 安卓），每套指纹和出口 IP 成对，切身份不必新开进程。
- 精准的流量控制：假首页当 HTTP 响应发出，缓存 HIT 掉重复请求，研究 / 回归时少烧带宽、少等网络。
- **WAF/CAPTCHA**类产品研究：假首页里放下盾/验证码的入口脚本，静态 HIT、裁决出网。

---

## 如何用来对抗 antibot

Kasada / PerimeterX / DataDome 一类，假 HTML 和自定义缓存一起用，都在那条 `setContextOverrides` 里下发。构造出可以通过目标网站的最小html，借助浏览器环境发出遥测请求，拿到这些waf下发的凭证。

Turnstile/HCaptcha/FunCaptcha一类，根据风控等级选择自己构造captcha接入前端的最简demo，通过CDP通过。或者加载原始页面，把静态资源与无关请求放入缓存，只放行captcha相关请求来获得高分。

**假 HTML（`url` + `html`）**：地址栏是目标站 URL，正文是你构造的最小HTML，内核当 HTTP 响应发出去。HTML 里只留上表那条入口脚本，整站首页可以不打网。SDK 自己按 `<script src>` 拉脚本，再 POST 到对应路径。

**自定义缓存**：只让上表的裁决 POST 出网。HIT 掉入口脚本和静态资源（css、字体、图片），住宅代理流量和 RTT 都省掉——同一条挑战跑十次，不该把同一份脚本下十次。block 掉 telemetry / 广告 / 埋点。放行 `/tl`、`/collector`、`/js/`等关键请求，它们必须走这个 context 的代理和画像。缓存不能替你过盾。

一条链路就是：context 下发指纹 + 代理 → 假首页加载（HIT 静态、block 埋点）→ SDK 采集 → 裁决请求出网。

Kasada 现成例子：`chromium/scripts/kasada_demo.py`、`firefox/scripts/kasada_demo.py`。假首页插入 `/p.js`，等 `/tl`，body 含 `reload` 时即为通过。

---

## 对比

| | 市面魔改浏览器 | 补环境 | 本仓库 |
|---|---|---|---|
| 维护难度 | 高并发难过风控 | JS一更新就要改环境 | 画像在内核，盾脚本更新不用跟；漏读取点才改 C++ |
| 占用机器资源 | 一套身份一个进程（市面指纹浏览器同样） | 占用最低，仅需v8/iv8/vm2等占用 | 一个进程多个 context |
| 代理流量消耗 | 首屏和静态每次走代理 | 只有核心请求走网络 | 同补环境，只放行必要请求 |
| 速度 | 每次冷启动、整站打网 | 只请求和计算目标风控相关，不渲染js、css等 | 同补环境，但多出浏览器的基础消耗 |

普通自动化负责「开浏览器、点、等」；补环境负责「用node欺骗风控sdk」；市面指纹浏览器负责「每个进程一份画像」；这套负责「一个进程里多个可切换的 context，首屏和缓存走内核，少打网」。过盾仍然要画像自洽 + 干净出口 IP，内核不是万能解。

---

## 怎么用

1. 拿到带补丁的二进制（Chromium 用 Release 包，或按各目录 README 从源码编）。
2. 打开远程调试口（Chromium CDP / Firefox BiDi）。
3. **新建隔离 context**（不要在创建时把代理塞进官方的 `proxyServer` 字段）。
4. 对这个 context 发 **一条** `setContextOverrides`（指纹、代理、cookie、缓存、可选首屏一起下发）。
5. 之后正常导航、点、跑脚本。
6. 要换身份：再发一条 overrides，或另开一个 context。不必重启进程。

伪代码两边一样，只是方法和 session 模型不同：

```python
profile = {
    "userAgent": "...",          # Chrome 151 或 Firefox 152，和引擎一致
    "platform": "Win32",
    "timezone": "America/New_York",
    "webglVendor": "Google Inc. (NVIDIA)",
    "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "webRTC": 0,
}

overrides = {
    "fingerprint": json.dumps(profile),
    "proxy": {"endpoint": "host:port", "username": "...", "password": "..."},
    "cookies": [{"name": "a", "value": "b", "domain": "example.com", "path": "/"}],
    "cache": {"dir": "", "map": "{}", "rules": json.dumps({"blocks": ["*/telemetry/*"]})},
    "url": "https://example.com/",
    "html": "<!doctype html>...",   # 可省略；和 url 一起 = 内存假首页
}

# Chromium（已 attach 到该 BrowserContext 的 page session）
cdp("Context.setContextOverrides", overrides)

# Firefox（BiDi session.new 之后）
overrides["userContexts"] = [user_context_id]
bidi("moz:context.setContextOverrides", overrides)
```

`fingerprint` 必须是 **JSON 字符串**，不要把字段摊在协议参数顶层。

**Kasada（Arc'teryx）** 是这条链路的现成例子：自定义响应里插入 `/p.js`，等 `/tl`，body 含 `reload` 才算过。代理用环境变量，脚本不打印 ct/h。

```bash
export KASADA_PROXY='http://user:pass@host:port'   # 美/加住宅
python3 chromium/scripts/kasada_demo.py /path/to/chrome
python3 firefox/scripts/kasada_demo.py /path/to/firefox
```

编内核、字段全集、Windows 步骤分别看：

- Chromium：[chromium/README.md](chromium/README.md) · 字段 [chromium/docs/SPECIAL-CDP.md](chromium/docs/SPECIAL-CDP.md)
- Firefox：[firefox/README.md](firefox/README.md) · 字段 [firefox/docs/FINGERPRINT-SCHEMA.md](firefox/docs/FINGERPRINT-SCHEMA.md)
