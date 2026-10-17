#!/usr/bin/env python3
"""BiDi input: mark synthesized widget events as real-user (isSynthesized=false).

Vanilla EventUtils defaults isDOMEventSynthesized=true. That does NOT clear
Event.isTrusted (widget ctor still trusted=true), but it sets the test-only
Event.isSynthesized flag. BiDi clicks should look like OS input:
  isTrusted=true, isSynthesized=false.

Page JS Event / dispatchEvent is not touched — real Firefox logic.
Usage: python3 scripts/patch_input_trusted.py <firefox-src>
"""
from pathlib import Path
import sys

MARKER = "BROWSER_CONTEXT_BIDI_TRUSTED"

OLD = """event.synthesizeMouseAtPoint = function (left, top, event, win) {
  if (!event.asyncEnabled) {
    return Promise.resolve(
      _getEventUtils(win).synthesizeMouseAtPoint(left, top, event, win)
    );
  }
"""

NEW = """event.synthesizeMouseAtPoint = function (left, top, event, win) {
  // BROWSER_CONTEXT_BIDI_TRUSTED: widget path stays isTrusted=true (Firefox
  // default for sendMouseEvent). Only clear the test isSynthesized flag.
  event = Object.assign({}, event, { isSynthesized: false });
  if (!event.asyncEnabled) {
    return Promise.resolve(
      _getEventUtils(win).synthesizeMouseAtPoint(left, top, event, win)
    );
  }
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_input_trusted.py <firefox-src>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]) / "remote" / "shared" / "webdriver" / "Event.sys.mjs"
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print("== BiDi input trusted marker already present ==")
        return 0
    if OLD not in text:
        print("!! Event.sys.mjs: synthesizeMouseAtPoint block not found", file=sys.stderr)
        return 1
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("patched", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
