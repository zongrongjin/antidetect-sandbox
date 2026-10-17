#!/bin/bash
# 把 fp_all.diff 套到官方 Firefox 152.0.5 源码树。
# 用法: bash fp_apply.sh [源码根路径]   (默认 ~/firefox-152.0.5)
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"        # firefox/ 引擎目录
SRC="${1:-$HOME/firefox-152.0.5}"
DIFF="$HERE/patches/fp_all.diff"

cd "$SRC"

# tarball 无 VCS —— 先 git init 建一个 baseline commit, 便于套用/重置/生成 diff
if [ ! -d .git ]; then
  git init -q
  printf 'obj-release/\nobj-*/\n.mozbuild/\nmozconfig\n*.fpbak\n*.orig\n' > .gitignore
  git -c user.email=fp@local -c user.name=fp add -A
  git -c user.email=fp@local -c user.name=fp commit -q -m "baseline firefox-152.0.5"
  echo "== baseline committed =="
else
  echo "== git 已存在, 重置到 baseline 再套 =="
  git checkout -- . 2>/dev/null || true
  git clean -fdq -e obj-release -e 'obj-*' -e mozconfig 2>/dev/null || true
fi

# CRLF 差异(Windows checkout)用 --ignore-whitespace; tarball 的 .gitignore 与 diff 不符, 排除它
echo "== git apply --check =="
git apply --check --ignore-whitespace --exclude=.gitignore "$DIFF"
echo "== git apply =="
git apply --ignore-whitespace --exclude=.gitignore "$DIFF"

if [ -f "$HERE/scripts/patch_android_surface.py" ]; then
  echo "== android surface (plugins/pdfViewer/connection) =="
  python3 "$HERE/scripts/patch_android_surface.py" "$SRC"
fi

if [ -f "$HERE/scripts/patch_context_module.py" ]; then
  echo "== moz:context (fingerprint + proxy + cache/html/cookies) =="
  python3 "$HERE/scripts/patch_context_module.py" "$SRC"
fi

if [ -f "$HERE/scripts/patch_input_trusted.py" ]; then
  echo "== BiDi input isTrusted (widget; page JS untouched) =="
  python3 "$HERE/scripts/patch_input_trusted.py" "$SRC"
fi

if [ -f "$HERE/scripts/patch_offscreen_webgl.py" ]; then
  echo "== OffscreenCanvas WebGL + masked RENDERER=Mozilla =="
  python3 "$HERE/scripts/patch_offscreen_webgl.py" "$SRC/dom/canvas/ClientWebGLContext.cpp"
fi

echo "== 完成: 完整指纹补丁 + android surface 已套用。接着写 mozconfig 并 ./mach build =="
