#!/usr/bin/env bash
# 把这一份补丁套到已 checkout 到基础 commit 的 Chromium 源码树。
# 用法: bash chromium/scripts/apply.sh <chromium/src 路径>
# 只打 fp_full.diff、fp_webrtc.diff、fp_devtools.diff。
# 不要再叠开源仓库的 fp_full.diff，也不要跑 patch_context_domain.py。
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:?用法: apply.sh <chromium/src 路径>}"
BASE=fdadfe85a4cf993308b77a9324bd31b79df69ba3
DIFF="$HERE/patches/fp_full.diff"
DIFF_RTC="$HERE/patches/fp_webrtc.diff"
DIFF_DT="$HERE/patches/fp_devtools.diff"
SRC_RTC="$SRC/third_party/webrtc"
SRC_DT="$SRC/third_party/devtools-frontend/src"

cd "$SRC"
cur="$(git rev-parse HEAD)"
if [ "$cur" != "$BASE" ]; then
  echo "!! 警告: 当前 HEAD=$cur"
  echo "   期望基础 commit=$BASE (Chromium 151.0.7907.0)"
  echo "   非该 commit 时补丁可能有 context 冲突。继续套用中..."
fi

echo ">>> git apply --check (chromium/src)"
git apply --check --ignore-whitespace "$DIFF"
echo ">>> git apply (chromium/src) fp_full.diff"
git apply --ignore-whitespace "$DIFF"

if [ ! -d "$SRC_RTC/.git" ]; then
  echo "!! 找不到 $SRC_RTC/.git —— gclient sync 是否已完成？"
  exit 1
fi
cd "$SRC_RTC"
echo ">>> git apply --check (third_party/webrtc)"
git apply --check --ignore-whitespace "$DIFF_RTC"
echo ">>> git apply (third_party/webrtc) fp_webrtc.diff"
git apply --ignore-whitespace "$DIFF_RTC"

if [ ! -d "$SRC_DT/.git" ]; then
  echo "!! 找不到 $SRC_DT/.git —— gclient sync 是否已完成？"
  exit 1
fi
cd "$SRC_DT"
echo ">>> git apply --check (third_party/devtools-frontend/src)"
git apply --check --ignore-whitespace "$DIFF_DT"
echo ">>> git apply (devtools-frontend) fp_devtools.diff"
git apply --ignore-whitespace "$DIFF_DT"

echo ">>> 完成"
echo "    chromium/src                          fp_full.diff"
echo "    third_party/webrtc                    fp_webrtc.diff"
echo "    third_party/devtools-frontend/src     fp_devtools.diff"
echo "    接着把 chromium/args.gn 抄到 out/Default/args.gn 再 gn gen"
