/* BROWSER_CONTEXT */
import { RootBiDiModule } from "chrome://remote/content/webdriver-bidi/modules/RootBiDiModule.sys.mjs";

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  assert: "chrome://remote/content/shared/webdriver/Assert.sys.mjs",
  NavigableManager:
    "chrome://remote/content/shared/NavigableManager.sys.mjs",
  pprint: "chrome://remote/content/shared/Format.sys.mjs",
  RootMessageHandler:
    "chrome://remote/content/shared/messagehandler/RootMessageHandler.sys.mjs",
  UserContextManager:
    "chrome://remote/content/shared/UserContextManager.sys.mjs",
});

const { TRANSPARENT_PROXY_RESOLVES_HOST } = Ci.nsIProxyInfo;

// internalUserContextId -> { type, host, port, username, password }
const gProxyByUserContext = new Map();

// internalUserContextId -> { dir, map, rules, docUrl, docHtml }
const gNetByUserContext = new Map();

let gProxyService = null;
function proxyService() {
  if (!gProxyService) {
    gProxyService = Cc[
      "@mozilla.org/network/protocol-proxy-service;1"
    ].getService(Ci.nsIProtocolProxyService);
  }
  return gProxyService;
}

const gFilter = {
  QueryInterface: ChromeUtils.generateQI(["nsIProtocolProxyChannelFilter"]),
  applyFilter(channel, defaultProxyInfo, callback) {
    let pi = defaultProxyInfo;
    try {
      const uid = channel.loadInfo?.originAttributes?.userContextId ?? 0;
      const o = gProxyByUserContext.get(uid);
      if (o) {
        pi = proxyService().newProxyInfoWithAuth(
          o.type,
          o.host,
          o.port,
          o.username,
          o.password,
          "",
          "",
          TRANSPARENT_PROXY_RESOLVES_HOST,
          -1,
          null
        );
      }
    } catch (e) {
      pi = defaultProxyInfo;
    }
    callback.onProxyFilterResult(pi);
  },
};

let gRegistered = false;
function ensureRegistered() {
  if (!gRegistered) {
    proxyService().registerChannelFilter(gFilter, 0);
    gRegistered = true;
  }
}

function parseEndpoint(endpoint) {
  let type = "http";
  let rest = endpoint;
  const m = /^([a-zA-Z0-9]+):\/\/(.*)$/.exec(endpoint);
  if (m) {
    const scheme = m[1].toLowerCase();
    rest = m[2];
    if (scheme === "socks5" || scheme === "socks") {
      type = "socks";
    } else if (scheme === "socks4") {
      type = "socks4";
    } else if (scheme === "https") {
      type = "https";
    } else {
      type = "http";
    }
  }
  const idx = rest.lastIndexOf(":");
  return {
    type,
    host: rest.slice(0, idx),
    port: parseInt(rest.slice(idx + 1), 10),
  };
}

function globToRe(pat) {
  let out = "^";
  for (let i = 0; i < pat.length; i++) {
    const c = pat[i];
    if (c === "*") {
      out += "[\\s\\S]*";
    } else if (c === "?") {
      out += "[\\s\\S]";
    } else {
      out += c.replace(/[|\\{}()[\]^$+.]/g, "\\$&");
    }
  }
  return new RegExp(out + "$");
}

function matchAny(url, pats) {
  if (!pats || !pats.length) {
    return false;
  }
  for (const pat of pats) {
    if (!pat) {
      continue;
    }
    if (pat === url || pat === "*") {
      return true;
    }
    try {
      if (globToRe(pat).test(url)) {
        return true;
      }
    } catch (e) {
      if (url.includes(pat)) {
        return true;
      }
    }
  }
  return false;
}

function listFrom(rules, key) {
  if (!rules || !Array.isArray(rules[key])) {
    return [];
  }
  return rules[key].filter(x => typeof x === "string");
}

function looksLikeSha256Hex(s) {
  return typeof s === "string" && /^[0-9a-fA-F]{64}$/.test(s);
}

function findHitEntry(index, key) {
  if (!index || typeof index !== "object") {
    return null;
  }
  if (index[key]) {
    return index[key];
  }
  if (typeof key === "string" && key.startsWith("POST ")) {
    const sp = key.lastIndexOf(" ");
    if (sp > 5 && looksLikeSha256Hex(key.slice(sp + 1))) {
      const alt = key.slice(0, sp);
      if (index[alt]) {
        return index[alt];
      }
    }
  }
  try {
    const u = new URL(key);
    if (u.hash) {
      u.hash = "";
      if (index[u.href]) {
        return index[u.href];
      }
    }
  } catch (e) {}
  return null;
}

function canonPath(u) {
  u.hash = "";
  let href = u.href;
  if (href.endsWith("/")) {
    href = href.slice(0, -1);
  }
  return href;
}

function documentUrlMatch(request, target) {
  if (!target) {
    return false;
  }
  if (request === target) {
    return true;
  }
  try {
    const a = new URL(request);
    const b = new URL(target);
    if (canonPath(a) === canonPath(b)) {
      return true;
    }
    // Firefox https-first upgrades http:// → https:// before the channel opens.
    if (
      a.host === b.host &&
      a.pathname === b.pathname &&
      a.search === b.search
    ) {
      const schemes = new Set([a.protocol, b.protocol]);
      if (schemes.has("http:") && schemes.has("https:")) {
        return true;
      }
    }
  } catch (e) {
    return false;
  }
  return false;
}

function cacheExcluded(url, rules) {
  const include = listFrom(rules, "include");
  if (include.length && !matchAny(url, include)) {
    return true;
  }
  return matchAny(url, listFrom(rules, "exclude"));
}

function entryExpired(entry, rules) {
  const ttl = rules && Number(rules.ttl) ? Number(rules.ttl) : 0;
  if (ttl <= 0 || !entry || entry.created_at == null) {
    return false;
  }
  return Date.now() / 1000 - Number(entry.created_at) > ttl;
}

function matchAction(url, cacheKey, rules, index) {
  if (matchAny(url, listFrom(rules, "captures"))) {
    return "capture";
  }
  if (matchAny(url, listFrom(rules, "callbacks"))) {
    return "callback";
  }
  const entry = findHitEntry(index, cacheKey);
  if (entry && !cacheExcluded(url, rules) && !entryExpired(entry, rules)) {
    return "hit";
  }
  if (matchAny(url, listFrom(rules, "blocks"))) {
    return "block";
  }
  if (matchAny(url, listFrom(rules, "allowMiss"))) {
    return "allow-miss";
  }
  if (matchAny(url, listFrom(rules, "observe"))) {
    return "observe";
  }
  return "pass";
}

function sha256hex(str) {
  const converter = Cc[
    "@mozilla.org/intl/scriptableunicodeconverter"
  ].createInstance(Ci.nsIScriptableUnicodeConverter);
  converter.charset = "UTF-8";
  const data = converter.convertToByteArray(str);
  const hasher = Cc["@mozilla.org/security/hash;1"].createInstance(
    Ci.nsICryptoHash
  );
  hasher.init(Ci.nsICryptoHash.SHA256);
  hasher.update(data, data.length);
  const raw = hasher.finish(false);
  return Array.from(raw, (_, i) =>
    ("0" + raw.charCodeAt(i).toString(16)).slice(-2)
  ).join("");
}

function parseJsonObject(s, fallback) {
  if (!s) {
    return fallback;
  }
  if (typeof s === "object" && !Array.isArray(s)) {
    return s;
  }
  try {
    const v = JSON.parse(s);
    return v && typeof v === "object" && !Array.isArray(v) ? v : fallback;
  } catch (e) {
    return fallback;
  }
}

function skipHeader(name) {
  const n = String(name).toLowerCase();
  return n === "content-encoding" || n === "content-length" || n === "set-cookie";
}

function netState(uid) {
  if (!gNetByUserContext.has(uid)) {
    gNetByUserContext.set(uid, {
      dir: "",
      map: {},
      rules: {},
      docUrl: "",
      docHtml: "",
    });
  }
  return gNetByUserContext.get(uid);
}

async function loadDiskMap(dir) {
  if (!dir) {
    return {};
  }
  try {
    const path = dir.replace(/\/+$/, "") + "/_map.json";
    const txt = await IOUtils.readUTF8(path);
    return parseJsonObject(txt, {});
  } catch (e) {
    return {};
  }
}

async function saveDiskMap(dir, map) {
  if (!dir) {
    return;
  }
  const path = dir.replace(/\/+$/, "") + "/_map.json";
  await IOUtils.makeDirectory(dir, { ignoreExisting: true });
  await IOUtils.writeUTF8(path, JSON.stringify(map), { tmpPath: path + ".tmp" });
}

function serveOverride(channel, status, reason, headers, body) {
  const replaced = Cc[
    "@mozilla.org/network/replaced-http-response;1"
  ].createInstance(Ci.nsIReplacedHttpResponse);
  replaced.init();
  replaced.responseStatus = status;
  replaced.responseStatusText = reason;
  replaced.responseBody = body || "";
  if (headers) {
    for (const [name, value] of Object.entries(headers)) {
      if (skipHeader(name) || value == null) {
        continue;
      }
      replaced.setResponseHeader(String(name), String(value), true);
    }
  }
  channel.QueryInterface(Ci.nsIHttpChannelInternal).setResponseOverride(replaced);
}

function readUploadBody(channel) {
  try {
    const upload = channel.QueryInterface(Ci.nsIUploadChannel);
    const stream = upload.uploadStream;
    if (!stream) {
      return "";
    }
    const seek = stream.QueryInterface(Ci.nsISeekableStream);
    const pos = seek.tell();
    seek.seek(Ci.nsISeekableStream.NS_SEEK_SET, 0);
    const sis = Cc["@mozilla.org/scriptableinputstream;1"].createInstance(
      Ci.nsIScriptableInputStream
    );
    sis.init(stream);
    const available = sis.available();
    const data = available ? sis.read(available) : "";
    seek.seek(Ci.nsISeekableStream.NS_SEEK_SET, pos);
    return data;
  } catch (e) {
    return "";
  }
}

function cacheKey(method, url, body) {
  const m = String(method || "GET").toUpperCase();
  if (!m || m === "GET" || m === "HEAD") {
    return url;
  }
  let key = m + " " + url;
  if (body) {
    key += " " + sha256hex(body);
  }
  return key;
}

function emitNet(kind, url) {
  try {
    Services.obs.notifyObservers(
      null,
      "zzbrowser-context-" + kind,
      url
    );
  } catch (e) {}
}

function onModifyRequest(subject) {
  let channel;
  try {
    channel = subject.QueryInterface(Ci.nsIHttpChannel);
  } catch (e) {
    return;
  }
  const uid = channel.loadInfo?.originAttributes?.userContextId ?? 0;
  const st = gNetByUserContext.get(uid);
  if (!st) {
    return;
  }
  let url;
  try {
    url = channel.URI.spec;
  } catch (e) {
    return;
  }
  if (st.docHtml && documentUrlMatch(url, st.docUrl)) {
    serveOverride(
      channel,
      200,
      "OK",
      { "Content-Type": "text/html; charset=utf-8" },
      st.docHtml
    );
    return;
  }
  const method = channel.requestMethod;
  const key = cacheKey(method, url, readUploadBody(channel));
  const action = matchAction(url, key, st.rules, st.map);
  if (action === "callback") {
    emitNet("callback", url);
  } else if (action === "observe") {
    emitNet("observe", url);
  } else if (action === "capture") {
    emitNet("capture", url);
  }
  if (action === "hit") {
    const entry = findHitEntry(st.map, key);
    if (!entry) {
      return;
    }
    let body = "";
    if (st.dir && entry.file) {
      const p = entry.file.startsWith("/")
        ? entry.file
        : st.dir.replace(/\/+$/, "") + "/" + entry.file;
      body = readFileSync(p);
    }
    const status = Number(entry.status) || 200;
    serveOverride(channel, status, "OK", entry.headers || {}, body);
    return;
  }
  if (action === "block") {
    try {
      channel.cancel(Cr.NS_BINDING_ABORTED);
    } catch (e) {
      serveOverride(channel, 403, "Forbidden", {}, "");
    }
  }
}

function readFileSync(path) {
  try {
    const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    file.initWithPath(path);
    const fis = Cc["@mozilla.org/network/file-input-stream;1"].createInstance(
      Ci.nsIFileInputStream
    );
    fis.init(file, 0x01, 0o444, 0);
    const sis = Cc["@mozilla.org/scriptableinputstream;1"].createInstance(
      Ci.nsIScriptableInputStream
    );
    sis.init(fis);
    const data = sis.read(sis.available());
    sis.close();
    fis.close();
    return data;
  } catch (e) {
    return "";
  }
}

function statusCacheable(status, rules) {
  if (rules && Array.isArray(rules.cacheableStatus) && rules.cacheableStatus.length) {
    return rules.cacheableStatus.includes(status);
  }
  return status >= 200 && status < 300;
}

function shouldPersist(method, url, dir, action, rules) {
  if (!dir) {
    return false;
  }
  const m = String(method || "").toUpperCase();
  if (m !== "GET" && m !== "POST") {
    return false;
  }
  if (action === "capture" || action === "callback" || action === "block") {
    return false;
  }
  if (action === "allow-miss") {
    return false;
  }
  if (cacheExcluded(url, rules)) {
    return false;
  }
  return true;
}

function collectHeaders(channel) {
  const headers = {};
  try {
    channel.visitResponseHeaders({
      visitHeader(name, value) {
        if (!skipHeader(name)) {
          headers[name] = value;
        }
      },
    });
  } catch (e) {}
  return headers;
}

function persistResponse(channel, st, url, method, action) {
  if (!shouldPersist(method, url, st.dir, action, st.rules)) {
    return;
  }
  let status = 200;
  try {
    status = channel.responseStatus;
  } catch (e) {
    return;
  }
  if (!statusCacheable(status, st.rules)) {
    return;
  }
  let trace;
  try {
    trace = channel.QueryInterface(Ci.nsITraceableChannel);
  } catch (e) {
    return;
  }
  const hex = sha256hex(url);
  const rel = hex.slice(0, 2) + "/" + hex;
  const fullDir = st.dir.replace(/\/+$/, "") + "/" + hex.slice(0, 2);
  try {
    IOUtils.makeDirectory(fullDir, { ignoreExisting: true });
  } catch (e) {}
  const fullPath = st.dir.replace(/\/+$/, "") + "/" + rel;
  const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  try {
    file.initWithPath(fullPath);
    file.parent.create(Ci.nsIFile.DIRECTORY_TYPE, 0o755);
  } catch (e) {}
  const fos = Cc["@mozilla.org/network/file-output-stream;1"].createInstance(
    Ci.nsIFileOutputStream
  );
  try {
    fos.init(file, 0x02 | 0x08 | 0x20, 0o644, 0);
  } catch (e) {
    return;
  }
  const tee = Cc["@mozilla.org/network/stream-listener-tee;1"].createInstance(
    Ci.nsIStreamListenerTee
  );
  let old;
  try {
    old = trace.setNewListener(tee);
  } catch (e) {
    fos.close();
    return;
  }
  const headers = collectHeaders(channel);
  const created = Date.now() / 1000;
  const observer = {
    QueryInterface: ChromeUtils.generateQI(["nsIRequestObserver"]),
    onStartRequest() {},
    onStopRequest() {
      try {
        fos.close();
      } catch (e) {}
      st.map[url] = {
        file: rel,
        status,
        headers,
        created_at: created,
      };
      saveDiskMap(st.dir, st.map).catch(() => {});
      if (action === "capture") {
        emitNet("captured", url);
      }
    },
  };
  try {
    tee.init(old, fos, observer);
  } catch (e) {
    try {
      fos.close();
    } catch (e2) {}
  }
}

function onExamineResponse(subject) {
  let channel;
  try {
    channel = subject.QueryInterface(Ci.nsIHttpChannel);
  } catch (e) {
    return;
  }
  const uid = channel.loadInfo?.originAttributes?.userContextId ?? 0;
  const st = gNetByUserContext.get(uid);
  if (!st || !st.dir) {
    return;
  }
  let url;
  try {
    url = channel.URI.spec;
  } catch (e) {
    return;
  }
  const method = channel.requestMethod;
  const key = cacheKey(method, url, "");
  const action = matchAction(url, key, st.rules, st.map);
  persistResponse(channel, st, url, method, action);
}

let gNetHooked = false;
function ensureNetHook() {
  if (gNetHooked) {
    return;
  }
  gNetHooked = true;
  const obs = Services.obs;
  obs.addObserver(onModifyRequest, "http-on-modify-request");
  obs.addObserver(onExamineResponse, "http-on-examine-response");
  obs.addObserver(onExamineResponse, "http-on-examine-cached-response");
}

function sameSiteValue(s) {
  const Cookie = Ci.nsICookie;
  if (s == null || s === "") {
    return Cookie.SAMESITE_UNSET ?? Cookie.SAMESITE_LAX;
  }
  const u = String(s).toLowerCase();
  if (u === "strict") {
    return Cookie.SAMESITE_STRICT;
  }
  if (u === "none") {
    return Cookie.SAMESITE_NONE;
  }
  return Cookie.SAMESITE_LAX;
}

function addCookies(internalId, cookies) {
  const cm = Services.cookies;
  const schemeHttps = Ci.nsICookie.SCHEME_HTTPS ?? 2;
  for (const c of cookies) {
    if (!c || !c.name) {
      continue;
    }
    let host = c.domain || "";
    let path = c.path || "/";
    if (!host && c.url) {
      try {
        const u = new URL(c.url);
        host = u.hostname;
        path = c.path || u.pathname || "/";
      } catch (e) {}
    }
    if (!host) {
      continue;
    }
    if (host.startsWith(".")) {
      // allowed for domain cookies
    }
    const isSession = c.expires == null;
    const expiry = isSession
      ? Date.now() + 86400 * 1000 * 365
      : Number(c.expires) * 1000;
    const originAttributes = { userContextId: internalId };
    const schemeHttp = Ci.nsICookie.SCHEME_HTTP ?? 1;
    const schemeMap = c.secure ? schemeHttps : schemeHttp | schemeHttps;
    try {
      cm.add(
        host,
        path,
        c.name,
        String(c.value ?? ""),
        !!c.secure,
        !!c.httpOnly,
        isSession,
        expiry,
        originAttributes,
        sameSiteValue(c.sameSite),
        schemeMap,
        false
      );
    } catch (e) {}
  }
}

function navigateContexts(contextIds, userContextIds, url) {
  if (!url) {
    return;
  }
  const targets = [];
  if (contextIds && contextIds.length) {
    for (const id of contextIds) {
      try {
        const bc = lazy.NavigableManager.getBrowsingContextById(id);
        if (bc) {
          targets.push(bc);
        }
      } catch (e) {}
    }
  } else if (userContextIds && userContextIds.length) {
    for (const bidiId of userContextIds) {
      const internalId = lazy.UserContextManager.getInternalIdById(bidiId);
      for (const win of Services.wm.getEnumerator("navigator:browser")) {
        const tabs = win.gBrowser?.tabs || [];
        for (const tab of tabs) {
          const bc = tab.linkedBrowser?.browsingContext;
          if (bc && bc.originAttributes.userContextId === internalId) {
            targets.push(bc);
          }
        }
      }
    }
  }
  const uri = Services.io.newURI(url);
  const principal = Services.scriptSecurityManager.getSystemPrincipal();
  for (const bc of targets) {
    try {
      bc.loadURI(uri, {
        triggeringPrincipal: principal,
      });
    } catch (e) {
      try {
        bc.fixupAndLoadURIString(url, { triggeringPrincipal: principal });
      } catch (e2) {}
    }
  }
}

/**
 * moz:context module (root). One setContextOverrides for fingerprint + proxy
 * + cache + cookies + url/html. Fingerprint goes through
 * _configuration/SessionData. Proxy uses nsIProtocolProxyChannelFilter.
 * Cache HIT / fake html use nsIReplacedHttpResponse (HTTP/1.1, no network).
 */
class ContextModule extends RootBiDiModule {
  constructor(messageHandler) {
    super(messageHandler);
  }

  destroy() {}

  /**
   * @param {object=} params
   * @param {string=} params.fingerprint  JSON string; omit to leave unchanged.
   * @param {object=} params.proxy        {endpoint, username, password}
   * @param {object=} params.cache        {dir, map, rules} — map/rules JSON strings
   * @param {Array<object>=} params.cookies
   * @param {string=} params.url
   * @param {string=} params.html
   * @param {Array<string>=} params.contexts
   * @param {Array<string>=} params.userContexts
   */
  async setContextOverrides(params = {}) {
    const {
      fingerprint,
      proxy,
      cache,
      cookies,
      url,
      html,
      contexts: contextIds,
      userContexts: userContextIds = [],
    } = params;

    if (fingerprint !== undefined) {
      lazy.assert.string(
        fingerprint,
        lazy.pprint`Expected "fingerprint" to be a string, got ${fingerprint}`
      );
      await this.messageHandler.handleCommand({
        moduleName: "_configuration",
        commandName: "_applyConfigurationParameters",
        destination: { type: lazy.RootMessageHandler.type },
        params: {
          async: false,
          category: "fingerprint-override",
          contextIds,
          resetValue: "",
          supportsGlobalConfiguration: true,
          userContextIds,
          value: fingerprint,
        },
      });
    }

    if (proxy !== undefined) {
      if (proxy === null || typeof proxy !== "object" || Array.isArray(proxy)) {
        throw new TypeError("Expected proxy to be an object");
      }
      const endpoint = proxy.endpoint ?? "";
      const username = proxy.username ?? "";
      const password = proxy.password ?? "";
      lazy.assert.string(
        endpoint,
        lazy.pprint`Expected "proxy.endpoint" to be a string, got ${endpoint}`
      );
      ensureRegistered();
      const parsed = endpoint ? parseEndpoint(endpoint) : null;
      for (const bidiId of userContextIds) {
        const internalId = lazy.UserContextManager.getInternalIdById(bidiId);
        if (internalId === undefined || internalId === null) {
          continue;
        }
        if (!parsed) {
          gProxyByUserContext.delete(internalId);
        } else {
          gProxyByUserContext.set(internalId, {
            type: parsed.type,
            host: parsed.host,
            port: parsed.port,
            username,
            password,
          });
        }
      }
    }

    const netIds = [];
    for (const bidiId of userContextIds) {
      const internalId = lazy.UserContextManager.getInternalIdById(bidiId);
      if (internalId === undefined || internalId === null) {
        continue;
      }
      netIds.push(internalId);
    }

    if (cache !== undefined) {
      if (cache === null || typeof cache !== "object" || Array.isArray(cache)) {
        throw new TypeError("Expected cache to be an object");
      }
      ensureNetHook();
      const dir = cache.dir ?? "";
      const overlay = parseJsonObject(cache.map, {});
      const rules = parseJsonObject(cache.rules, {});
      for (const uid of netIds) {
        const disk = dir ? await loadDiskMap(dir) : {};
        const st = netState(uid);
        st.dir = dir;
        st.map = Object.assign({}, disk, overlay);
        st.rules = rules;
      }
    }

    if (url !== undefined || html !== undefined) {
      ensureNetHook();
      const navUrl = url ?? "";
      const navHtml = html ?? "";
      for (const uid of netIds) {
        const st = netState(uid);
        st.docUrl = navUrl;
        st.docHtml = navHtml;
      }
    }

    if (cookies !== undefined) {
      if (!Array.isArray(cookies)) {
        throw new TypeError("Expected cookies to be an array");
      }
      for (const uid of netIds) {
        addCookies(uid, cookies);
      }
    }

    if (url) {
      navigateContexts(contextIds, userContextIds, url);
    }

    return {};
  }

  async deepLocate(params = {}) {
    const { selector, context: navigableId } = params;

    lazy.assert.string(
      selector,
      lazy.pprint`Expected "selector" to be a string, got ${selector}`
    );
    lazy.assert.string(
      navigableId,
      lazy.pprint`Expected "context" to be a string, got ${navigableId}`
    );

    const context = this._getNavigable(navigableId);
    const result = await this.#deepLocateRecursive(
      context,
      selector,
      navigableId,
      0,
      0
    );
    return result || { found: false };
  }

  async #deepLocateRecursive(context, selector, bidiId, ox, oy) {
    let res = null;
    try {
      res = await this._forwardToWindowGlobal(
        "_deepLocate",
        context.id,
        { selector },
        { retryOnAbort: true }
      );
    } catch (e) {
      res = null;
    }

    if (res && res.found) {
      const r = res.rect;
      return {
        found: true,
        context: bidiId,
        offset: { x: ox, y: oy },
        local: r,
        rect: {
          x: ox + r.x,
          y: oy + r.y,
          width: r.width,
          height: r.height,
        },
        node: res.node,
      };
    }

    const children = context.children || [];
    if (!children.length) {
      return null;
    }

    let rects = [];
    try {
      const ir = await this._forwardToWindowGlobal(
        "_iframeRects",
        context.id,
        {},
        { retryOnAbort: true }
      );
      rects = (ir && ir.rects) || [];
    } catch (e) {
      rects = [];
    }

    for (let i = 0; i < children.length; i++) {
      const io = rects[i] || { x: 0, y: 0 };
      const childBidiId = lazy.NavigableManager.getIdForBrowsingContext(
        children[i]
      );
      const found = await this.#deepLocateRecursive(
        children[i],
        selector,
        childBidiId,
        ox + io.x,
        oy + io.y
      );
      if (found) {
        return found;
      }
    }

    return null;
  }
}

export const context = ContextModule;
