/* BROWSER_FINGERPRINT */
import { RootBiDiModule } from "chrome://remote/content/webdriver-bidi/modules/RootBiDiModule.sys.mjs";

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  assert: "chrome://remote/content/shared/webdriver/Assert.sys.mjs",
  pprint: "chrome://remote/content/shared/Format.sys.mjs",
  UserContextManager:
    "chrome://remote/content/shared/UserContextManager.sys.mjs",
});

const { TRANSPARENT_PROXY_RESOLVES_HOST } = Ci.nsIProxyInfo;

const gProxyByUserContext = new Map();

function mozProxyLog(msg) {
  dump("MOZPROXY " + msg + "\n");
  try {
    const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    file.initWithPath("/tmp/moz-proxy.log");
    const fos = Cc["@mozilla.org/network/file-output-stream;1"].createInstance(
      Ci.nsIFileOutputStream
    );
    fos.init(file, 0x02 | 0x08 | 0x10, 0o644, 0);
    const cos = Cc["@mozilla.org/intl/converter-output-stream;1"].createInstance(
      Ci.nsIConverterOutputStream
    );
    cos.init(fos, "UTF-8");
    cos.writeString(Date.now() + " " + msg + "\n");
    cos.close();
  } catch (e) {
    dump("MOZPROXY-LOGFAIL " + e + "\n");
  }
}

let gProxyService = null;
function proxyService() {
  if (!gProxyService) {
    gProxyService = Cc[
      "@mozilla.org/network/protocol-proxy-service;1"
    ].getService(Ci.nsIProtocolProxyService);
  }
  return gProxyService;
}

const PR_UINT32_MAX = 0xffffffff;

function basicProxyAuthorization(username, password) {
  if (!username && !password) {
    return "";
  }
  const bytes = new TextEncoder().encode(
    `${username || ""}:${password || ""}`
  );
  let bin = "";
  for (let i = 0; i < bytes.length; i++) {
    bin += String.fromCharCode(bytes[i]);
  }
  return "Basic " + btoa(bin);
}

function makeProxyInfo(o) {
  const isolationKey = "";
  const flags = TRANSPARENT_PROXY_RESOLVES_HOST;
  const socks = o.type === "socks" || o.type === "socks4";
  if (socks) {
    return proxyService().newProxyInfoWithAuth(
      o.type,
      o.host,
      o.port,
      o.username || "",
      o.password || "",
      "",
      isolationKey,
      flags,
      PR_UINT32_MAX,
      null
    );
  }
  return proxyService().newProxyInfo(
    o.type,
    o.host,
    o.port,
    basicProxyAuthorization(o.username, o.password),
    isolationKey,
    flags,
    PR_UINT32_MAX,
    null
  );
}

const gFilter = {
  QueryInterface: ChromeUtils.generateQI(["nsIProtocolProxyChannelFilter"]),
  applyFilter(channel, defaultProxyInfo, callback) {
    let pi = defaultProxyInfo;
    try {
      const oa = channel.loadInfo?.originAttributes;
      const uid = oa?.userContextId ?? 0;
      const o = gProxyByUserContext.get(uid);
      const spec = channel.URI?.spec || "?";
      mozProxyLog(
        "filter spec=" +
          spec.slice(0, 120) +
          " uid=" +
          uneval(uid) +
          " hit=" +
          !!o +
          " keys=" +
          uneval([...gProxyByUserContext.keys()])
      );
      if (o) {
        const socks = o.type === "socks" || o.type === "socks4";
        const authLen = basicProxyAuthorization(o.username, o.password).length;
        mozProxyLog(
          "makeProxyInfo socks=" +
            socks +
            " type=" +
            o.type +
            " host=" +
            o.host +
            " port=" +
            o.port +
            " user=" +
            o.username +
            " passLen=" +
            String(o.password || "").length +
            " authHdrLen=" +
            authLen
        );
        pi = makeProxyInfo(o);
        mozProxyLog(
          "makeProxyInfo OK host=" +
            (pi && pi.host) +
            " port=" +
            (pi && pi.port) +
            " type=" +
            (pi && pi.type)
        );
      }
    } catch (e) {
      mozProxyLog("filter CATCH " + e + " stack=" + (e && e.stack));
      pi = defaultProxyInfo;
    }
    callback.onProxyFilterResult(pi);
  },
};

const gAuthObserver = {
  observe(subject) {
    try {
      const channel = subject.QueryInterface(Ci.nsIHttpChannel);
      const uid = channel.loadInfo?.originAttributes?.userContextId ?? 0;
      const o = gProxyByUserContext.get(uid);
      if (!o || o.type === "socks" || o.type === "socks4") {
        return;
      }
      const hdr = basicProxyAuthorization(o.username, o.password);
      if (!hdr) {
        return;
      }
      channel.setRequestHeader("Proxy-Authorization", hdr, false);
      const spec = channel.URI?.spec || "?";
      mozProxyLog("obs set Proxy-Authorization spec=" + spec.slice(0, 120) + " uid=" + uid);
    } catch (e) {
      mozProxyLog("obs CATCH " + e);
    }
  },
};

let gRegistered = false;
function ensureRegistered() {
  if (!gRegistered) {
    proxyService().registerChannelFilter(gFilter, 0);
    Services.obs.addObserver(gAuthObserver, "http-on-modify-request");
    mozProxyLog("registered filter + http-on-modify-request observer");
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

class ProxyModule extends RootBiDiModule {
  constructor(messageHandler) {
    super(messageHandler);
  }

  destroy() {}

  async setContextOverrides(params = {}) {
    const {
      endpoint = "",
      username = "",
      password = "",
      userContexts: userContextIds = [],
    } = params;

    lazy.assert.string(
      endpoint,
      lazy.pprint`Expected "endpoint" to be a string, got ${endpoint}`
    );

    ensureRegistered();

    const parsed = endpoint ? parseEndpoint(endpoint) : null;
    mozProxyLog(
      "set endpoint=" +
        uneval(endpoint) +
        " user=" +
        uneval(username) +
        " passLen=" +
        String(password || "").length +
        " bidiIds=" +
        uneval(userContextIds) +
        " parsed=" +
        uneval(parsed)
    );
    for (const bidiId of userContextIds) {
      const internalId = lazy.UserContextManager.getInternalIdById(bidiId);
      mozProxyLog(
        "map bidiId=" +
          uneval(bidiId) +
          " internalId=" +
          uneval(internalId) +
          " typeof=" +
          typeof internalId
      );
      if (internalId === undefined || internalId === null) {
        mozProxyLog("SKIP no internalId for " + uneval(bidiId));
        continue;
      }
      if (!parsed) {
        gProxyByUserContext.delete(internalId);
        mozProxyLog("deleted " + internalId);
      } else {
        gProxyByUserContext.set(internalId, {
          type: parsed.type,
          host: parsed.host,
          port: parsed.port,
          username,
          password,
        });
        mozProxyLog(
          "SET key=" +
            uneval(internalId) +
            " keysNow=" +
            uneval([...gProxyByUserContext.keys()])
        );
      }
    }

    return {};
  }
}

export const proxy = ProxyModule;
