/* BROWSER_FINGERPRINT
 *
 * moz:fingerprint windowglobal module.
 *
 * Native, page-invisible closed-shadow piercing for deep element location.
 *
 * This module runs in the content process with a system principal, so it can
 * read `el.openOrClosedShadowRoot` -- a chrome-only property that pierces
 * *closed* shadow roots. Page scripts cannot access this property, and
 * Element.prototype.attachShadow stays 100% native (no monkey-patch), so the
 * previous detection surface (attachShadow.toString() no longer [native code],
 * closed shadowRoot leaking to the page) is completely gone.
 */
import { WindowGlobalBiDiModule } from "chrome://remote/content/webdriver-bidi/modules/WindowGlobalBiDiModule.sys.mjs";

const lazy = {};

ChromeUtils.defineESModuleGetters(lazy, {
  dom: "chrome://remote/content/shared/DOM.sys.mjs",
  OwnershipModel: "chrome://remote/content/webdriver-bidi/RemoteValue.sys.mjs",
  setDefaultAndAssertSerializationOptions:
    "chrome://remote/content/webdriver-bidi/RemoteValue.sys.mjs",
});

class FingerprintModule extends WindowGlobalBiDiModule {
  constructor(messageHandler) {
    super(messageHandler);
  }

  destroy() {}

  /**
   * Return the open OR closed shadow root of an element, using the chrome-only
   * `openOrClosedShadowRoot` property (invisible to page scripts). Returns null
   * when the element has no usable shadow root.
   */
  #shadowRootOf(el) {
    try {
      const sr = el.openOrClosedShadowRoot;
      if (sr && !sr.isUAWidget()) {
        return sr;
      }
    } catch (e) {
      // openOrClosedShadowRoot can throw for some nodes; treat as "no shadow".
    }
    return null;
  }

  /**
   * Recursively query `selector` within `root` (a Document or ShadowRoot),
   * descending into every element's open/closed shadow root. Returns the first
   * matching Element, or null.
   */
  #deepQuery(root, selector) {
    let el;
    try {
      el = root.querySelector(selector);
    } catch (e) {
      // Invalid selector -> no match (do not throw across the wire).
      return null;
    }
    if (el) {
      return el;
    }
    const all = root.querySelectorAll("*");
    for (let i = 0; i < all.length; i++) {
      const sr = this.#shadowRootOf(all[i]);
      if (sr) {
        const found = this.#deepQuery(sr, selector);
        if (found) {
          return found;
        }
      }
    }
    return null;
  }

  /**
   * Locate the first element matching `selector` in this window global,
   * piercing (open and closed) shadow roots. Returns the element's viewport
   * rectangle and a serialized node reference (sharedId) so the client can
   * drive it later, or `{ found: false }` when nothing matches.
   *
   * @param {object=} params
   * @param {string} params.selector
   *     CSS selector to look up.
   */
  async _deepLocate(params = {}) {
    const { selector } = params;
    const doc = this.messageHandler.window.document;
    const el = this.#deepQuery(doc, selector);
    if (!el) {
      return { found: false, rect: null, node: null };
    }

    const r = el.getBoundingClientRect();
    const rect = { x: r.x, y: r.y, width: r.width, height: r.height };

    // Serialize the node so find(deep=True) can build an Element handle and
    // drive it later via sharedId. OwnershipModel.None is enough: the node
    // remains resolvable by sharedId while it lives in the DOM.
    let node = null;
    try {
      const realm = this.messageHandler.getRealm();
      const serializationOptions =
        lazy.setDefaultAndAssertSerializationOptions({});
      node = this.serialize(
        el,
        serializationOptions,
        lazy.OwnershipModel.None,
        realm,
        { seenNodeIds: new Map() }
      );
    } catch (e) {
      node = null;
    }

    return { found: true, rect, node };
  }

  /**
   * Viewport rectangles ({x, y}) of every <iframe> element in this window
   * global, including iframes nested inside open/closed shadow roots, in DOM
   * order. The root module uses these offsets to translate child browsing
   * context coordinates into the top-level viewport for cross-frame deep
   * location.
   */
  async _iframeRects() {
    const doc = this.messageHandler.window.document;
    const out = [];
    const collect = root => {
      const frames = root.querySelectorAll("iframe");
      for (let i = 0; i < frames.length; i++) {
        const fr = frames[i].getBoundingClientRect();
        out.push({ x: fr.x, y: fr.y });
      }
      const all = root.querySelectorAll("*");
      for (let j = 0; j < all.length; j++) {
        const sr = this.#shadowRootOf(all[j]);
        if (sr) {
          collect(sr);
        }
      }
    };
    collect(doc);
    return { rects: out };
  }
}

export const fingerprint = FingerprintModule;
