#!/usr/bin/env python3
"""Apply Context proxy-support sources onto a Chromium 151 tree."""
from __future__ import annotations
import shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC_NEW = HERE / "src-new"

def main():
    src = Path(sys.argv[1])
    proto = src / "content/browser/devtools/protocol"
    shutil.copy2(SRC_NEW / "content/browser/devtools/protocol/context_handler.cc", proto / "context_handler.cc")
    shutil.copy2(SRC_NEW / "content/browser/devtools/protocol/context_handler.h", proto / "context_handler.h")
    shutil.copy2(SRC_NEW / "content/browser/devtools/protocol/context_proxy_support.cc", proto / "context_proxy_support.cc")
    shutil.copy2(SRC_NEW / "content/browser/devtools/protocol/context_proxy_support.h", proto / "context_proxy_support.h")
    shutil.copy2(SRC_NEW / "content/browser/devtools/protocol/context_request_interceptor.cc", proto / "context_request_interceptor.cc")
    shutil.copy2(SRC_NEW / "content/browser/devtools/protocol/context_request_interceptor.h", proto / "context_request_interceptor.h")
    shutil.copy2(
        SRC_NEW / "third_party/blink/public/devtools_protocol/domains/Context.pdl",
        src / "third_party/blink/public/devtools_protocol/domains/Context.pdl",
    )
    gn = src / "content/browser/BUILD.gn"
    g = gn.read_text(encoding="utf-8")
    needle = "devtools/protocol/context_handler.cc"
    extras = []
    if "context_proxy_support.cc" not in g:
        extras.append('    "devtools/protocol/context_proxy_support.cc",\n')
    if "context_request_interceptor.cc" not in g:
        extras.append('    "devtools/protocol/context_request_interceptor.cc",\n')
    gn_dirty = False
    if extras:
        i = g.find(needle)
        if i < 0:
            raise SystemExit("context_handler.cc not in BUILD.gn")
        line_end = g.find("\n", i)
        g = g[: line_end + 1] + "".join(extras) + g[line_end + 1 :]
        gn_dirty = True
        print("BUILD.gn: added", extras)
    if "//third_party/brotli:dec" not in g:
        zlib_dep = '    "//third_party/zlib",\n'
        brotli_dep = '    "//third_party/brotli:dec",\n'
        if zlib_dep in g:
            g = g.replace(zlib_dep, zlib_dep + brotli_dep, 1)
        else:
            deps_i = g.find("  deps = [\n")
            if deps_i < 0:
                raise SystemExit("content/browser BUILD.gn deps missing")
            line_end = g.find("\n", deps_i)
            g = g[: line_end + 1] + brotli_dep + g[line_end + 1 :]
        gn_dirty = True
        print("BUILD.gn: added //third_party/brotli:dec")
    if gn_dirty:
        gn.write_text(g, encoding="utf-8")
    th = src / "content/browser/devtools/protocol/target_handler.cc"
    t = th.read_text(encoding="utf-8")
    inc = '#include "content/browser/devtools/protocol/context_proxy_support.h"\n'
    if inc not in t:
        t = t.replace('#include "content/browser/web_contents/web_contents_impl.h"\n',
                      '#include "content/browser/web_contents/web_contents_impl.h"\n' + inc)
    if "BeginIsolatedProxyContextCreation" not in t:
        old_begin = """  DevToolsManagerDelegate* delegate =
      DevToolsManager::GetInstance()->delegate();
  if (!delegate) {
    callback->sendFailure(
        Response::ServerError("Browser context management is not supported."));
    return;
  }
"""
        new_begin = """  DevToolsManagerDelegate* delegate =
      DevToolsManager::GetInstance()->delegate();
  if (!delegate) {
    callback->sendFailure(
        Response::ServerError("Browser context management is not supported."));
    return;
  }
  BeginIsolatedProxyContextCreation();
"""
        if old_begin not in t:
            raise SystemExit("CreateBrowserContext head missing")
        t = t.replace(old_begin, new_begin, 1)
    if "RegisterIsolatedProxyContext" not in t:
        old = """  if (in_disposeOnDetach.value_or(false)) {
    dispose_on_detach_context_ids_.insert(context->UniqueId());
  }
  callback->sendSuccess(context->UniqueId());
}"""
        new = """  if (in_disposeOnDetach.value_or(false)) {
    dispose_on_detach_context_ids_.insert(context->UniqueId());
  }
  RegisterIsolatedProxyContext(context);
  callback->sendSuccess(context->UniqueId());
}"""
        if old not in t:
            raise SystemExit("CreateBrowserContext tail missing")
        t = t.replace(old, new, 1)
    if "ApplyContextProxyToNetworkParams" not in t:
        needle = "void TargetHandler::ApplyNetworkContextParamsOverrides("
        i = t.find(needle)
        brace = t.find("{", i)
        t = t[: brace + 1] + """
  if (ApplyContextProxyToNetworkParams(browser_context, context_params)) {
    return;
  }
""" + t[brace + 1 :]
    th.write_text(t, encoding="utf-8")
    print("patched target_handler.cc")
    inst = src / "content/browser/devtools/devtools_instrumentation.cc"
    it = inst.read_text(encoding="utf-8")
    iinc = '#include "content/browser/devtools/protocol/context_request_interceptor.h"\n'
    if iinc not in it:
        it = it.replace('#include "content/browser/devtools/protocol/browser_handler.h"\n',
                        '#include "content/browser/devtools/protocol/browser_handler.h"\n' + iinc)
        if iinc not in it:
            # fall back: first include in the file
            nl = it.find('\n#include ')
            it = it[: nl + 1] + iinc + it[nl + 1 :]
    hook = """  had_interceptors |= MaybeInstallContextRequestInterceptor(
      agent_host_, storage_partition_, handler_override);
"""
    if "MaybeInstallContextRequestInterceptor" not in it:
        marker = "  if (!had_interceptors) {\n    return false;\n  }"
        if marker not in it:
            raise SystemExit("instrumentation interceptor tail missing")
        it = it.replace(marker, hook + marker, 1)
    inst.write_text(it, encoding="utf-8")
    print("patched devtools_instrumentation.cc")
    cfgp = src / "content/browser/devtools/protocol_config.json"
    cfg = cfgp.read_text(encoding="utf-8")
    old = '''            {
                "domain": "Context",
                "include": ["setContextOverrides"]
            },'''
    new = '''            {
                "domain": "Context",
                "include": ["setContextOverrides"],
                "async": ["setContextOverrides"]
            },'''
    if '"async": ["setContextOverrides"]' not in cfg:
        if old not in cfg:
            raise SystemExit("protocol_config.json Context block missing")
        cfgp.write_text(cfg.replace(old, new, 1), encoding="utf-8")
        print("protocol_config.json: Context.setContextOverrides async")
    else:
        print("protocol_config.json already async")
    print("== win proxy patch ok ==")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
