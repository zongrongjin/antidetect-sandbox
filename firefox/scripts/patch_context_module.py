#!/usr/bin/env python3
"""Register moz:context after fp_all.diff. Usage: patch_context_module.py <firefox-src>"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC_MOD = HERE / "patches" / "bidi-module" / "context.sys.mjs"


def main():
    if len(sys.argv) != 2:
        print("usage: patch_context_module.py <firefox-src>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dest_dir = src / "remote" / "webdriver-bidi" / "modules" / "root" / "moz"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_MOD, dest_dir / "context.sys.mjs")

    jar = src / "remote" / "webdriver-bidi" / "jar.mn"
    text = jar.read_text(encoding="utf-8")
    needle = (
        "  content/webdriver-bidi/modules/root/moz/proxy.sys.mjs "
        "(modules/root/moz/proxy.sys.mjs)\n"
    )
    insert = (
        needle
        + "  content/webdriver-bidi/modules/root/moz/context.sys.mjs "
        "(modules/root/moz/context.sys.mjs)\n"
    )
    if "modules/root/moz/context.sys.mjs" not in text:
        if needle not in text:
            raise SystemExit("jar.mn: moz/proxy.sys.mjs line not found")
        jar.write_text(text.replace(needle, insert, 1), encoding="utf-8")

    reg = src / "remote" / "webdriver-bidi" / "modules" / "ModuleRegistry.sys.mjs"
    rtext = reg.read_text(encoding="utf-8")
    if "moz/context.sys.mjs" not in rtext:
        old = '''  proxy:
    "chrome://remote/content/webdriver-bidi/modules/root/moz/proxy.sys.mjs",
});'''
        new = '''  proxy:
    "chrome://remote/content/webdriver-bidi/modules/root/moz/proxy.sys.mjs",
  context:
    "chrome://remote/content/webdriver-bidi/modules/root/moz/context.sys.mjs",
});'''
        if old not in rtext:
            raise SystemExit("ModuleRegistry.sys.mjs: moz proxy block not found")
        reg.write_text(rtext.replace(old, new, 1), encoding="utf-8")
    print("== moz:context module registered ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
