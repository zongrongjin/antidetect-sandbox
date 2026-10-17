# Windows 构建（指纹 Chromium）

在干净的 Windows Server 2022（C 盘 >=150GB 空闲）上复现本指纹补丁的 Windows 版。2026-07-15 已实测编出 chrome + 三 context 检测站全绿。

**耗时参考**：32c/64G 约 2.5h；**16c/31G 实测 7h**（2026-07-22，83163 个目标）。整个 `out\Default` 约 100GB，加源码 24GB，**准备 150GB+ 空闲**。

## 前置
1. **代理**（GFW）：clash/mihomo → 127.0.0.1:7890（Google 源被墙）。设 `HTTP_PROXY/HTTPS_PROXY`。
   注：部分云厂商机器（如腾讯云）可直连 `chromium.googlesource.com`，先测一次再决定要不要代理。
2. **工具链**：Git for Windows（`git config --system core.longpaths true` + 注册表 LongPathsEnabled=1）；depot_tools（C:\depot_tools，`DEPOT_TOOLS_WIN_TOOLCHAIN=0`）；**VS2022 BuildTools**（VCTools + MSVC v143 + Win11 SDK 10.0.22621 + C++ ATL + **Debugging Tools for Windows**）。
   - ★ **装到无空格路径**，例如 `C:\BuildTools`。用 PowerShell `Start-Process -ArgumentList` 传 `--installPath` 时含空格的路径**不会自动加引号**，会被截断在第一个空格 —— 曾因此把整套 VS 装进了 `C:\Program`，而安装器仍返回 3010 看似成功。装完务必确认 `vcvarsall.bat` / `cl.exe` / `atlmfc\include\atlbase.h` 真的存在。
   - Debugging Tools 若 VS 安装器没带上，用 winsdksetup.exe `/features OptionId.WindowsDesktopDebuggers` 补装。
3. **Defender 排除**：`C:\src`、`C:\depot_tools` 及 cl/link/ninja 等进程，否则编译慢 2-3 倍。

## 拉源码（基线 commit `fdadfe85a4cf993308b77a9324bd31b79df69ba3`，Chromium 151.0.7907.0）
`.gclient` 设 `target_os=['win']`；`git init src` + `git fetch --depth 1 origin <commit>` + `git checkout -f FETCH_HEAD`；`gclient sync --no-history --shallow -D -j4`（**★`-j4` 避 googlesource 429 限流**，高并发会挂）。`.gclient` 用 `managed:False` 保护补丁不被 sync 还原。

## 打补丁
直接跑 `scripts/apply.sh <src路径>`，它会套**两个**补丁：

- `patches/fp_full.diff` → `chromium/src`，套用后 `git status --porcelain` 应为 **54** 项（51 改 + 3 个 src-new 新增）
- `patches/fp_webrtc.diff` → `third_party/webrtc`（**DEPS 管理的独立仓库，有自己的 .git**），应为 **4** 项

两个都用 `--ignore-whitespace`：Windows 上 `third_party/webrtc` 会被 git 的 autocrlf 转成 CRLF，
而补丁存的是 LF（`chromium/src` 因自带 `.gitattributes` 的 `* -text` 不受影响）。
若 SYSTEM 拥有源码目录，git 需 `git config --global --add safe.directory '*'`。

> ★ **生成补丁时绝对不要用 PowerShell 的 `>` 或 `Out-File`** —— 它们默认写 UTF-16LE，
> 而 `git apply` 对 UTF-16 直接报 `No valid patches in input`。本仓库的补丁曾因此完全失效过。
> 用 `git diff > x.diff` 时请在 bash 里执行，或生成后确认 `file x.diff` 显示 UTF-8。

> **补丁文件必须是 UTF-8**。曾被存成 UTF-16LE，`git apply` 直接报 `No valid patches in input`，
> `scripts/apply.sh` 完全跑不通。改动补丁时注意别用会改写编码的编辑器/重定向
> （PowerShell 的 `>` 和 `Out-File` 默认就会写成 UTF-16LE）。

## 编译（关键坑）
`out\Default\args.gn` 对齐 Linux：`is_component_build=true / is_debug=false / symbol_level=0 / blink_symbol_level=0 / enable_nacl=false / use_remoteexec=false`。编译进程 env **必须**：
- `vs2022_install=C:\BuildTools`（指向你实际的 BuildTools 安装路径）—— vs_toolchain.py 路径表里 2022 只查 `%ProgramFiles%`，BuildTools 默认却装在 `%ProgramFiles(x86)%`，不设此 env 会报 "No supported Visual Studio"。
- `PYTHONUTF8=1` —— 补丁含**中文注释**，Windows cp1252 读 `.pdl` 会 UnicodeDecodeError 崩。
`gn gen out\Default` → `autoninja -C out\Default chrome`。产物 `out\Default\chrome.exe`（component build，chrome.exe 只是壳，代码在 551 个 DLL 里）。见 `windows/win_chromium_build.ps1`。SYSTEM 计划任务即可跑编译。

**增量重编**：只改少数文件时，`git checkout -- <改动的文件>` 后只对这几个文件重打补丁
（`git apply --include=<path>`），**不要全量回滚重打** —— 那会刷新全部 50 个文件的 mtime，
触发 7 小时全量重编。改 blink 里 1-2 个文件时增量约 2 分钟。
注意 component build 下 `chrome.exe` 不会被重链，**要看目标 DLL（如 `blink_core.dll`）的 mtime 判断是否真的重建**。

## 安装（替换已装的 Chromium）
`autoninja -C out\Default mini_installer` → `out\Default\mini_installer.exe`（component build 约 628MB），
`mini_installer.exe --system-level --do-not-launch-chrome --verbose-logging`。日志在 `C:\Windows\SystemTemp\chromium_installer.log`。

- ★ **必须先停掉所有在用该二进制的进程**，否则安装器会在挪完 551 个 DLL 后卡在「删除空目录」（`0x20` 占用），
  然后**全量回滚**（`result: 7`）—— 表现为所有文件 mtime 都没变，很像「同版本被跳过」，其实是装到最后失败了。
  只杀 chrome 进程没用：worker 会秒级重启。要停的是拉起它的服务本身。
- 新旧版本号相同，**不能靠版本号判断是否替换成功**，看 `Application\<ver>\blink_core.dll` 的 mtime，
  最终以行为验证为准（见下）。
- 装之前把 `C:\Program Files\Chromium\Application` 整个备份一份（约 1.5GB），回退直接拷回。

## 验证（单 context 全维度）
`python scripts/verify.py <chrome 路径>`，**退出码 0=通过 / 1=有失败**，可直接接 CI。除高熵值外还会校验：
- 主文档与子资源实际发出的 `Accept-Language` 请求头必须**都等于**传入的 `acceptLanguages`（浏览器逐字透传，不自己补 q）
- `navigator.languages` 必须**剥掉** q 值
- WebGL vendor/renderer（拿不到 context 会判 FAIL，不再静默假通过）

脚本已内置这几个必需 flag：`--disable-features=ReduceAcceptLanguage`（否则 languages 被截断成一项，
q 值泄漏会被掩盖）、`--use-gl=angle --use-angle=swiftshader`（否则 Windows headless 下拿不到 WebGL context）、
`--password-store=basic`。

## 验证（三 context）
chrome 的 os_crypt **DPAPI 在 ssh 网络登录(type3)不可用** → os_crypt_init DCHECK 崩。用 **Administrator + 密码的计划任务(BATCH 登录 type4)** 跑验证；chrome 加 `--no-sandbox --headless=new --password-store=basic`；python 进程内删 `HTTP_PROXY`（否则 urllib 探 localhost:9222 走代理超时）+ `sys.stdout.reconfigure('utf-8')`（打印中文 meta）。三 context（法国/NVIDIA/Win、日本/Apple/Mac、美国/AMD/Linux 各不同画像）跑检测站 `secdev.solvermarket.com` → **inconsistencies=0、互不干扰**。见 `windows/win_chrome_3ctx.py`。
