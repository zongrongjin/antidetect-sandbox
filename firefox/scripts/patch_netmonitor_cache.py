#!/usr/bin/env python3
"""Add the cache-rules sidebar and row colors to Firefox netmonitor.

Usage: patch_netmonitor_cache.py <firefox-src>
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PANEL = HERE / "patches" / "devtools" / "CacheRulesPanel.js"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print("== already", label)
        return
    if old not in text:
        raise SystemExit(f"{path}: anchor missing for {label}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("== patched", label)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_netmonitor_cache.py <firefox-src>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dest = (
        src
        / "devtools"
        / "client"
        / "netmonitor"
        / "src"
        / "components"
        / "CacheRulesPanel.js"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PANEL, dest)

    replace_once(
        src / "devtools/server/actors/network-monitor/network-event-actor.js",
        "      proxyStatusText: proxyInfo[2],\n    });",
        """      proxyStatusText: proxyInfo[2],
      contextCacheAction: readContextCacheAction(channel),
    });""",
        "response event",
    )
    actor = src / "devtools/server/actors/network-monitor/network-event-actor.js"
    actor_text = actor.read_text(encoding="utf-8")
    helper = """
function readContextCacheAction(channel) {
  try {
    return channel
      .QueryInterface(Ci.nsIPropertyBag2)
      .getPropertyAsAString("moz-context-cache-action");
  } catch (e) {
    return "";
  }
}
"""
    if "function readContextCacheAction" not in actor_text:
        actor.write_text(helper + actor_text, encoding="utf-8")

    replace_once(
        src / "devtools/client/netmonitor/src/constants.js",
        '  "fromCache",\n',
        '  "fromCache",\n  "contextCacheAction",\n',
        "request field",
    )
    replace_once(
        src / "devtools/client/netmonitor/src/components/request-list/RequestListItem.js",
        '  "fromCache",\n',
        '  "fromCache",\n  "contextCacheAction",\n',
        "row props",
    )
    replace_once(
        src / "devtools/client/netmonitor/src/components/request-list/RequestListItem.js",
        '    fromCache && classList.push("fromCache");\n',
        """    fromCache && classList.push("fromCache");
    if (item.contextCacheAction) {
      classList.push("zz-cache-" + item.contextCacheAction);
    }
""",
        "row class",
    )
    css = src / "devtools/client/netmonitor/src/assets/styles/RequestList.css"
    extra = """
.request-list-item.zz-cache-hit .requests-list-file,
.request-list-item.zz-cache-html .requests-list-file { color: #0b7a32; }
.request-list-item.zz-cache-store .requests-list-file { color: #b36b00; }
.request-list-item.zz-cache-block .requests-list-file { color: #b00020; }
.request-list-item.zz-cache-allow-miss .requests-list-file { color: #666; }
.request-list-item.zz-cache-observe .requests-list-file { color: #1554b3; }
.request-list-item.zz-cache-capture .requests-list-file,
.request-list-item.zz-cache-callback .requests-list-file { color: #6b3fa0; }
.zz-cache-rules { padding: 4px 8px; border-bottom: 1px solid var(--theme-splitter-color, #ccc); }
.zz-cache-body { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.zz-cache-bar, .zz-cache-rule, .zz-cache-dialog { display: flex; gap: 6px; align-items: center; }
.zz-cache-pattern { flex: 1; overflow: hidden; text-overflow: ellipsis; }
.zz-cache-rule.off { opacity: 0.55; }
.zz-cache-error { color: #b00020; }
.zz-cache-file { min-height: 48px; }
"""
    css_text = css.read_text(encoding="utf-8")
    if ".zz-cache-hit" not in css_text:
        css.write_text(css_text + extra, encoding="utf-8")

    moz = src / "devtools/client/netmonitor/src/components/moz.build"
    replace_once(
        moz,
        '    "App.js",\n',
        '    "App.js",\n    "CacheRulesPanel.js",\n',
        "moz.build",
    )
    panel = src / "devtools/client/netmonitor/src/components/MonitorPanel.js"
    replace_once(
        panel,
        """const Toolbar = createFactory(
  require("resource://devtools/client/netmonitor/src/components/Toolbar.js")
);""",
        """const Toolbar = createFactory(
  require("resource://devtools/client/netmonitor/src/components/Toolbar.js")
);
const CacheRulesPanel = createFactory(
  require("resource://devtools/client/netmonitor/src/components/CacheRulesPanel.js")
);""",
        "panel import",
    )
    replace_once(
        panel,
        """      Toolbar({
        actions,
        connector,
        openSplitConsole,
        singleRow: this.state.isSingleRow,
        toolboxDoc,
      }),""",
        """      Toolbar({
        actions,
        connector,
        openSplitConsole,
        singleRow: this.state.isSingleRow,
        toolboxDoc,
      }),
      CacheRulesPanel({ connector }),""",
        "panel mount",
    )
    print("== netmonitor cache rules patched ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
