# Windows 构建（指纹 Firefox 152）

在 Windows Server 2022（32c/64G）上复现本指纹补丁的 Windows 版。2026-07-15 已实测编出 firefox + 三 context 检测站全绿（含第 2 个 context serviceWorker 不串）。

## 前置
1. **代理**（Google/taskcluster 部分资源）：clash/mihomo → 127.0.0.1:7890；Mozilla ftp 可直连。
2. **MozillaBuild**（`C:\mozilla-build`，含 msys2/python3/7z）+ VS2022 BuildTools（同 Chromium）。

## 源码 + bootstrap
官方源码 tarball `ftp.mozilla.org/pub/firefox/releases/152.0.5/source/firefox-152.0.5.source.tar.xz`。**解压用 `C:\mozilla-build\bin\7z.exe` 两步**（.tar.xz→.tar→文件；Windows bsdtar 缺 xz、msys2 tar 缺 DLL）。
`mach bootstrap --application-choice browser`（★**不接受 `--no-interactive`**；装 Rust 后需把 `C:\Users\<user>\.cargo\bin` 加进 PATH 再跑一次，否则 exit1）。

## mozconfig（见 windows/mozconfig）
```
ac_add_options --enable-application=browser
ac_add_options --enable-optimize
ac_add_options --disable-debug
ac_add_options --enable-release
ac_add_options --enable-update-channel=release
ac_add_options --disable-warnings-as-errors
ac_add_options --without-wasm-sandboxed-libraries
ac_add_options --enable-bootstrap
export MOZILLA_OFFICIAL=1
mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/obj-release
```
**★不要设 `MOZ_AUTOMATION`**（tarball 无 VCS，configure 会报 "unable to resolve VCS type"）。`--enable-bootstrap` 自动拉 clang-cl。

## 打补丁
用**含 service-worker 修复版**的 `fp_all.diff`（GitHub Release `firefox-v152.0.5-fp` 附件那版；仓库旧 diff 会致第 2 个 context SW 串画像）。`git apply --ignore-whitespace -p1 --exclude=.gitignore fp_all.diff`（tarball 的 .gitignore 与 diff 不符，排除它）。

## 编译（关键坑）
`mach` 在**计划任务 session 0 起不来** → 用**交互 ssh 会话**跑 `python3 mach build`（全程 `PYTHONUTF8=1`）。产物 `obj-release\dist\bin\firefox.exe`（约 48min）。见 `windows/win_ff_build.ps1`。

## 验证（三 context）
用 Administrator 计划任务(DPAPI/BATCH 登录)跑。★**自启 firefox `-headless --remote-debugging-port 9223` → 轮询 `ws://127.0.0.1:9223/session`(suppress_origin=True) 就绪再 `bc.connect(bidi)`**（browser_controller 的 _wait_ready 只 TCP 探测、firefox `/session` 处理器注册稍晚, 过早连接会 404）。python 删 HTTP_PROXY + `sys.stdout.reconfigure('utf-8')`。三 context（法国/日本/美国）→ `secdev.solvermarket.com` **inconsistencies=0、互不干扰**。见 `windows/win_ff_3ctx.py`。
