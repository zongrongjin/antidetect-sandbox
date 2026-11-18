/* BROWSER_FINGERPRINT */
import { RootBiDiModule } from "chrome://remote/content/webdriver-bidi/modules/RootBiDiModule.sys.mjs";

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  assert: "chrome://remote/content/shared/webdriver/Assert.sys.mjs",
  NavigableManager:
    "chrome://remote/content/shared/NavigableManager.sys.mjs",
  pprint: "chrome://remote/content/shared/Format.sys.mjs",
  RootMessageHandler:
    "chrome://remote/content/shared/messagehandler/RootMessageHandler.sys.mjs",
});

/**
 * moz:fingerprint module (root). Routes the per-context fingerprint profile
 * through the standard _configuration/SessionData machinery so that:
 *  - it can be scoped per browsing context (contexts) or per user context
 *    (userContexts), or applied globally when neither is given, and
 *  - future top-level browsing contexts created within the scope inherit it
 *    (replayed from SessionData via _configuration.#onContextAttached).
 */
class FingerprintModule extends RootBiDiModule {
  constructor(messageHandler) {
    super(messageHandler);
  }

  destroy() {}

  /**
   * Set the fingerprint profile override.
   *
   * @param {object=} params
   * @param {string=} params.fingerprint
   *     Fingerprint profile as a JSON string. Empty string resets the override.
   * @param {Array<string>=} params.contexts
   *     Optional list of top-level browsing context ids to scope to.
   * @param {Array<string>=} params.userContexts
   *     Optional list of user context ids to scope to.
   */
  async setContextOverrides(params = {}) {
    const {
      fingerprint = "",
      contexts: contextIds,
      userContexts: userContextIds,
    } = params;

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

    return {};
  }

  /**
   * Deep-locate the first element matching `selector`, piercing closed shadow
   * DOM (natively, via the windowglobal module) and recursing across child
   * browsing contexts (same-process iframes and cross-origin OOPIFs).
   *
   * Forwards `_deepLocate` to the target context's windowglobal module (see
   * browsingContext.locateNodes for the same forward pattern). On a miss it
   * recurses into each child browsing context, accumulating the child's
   * embedder viewport offset so the returned rectangle is expressed in the
   * top-level (given context) viewport.
   *
   * @param {object=} params
   * @param {string} params.selector
   *     CSS selector to look up.
   * @param {string} params.context
   *     Top-level browsing context (navigable) id to search from.
   *
   * @returns {object}
   *     `{ found:true, context, offset:{x,y}, local:{x,y,width,height},
   *        rect:{x,y,width,height}, node }` where `rect` is the top-level
   *     absolute viewport rectangle, `local` is the rectangle inside the
   *     browsing context where the element was found and `context` is that
   *     context's BiDi id (usable for input.performActions). `{ found:false }`
   *     when nothing matches.
   */
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

export const fingerprint = FingerprintModule;
