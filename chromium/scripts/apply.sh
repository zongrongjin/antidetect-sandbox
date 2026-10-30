#!/usr/bin/env bash
# 把指纹补丁套到一份**已 checkout 到基础 commit** 的 Chromium 源码树。
# 用法: scripts/apply.sh <chromium/src 路径>
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"          # chromium/ 引擎目录
SRC="${1:?用法: apply.sh <chromium/src 路径>}"
BASE=fdadfe85a4cf993308b77a9324bd31b79df69ba3
DIFF="$HERE/patches/fp_full.diff"
# WebRTC 是 DEPS 管理的独立仓库，补丁要单独往 third_party/webrtc 里套
DIFF_RTC="$HERE/patches/fp_webrtc.diff"
SRC_RTC="$SRC/third_party/webrtc"

cd "$SRC"
cur="$(git rev-parse HEAD)"
if [ "$cur" != "$BASE" ]; then
  echo "!! 警告: 当前 HEAD=$cur"
  echo "   期望基础 commit=$BASE (Chromium 151.0.7907.0)"
  echo "   非该 commit 时补丁可能有 context 冲突。继续套用中..."
fi

# --ignore-whitespace: Windows 上 checkout 可能是 CRLF，而补丁存的是 LF
# fp_full.diff 已含 3 个新增文件，必须先 apply 再拷 src-new（否则 git apply 会 already exists）。
echo ">>> git apply --check (chromium/src)"
git apply --check --ignore-whitespace "$DIFF"
echo ">>> git apply (chromium/src)"
git apply --ignore-whitespace "$DIFF"

echo ">>> 拷贝新增文件 (src-new/ 与 diff 同步，便于阅读)"
cp -v "$HERE/src-new/content/browser/devtools/protocol/fingerprint_handler.cc" \
      "$SRC/content/browser/devtools/protocol/" 2>/dev/null || true
cp -v "$HERE/src-new/content/browser/devtools/protocol/fingerprint_handler.h" \
      "$SRC/content/browser/devtools/protocol/" 2>/dev/null || true
cp -v "$HERE/src-new/third_party/blink/public/devtools_protocol/domains/Fingerprint.pdl" \
      "$SRC/third_party/blink/public/devtools_protocol/domains/" 2>/dev/null || true

echo ">>> Context 域（Fingerprint 改名 + proxy 并入）"
python3 "$HERE/scripts/patch_context_domain.py" "$SRC"

echo ">>> cache rules（改名之后套，BUILD.gn 里已经是 context_handler）"
git apply --check --ignore-whitespace "$HERE/patches/cache_rules_install.diff"
git apply --ignore-whitespace "$HERE/patches/cache_rules_install.diff"
git apply --check --ignore-whitespace "$HERE/patches/cache_rules_protocol.diff"
git apply --ignore-whitespace "$HERE/patches/cache_rules_protocol.diff"
if [ -d "$SRC/third_party/devtools-frontend/src/.git" ]; then
  git -C "$SRC/third_party/devtools-frontend/src" apply --check --ignore-whitespace \
    "$HERE/patches/cache_rules_devtools.diff"
  git -C "$SRC/third_party/devtools-frontend/src" apply --ignore-whitespace \
    "$HERE/patches/cache_rules_devtools.diff"
fi

if [ ! -d "$SRC_RTC/.git" ]; then
  echo "!! 找不到 $SRC_RTC/.git —— gclient sync 是否已完成？"
  exit 1
fi
cd "$SRC_RTC"
echo ">>> git apply --check (third_party/webrtc)"
git apply --check --ignore-whitespace "$DIFF_RTC"
echo ">>> git apply (third_party/webrtc)"
git apply --ignore-whitespace "$DIFF_RTC"
cd "$SRC"

echo ">>> 完成："
echo "    chromium/src        fp_full.diff，然后 cache_rules_install.diff / cache_rules_protocol.diff"
echo "    devtools-frontend    cache_rules_devtools.diff"
echo "    third_party/webrtc   fp_webrtc.diff"
echo "    接着跑 scripts/build.sh"
