# Network 面板缓存规则

这次只备份缓存规则相关的源码。编译产物在服务器上：

`/root/src/chromium/src/out/Release/chrome`

生成时间 2026-10-29 05:50 UTC。没有覆盖正在给其他服务用的这份：

`/root/work/release/chromium-linux-x64-v151.0.7907.0-android-surface/chrome`

## 补丁

- `protocol_config.patch`：让 `Context` 域生成 `getCacheState`、`explainCache`、`cacheDecision`。打在 Chromium 源码根目录。
- `devtools-frontend.patch`：Network 面板的缓存规则栏和 URL 上色。打在 `third_party/devtools-frontend/src`。
- `chromium-new-files.patch`：`Context` 协议和请求拦截器的当前全文。这些文件在 Chromium 仓库里原本是未跟踪文件，所以这里是 `/dev/null` 对比，不是相对上一次提交的增量。打在 Chromium 源码根目录。

## 行为

Network 工具栏打开「缓存规则」。include、exclude、captures、callbacks、blocks、allowMiss、observe 各有输入框和勾选。应用后按内核裁决给左侧 URL 上色：命中为绿，写入为琥珀，拦截为红，观察为蓝，捕获和回调为紫。未勾选的键不会写进规则。应用只提交 `cache`，不改指纹、代理和 cookie。
