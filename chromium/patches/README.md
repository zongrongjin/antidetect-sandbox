# chromium/patches

只打这三份。不要叠开源仓库的 `fp_full.diff`，也不要打第一次 release 里仅供审计的 `fp_p0_capabilities.diff` / `fp_consistency_followup.diff`。

| 文件 | 目录 |
|---|---|
| `fp_full.diff` | Chromium 源码根，基线 `fdadfe85a4cf993308b77a9324bd31b79df69ba3` |
| `fp_webrtc.diff` | `third_party/webrtc`（DEPS 独立仓库） |
| `fp_devtools.diff` | `third_party/devtools-frontend/src`（DEPS 独立仓库，缓存面板） |

`../src-new/` 是 `fp_full.diff` 里的新增文件。`../devtools-src-new/` 是 `fp_devtools.diff` 里的新增文件。都已经在 diff 中，apply 脚本不另拷。
