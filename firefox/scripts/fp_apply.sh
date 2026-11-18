#!/usr/bin/env bash
# 把 fp_all.diff 套到官方 Firefox 152.0.5 源码树。
# 用法: bash firefox/scripts/fp_apply.sh [源码根路径]   (默认 ~/firefox-152.0.5)
# 只打这一份。不要再跑 patch_android_surface.py / patch_context_module.py /
# patch_input_trusted.py / patch_offscreen_webgl.py。
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$HOME/firefox-152.0.5}"
DIFF="$HERE/patches/fp_all.diff"

cd "$SRC"

if [ ! -d .git ]; then
  git init -q
  printf 'obj-release/\nobj-*/\n.mozbuild/\nmozconfig\n*.fpbak\n*.orig\n' > .gitignore
  git -c user.email=fp@local -c user.name=fp add -A
  git -c user.email=fp@local -c user.name=fp commit -q -m "baseline firefox-152.0.5"
  echo "== baseline committed =="
else
  echo "== git 已存在，不重置工作区。请确认这是干净的官方 152.0.5 =="
fi

echo "== git apply --check =="
git apply --check --ignore-whitespace --exclude=.gitignore "$DIFF"
echo "== git apply fp_all.diff =="
git apply --ignore-whitespace --exclude=.gitignore "$DIFF"

echo "== 完成。把 firefox/mozconfig 复制成源码根的 mozconfig，然后 ./mach build =="
