#!/usr/bin/env bash
# 配置 GN args 并全量编译 chrome。用法: scripts/build.sh <chromium/src 路径>
# 需要 depot_tools 在 PATH（gn / autoninja）。
set -e
SRC="${1:?用法: build.sh <chromium/src 路径>}"
cd "$SRC"

mkdir -p out/Default
cat > out/Default/args.gn <<'EOF'
is_debug = false
symbol_level = 0
blink_symbol_level = 0
is_component_build = true
enable_nacl = false
use_remoteexec = false
# 专有编解码器：开源 Chromium 默认不带 H.264/H.265/AAC，UA 却自称 Google Chrome →
# canPlayType 返回空串会露馅（Chromium-not-Chrome）。开启后与正版 Chrome 一致。
proprietary_codecs = true
ffmpeg_branding = "Chrome"
# Widevine：默认 enable_widevine=false（EME 只剩 ClearKey，requestMediaKeySystemAccess
# ('com.widevine.alpha') 抛 NotSupportedError）。开启后注册 Widevine 组件；CDM 本体由组件
# 更新器联网拉取，或从真 Chrome/Edge 安装目录拷 WidevineCdm 到 profile 离线注册（见 README）。
enable_widevine = true
EOF
echo ">>> args.gn:"; cat out/Default/args.gn

echo ">>> gn gen"
gn gen out/Default
echo ">>> autoninja -C out/Default chrome"
autoninja -C out/Default chrome
echo ">>> 完成：$SRC/out/Default/chrome"
