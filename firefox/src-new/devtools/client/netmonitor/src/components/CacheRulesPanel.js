/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

const {
  Component,
} = require("resource://devtools/client/shared/vendor/react.mjs");
const {
  button,
  div,
  input,
  label,
  option,
  select,
  textarea,
} = require("resource://devtools/client/shared/vendor/react-dom-factories.js");

const MODULE =
  "chrome://remote/content/webdriver-bidi/modules/root/moz/context.sys.mjs";

function cacheApi() {
  return ChromeUtils.importESModule(MODULE);
}

function userContextId(connector) {
  try {
    const browser = connector.toolbox.target.localTab.linkedBrowser;
    return browser.browsingContext.originAttributes.userContextId || 0;
  } catch (e) {
    return 0;
  }
}

function itemsFromRules(rules) {
  if (rules && Array.isArray(rules.items) && rules.items.length) {
    return rules.items.map(item => ({
      kind: item.kind === "exclude" ? "exclude" : "include",
      pattern: item.pattern || "",
      enabled: item.enabled !== false,
      ttl: item.ttl == null ? "0" : String(item.ttl),
      maxEntry: item.maxEntry == null ? "10485760" : String(item.maxEntry),
      cacheableStatus: Array.isArray(item.cacheableStatus)
        ? item.cacheableStatus.join(",")
        : item.cacheableStatus || "",
    }));
  }
  const out = [];
  for (const pattern of (rules && rules.include) || []) {
    out.push({
      kind: "include",
      pattern,
      enabled: true,
      ttl: rules.ttl == null ? "0" : String(rules.ttl),
      maxEntry: rules.maxEntry == null ? "10485760" : String(rules.maxEntry),
      cacheableStatus: Array.isArray(rules.cacheableStatus)
        ? rules.cacheableStatus.join(",")
        : "",
    });
  }
  for (const pattern of (rules && rules.exclude) || []) {
    out.push({
      kind: "exclude",
      pattern,
      enabled: true,
      ttl: "0",
      maxEntry: "10485760",
      cacheableStatus: "",
    });
  }
  return out;
}

function rulesFromItems(items) {
  const enabled = items.filter(item => item.enabled && item.pattern);
  const statusOf = text =>
    String(text || "")
      .split(",")
      .map(part => Number(part.trim()))
      .filter(n => Number.isFinite(n));
  return {
    include: enabled.filter(item => item.kind === "include").map(item => item.pattern),
    exclude: enabled.filter(item => item.kind === "exclude").map(item => item.pattern),
    items: items
      .filter(item => item.pattern)
      .map(item => ({
        kind: item.kind,
        pattern: item.pattern,
        enabled: !!item.enabled,
        ttl: Number(item.ttl) || 0,
        maxEntry: item.maxEntry === "" ? 10485760 : Number(item.maxEntry),
        cacheableStatus: statusOf(item.cacheableStatus),
      })),
  };
}

class CacheRulesPanel extends Component {
  static get propTypes() {
    return {};
  }

  constructor(props) {
    super(props);
    this.state = {
      open: false,
      dialog: false,
      items: [],
      dir: "",
      error: "",
      pattern: "",
      kind: "include",
      ttl: "0",
      maxEntry: "10485760",
      status: "",
    };
  }

  componentDidMount() {
    this.reload();
  }

  reload() {
    try {
      const uid = userContextId(this.props.connector);
      const net = cacheApi().readContextNet(uid);
      this.setState({
        dir: net.dir || "",
        items: itemsFromRules(net.rules),
        error: "",
      });
    } catch (e) {
      this.setState({ error: String(e) });
    }
  }

  persist(items) {
    const uid = userContextId(this.props.connector);
    const rules = rulesFromItems(items);
    const net = cacheApi().writeContextNet(uid, {
      dir: this.state.dir,
      rules,
    });
    this.setState({ items, dir: net.dir || "", error: "" });
  }

  toggleAll() {
    const on = this.state.items.some(item => !item.enabled);
    this.persist(this.state.items.map(item => ({ ...item, enabled: on })));
  }

  deleteChecked() {
    this.persist(this.state.items.filter(item => !item.enabled));
  }

  addRule() {
    const pattern = this.state.pattern.trim();
    if (!pattern) {
      this.setState({ error: "模式不能为空" });
      return;
    }
    const items = this.state.items.concat({
      kind: this.state.kind,
      pattern,
      enabled: true,
      ttl: this.state.ttl || "0",
      maxEntry: this.state.maxEntry || "10485760",
      cacheableStatus: this.state.status,
    });
    this.persist(items);
    this.setState({ dialog: false, pattern: "", status: "" });
  }

  exportJson() {
    const rules = rulesFromItems(this.state.items);
    const blob = {
      cache: {
        dir: this.state.dir,
        map: {},
        rules: JSON.stringify(rules),
      },
    };
    const text = JSON.stringify(blob, null, 2);
    const input = this.fileInput;
    if (!input) {
      return;
    }
    input.value = text;
    input.select();
  }

  importJson() {
    let parsed;
    try {
      parsed = JSON.parse(this.fileInput.value);
    } catch (e) {
      this.setState({ error: "JSON 无法解析" });
      return;
    }
    const cache = parsed.cache || parsed;
    const rules =
      typeof cache.rules === "string" ? JSON.parse(cache.rules) : cache.rules || {};
    this.setState({ dir: cache.dir || "" }, () => this.persist(itemsFromRules(rules)));
  }

  render() {
    const { open, dialog, items, error } = this.state;
    return div(
      { className: "zz-cache-rules" },
      button(
        {
          className: "devtools-button",
          onClick: () => this.setState({ open: !open }),
        },
        open ? "收起缓存规则" : "缓存规则"
      ),
      open &&
        div(
          { className: "zz-cache-body" },
          div(
            { className: "zz-cache-bar" },
            button(
              { className: "devtools-button", onClick: () => this.setState({ dialog: true }) },
              "新建规则"
            ),
            button({ className: "devtools-button", onClick: () => this.toggleAll() }, "全选"),
            button({ className: "devtools-button", onClick: () => this.deleteChecked() }, "删除已勾选"),
            button({ className: "devtools-button", onClick: () => this.exportJson() }, "导出"),
            button({ className: "devtools-button", onClick: () => this.importJson() }, "导入")
          ),
          error ? div({ className: "zz-cache-error" }, error) : null,
          textarea({
            className: "zz-cache-file",
            ref: node => {
              this.fileInput = node;
            },
            placeholder: "导入或导出 {cache:{dir,map,rules}}",
          }),
          items.map((item, index) =>
            div(
              { className: "zz-cache-rule" + (item.enabled ? "" : " off"), key: index },
              input({
                type: "checkbox",
                checked: item.enabled,
                onChange: () => {
                  const next = items.slice();
                  next[index] = { ...item, enabled: !item.enabled };
                  this.persist(next);
                },
              }),
              div({ className: "zz-cache-tag " + item.kind }, item.kind),
              div(
                { className: "zz-cache-pattern" },
                item.pattern +
                  " · ttl " +
                  item.ttl +
                  " · max " +
                  item.maxEntry +
                  (item.cacheableStatus ? " · " + item.cacheableStatus : "")
              ),
              button(
                {
                  className: "devtools-button",
                  onClick: () => this.persist(items.filter((_, i) => i !== index)),
                },
                "删除"
              )
            )
          ),
          dialog &&
            div(
              { className: "zz-cache-dialog" },
              textarea({
                value: this.state.pattern,
                placeholder: "*.js",
                onChange: event => this.setState({ pattern: event.target.value }),
              }),
              select(
                {
                  value: this.state.kind,
                  onChange: event => this.setState({ kind: event.target.value }),
                },
                option({ value: "include" }, "include"),
                option({ value: "exclude" }, "exclude")
              ),
              label(
                null,
                "ttl ",
                input({
                  value: this.state.ttl,
                  onChange: event => this.setState({ ttl: event.target.value }),
                })
              ),
              label(
                null,
                "maxEntry ",
                input({
                  value: this.state.maxEntry,
                  onChange: event => this.setState({ maxEntry: event.target.value }),
                })
              ),
              label(
                null,
                "status ",
                input({
                  value: this.state.status,
                  placeholder: "200,304",
                  onChange: event => this.setState({ status: event.target.value }),
                })
              ),
              button({ className: "devtools-button", onClick: () => this.addRule() }, "配置"),
              button(
                {
                  className: "devtools-button",
                  onClick: () => this.setState({ dialog: false }),
                },
                "取消"
              )
            )
        )
    );
  }
}

module.exports = CacheRulesPanel;
