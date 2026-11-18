// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/* eslint-disable @devtools/no-imperative-dom-api */

import * as SDK from '../../core/sdk/sdk.js';
import * as UI from '../../ui/legacy/legacy.js';

import cacheRulesViewStyles from './cacheRulesView.css.js';
import type {NetworkLogView} from './NetworkLogView.js';

const DEFAULT_MAX_ENTRY = 10 * 1024 * 1024;
type RuleKind = 'include'|'exclude';

interface RuleItem {
  id: string;
  pattern: string;
  kind: RuleKind;
  enabled: boolean;
  ttl: number;
  maxEntry: number;
  cacheableStatus: number[];
}

interface ContextAgent {
  invoke_getCacheState(params: object): Promise<{
    dir?: string,
    rules?: string,
    map?: string,
    getError?: () => string | undefined,
  }>;
  invoke_explainCache(params: object): Promise<{
    results?: Array<{url?: string, method?: string, action?: string}>,
    getError?: () => string | undefined,
  }>;
  invoke_setContextOverrides(params: object): Promise<{getError?: () => string | undefined}>;
}

const EXTRA_KEYS = ['captures', 'callbacks', 'blocks', 'allowMiss', 'observe'];

export class CacheRulesView extends UI.Widget.VBox implements SDK.TargetManager.Observer {
  readonly #logView: NetworkLogView;
  readonly #list: HTMLElement;
  readonly #empty: HTMLElement;
  readonly #selectAll: HTMLInputElement;
  readonly #deleteSelected: HTMLButtonElement;
  readonly #mask: HTMLElement;
  readonly #pattern: HTMLTextAreaElement;
  readonly #kind: HTMLSelectElement;
  readonly #ttl: HTMLInputElement;
  readonly #maxEntry: HTMLInputElement;
  readonly #statuses: HTMLInputElement;
  readonly #limitError: HTMLElement;
  readonly #error: HTMLElement;
  readonly #dispatcher = {
    cacheDecision: (params: {requestId?: string, url?: string, action?: string}): void => {
      this.#onDecision(params.requestId || '', params.url || '', params.action || '');
    },
  };
  #rules: RuleItem[] = [];
  #dir = '';
  #map = '{}';
  #extra: Record<string, unknown> = {};
  #pendingById = new Map<string, string>();
  #pendingByUrl = new Map<string, string>();
  #listening = false;
  #loaded = false;

  constructor(logView: NetworkLogView) {
    super();
    this.#logView = logView;
    this.element.classList.add('zz-cache-rules');
    this.registerRequiredCSS(cacheRulesViewStyles);

    const bar = this.element.createChild('div', 'zz-cache-bar');
    const add = bar.createChild('button', 'zz-cache-add') as HTMLButtonElement;
    add.textContent = '+ 新建规则';
    add.addEventListener('click', () => this.#openDialog());

    const tools = this.element.createChild('div', 'zz-cache-tools');
    const selectLabel = tools.createChild('label', 'zz-cache-check');
    this.#selectAll = selectLabel.createChild('input') as HTMLInputElement;
    this.#selectAll.type = 'checkbox';
    selectLabel.appendChild(document.createTextNode('全选规则'));
    this.#selectAll.addEventListener('change', () => {
      void this.#toggleAll(this.#selectAll.checked);
    });
    this.#deleteSelected = tools.createChild('button', 'zz-cache-danger') as HTMLButtonElement;
    this.#deleteSelected.textContent = '删除规则';
    this.#deleteSelected.addEventListener('click', () => {
      void this.#deleteChecked();
    });
    const exportButton = tools.createChild('button') as HTMLButtonElement;
    exportButton.textContent = '导出';
    exportButton.addEventListener('click', () => this.#export());
    const importButton = tools.createChild('button') as HTMLButtonElement;
    importButton.textContent = '导入';
    const file = tools.createChild('input') as HTMLInputElement;
    file.type = 'file';
    file.accept = 'application/json,.json';
    file.classList.add('zz-cache-file');
    importButton.addEventListener('click', () => file.click());
    file.addEventListener('change', () => {
      const picked = file.files && file.files[0];
      file.value = '';
      if (picked) {
        void this.#import(picked);
      }
    });

    this.#error = this.element.createChild('div', 'zz-cache-error');
    this.#empty = this.element.createChild('div', 'zz-cache-empty');
    this.#empty.textContent = '还没有规则';
    this.#list = this.element.createChild('div', 'zz-cache-list');

    this.#mask = this.element.createChild('div', 'zz-cache-mask');
    const dialog = this.#mask.createChild('div', 'zz-cache-dialog');
    const title = dialog.createChild('div', 'zz-cache-dialog-title');
    title.textContent = '新建规则';
    const row = dialog.createChild('div', 'zz-cache-dialog-row');
    this.#pattern = row.createChild('textarea') as HTMLTextAreaElement;
    this.#pattern.placeholder = '例如 *.js';
    this.#kind = row.createChild('select') as HTMLSelectElement;
    for (const value of ['include', 'exclude'] as const) {
      const option = this.#kind.createChild('option') as HTMLOptionElement;
      option.value = value;
      option.textContent = value;
    }
    const limits = dialog.createChild('div', 'zz-cache-limits');
    this.#ttl = this.#limitInput(limits, 'ttl 秒，0 为不过期', '0');
    this.#maxEntry = this.#limitInput(limits, 'maxEntry 字节，默认 10MB，0 为不限制', String(DEFAULT_MAX_ENTRY));
    this.#statuses = this.#limitInput(limits, 'cacheableStatus，逗号分隔。空着表示所有 2xx', '200');
    this.#limitError = limits.createChild('div', 'zz-cache-error');
    const actions = dialog.createChild('div', 'zz-cache-dialog-actions');
    const cancel = actions.createChild('button') as HTMLButtonElement;
    cancel.type = 'button';
    cancel.textContent = '取消';
    cancel.addEventListener('click', () => this.cancel());
    const submit = actions.createChild('button', 'zz-cache-add') as HTMLButtonElement;
    submit.type = 'button';
    submit.textContent = '配置';
    submit.addEventListener('click', () => {
      void this.#addRule();
    });

    this.#ensureListening();
    this.#render();
  }

  override wasShown(): void {
    super.wasShown();
    this.#ensureListening();
    void this.#load();
  }

  cancel(): void {
    this.#mask.classList.remove('show');
  }

  targetAdded(target: SDK.Target.Target): void {
    target.registerContextDispatcher(this.#dispatcher);
  }

  targetRemoved(target: SDK.Target.Target): void {
    target.unregisterContextDispatcher(this.#dispatcher);
  }

  #limitInput(parent: HTMLElement, label: string, value: string): HTMLInputElement {
    const field = parent.createChild('label', 'zz-cache-limit');
    field.createChild('span').textContent = label;
    const input = field.createChild('input') as HTMLInputElement;
    input.type = 'text';
    input.value = value;
    return input;
  }

  #ensureListening(): void {
    if (this.#listening) {
      return;
    }
    this.#listening = true;
    const manager = SDK.TargetManager.TargetManager.instance();
    manager.observeTargets(this);
    manager.addModelListener(
        SDK.NetworkManager.NetworkManager, SDK.NetworkManager.Events.RequestStarted, () => this.#flushPending(), this);
    manager.addModelListener(
        SDK.NetworkManager.NetworkManager, SDK.NetworkManager.Events.RequestFinished, () => this.#flushPending(), this);
  }

  #agent(): ContextAgent|null {
    const manager = SDK.TargetManager.TargetManager.instance();
    const target = manager.scopeTarget() || manager.primaryPageTarget();
    if (!target) {
      return null;
    }
    try {
      return target.contextAgent() as ContextAgent;
    } catch {
      return null;
    }
  }

  async #load(): Promise<void> {
    const agent = this.#agent();
    if (!agent) {
      this.#error.textContent = '当前目标没有 Context 域。';
      return;
    }
    const state = await agent.invoke_getCacheState({});
    const error = state.getError?.();
    if (error) {
      this.#error.textContent = error;
      return;
    }
    this.#dir = state.dir || '';
    this.#map = state.map || '{}';
    this.#readRules(state.rules || '');
    this.#loaded = true;
    this.#error.textContent = '';
    this.#render();
  }

  #readRules(text: string): void {
    this.#extra = {};
    this.#rules = [];
    if (!text) {
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text) as Record<string, unknown>;
    } catch {
      this.#error.textContent = '现有 rules 不是 JSON 对象。';
      return;
    }
    const fallbackTtl = typeof parsed['ttl'] === 'number' ? parsed['ttl'] : 0;
    const fallbackMax = typeof parsed['maxEntry'] === 'number' ? parsed['maxEntry'] : DEFAULT_MAX_ENTRY;
    const fallbackStatus = Array.isArray(parsed['cacheableStatus']) ?
        parsed['cacheableStatus'].filter(item => typeof item === 'number') as number[] :
        [200];
    for (const key of EXTRA_KEYS) {
      if (Array.isArray(parsed[key])) {
        this.#extra[key] = parsed[key];
      }
    }
    if (Array.isArray(parsed['items'])) {
      this.#rules = this.#clean(parsed['items'], fallbackTtl, fallbackMax, fallbackStatus);
      return;
    }
    let n = 0;
    const add = (patterns: unknown, kind: RuleKind): void => {
      if (!Array.isArray(patterns)) {
        return;
      }
      for (const pattern of patterns) {
        if (typeof pattern !== 'string' || !pattern.trim()) {
          continue;
        }
        this.#rules.push({
          id: String(Date.now()) + n,
          pattern: pattern.trim(),
          kind,
          enabled: true,
          ttl: fallbackTtl,
          maxEntry: fallbackMax,
          cacheableStatus: fallbackStatus.slice(),
        });
        n += 1;
      }
    };
    add(parsed['include'], 'include');
    add(parsed['exclude'], 'exclude');
  }

  #clean(items: unknown[], ttl: number, maxEntry: number, statuses: number[]): RuleItem[] {
    const rules: RuleItem[] = [];
    for (const item of items) {
      if (!item || typeof item !== 'object') {
        continue;
      }
      const record = item as {
        pattern?: unknown,
        kind?: unknown,
        enabled?: unknown,
        id?: unknown,
        ttl?: unknown,
        maxEntry?: unknown,
        cacheableStatus?: unknown,
      };
      if (record.kind !== 'include' && record.kind !== 'exclude') {
        continue;
      }
      const value = String(record.pattern || '').trim();
      if (!value) {
        continue;
      }
      rules.push({
        id: String(record.id || Date.now() + rules.length),
        pattern: value,
        kind: record.kind,
        enabled: record.enabled !== false,
        ttl: typeof record.ttl === 'number' ? record.ttl : ttl,
        maxEntry: typeof record.maxEntry === 'number' ? record.maxEntry : maxEntry,
        cacheableStatus: Array.isArray(record.cacheableStatus) ?
            record.cacheableStatus.filter(code => typeof code === 'number') as number[] :
            statuses.slice(),
      });
    }
    return rules;
  }

  #render(): void {
    this.#list.innerHTML = '';
    this.#empty.style.display = this.#rules.length ? 'none' : 'block';
    const enabledCount = this.#rules.filter(rule => rule.enabled).length;
    this.#selectAll.checked = this.#rules.length > 0 && enabledCount === this.#rules.length;
    this.#selectAll.indeterminate = enabledCount > 0 && enabledCount < this.#rules.length;
    this.#selectAll.disabled = this.#rules.length === 0;
    this.#deleteSelected.disabled = enabledCount === 0;
    for (const rule of this.#rules) {
      const row = this.#list.createChild('div', 'zz-cache-rule' + (rule.enabled ? '' : ' off'));
      const box = row.createChild('input') as HTMLInputElement;
      box.type = 'checkbox';
      box.checked = rule.enabled;
      box.title = '使用这条规则';
      box.addEventListener('change', () => {
        rule.enabled = box.checked;
        void this.#commit();
      });
      const tag = row.createChild('span', 'zz-cache-tag ' + rule.kind);
      tag.textContent = rule.kind;
      const body = row.createChild('div', 'zz-cache-body');
      const text = body.createChild('div', 'zz-cache-pattern');
      text.textContent = rule.pattern;
      const meta = body.createChild('div', 'zz-cache-meta');
      meta.textContent = 'ttl ' + rule.ttl + ' · maxEntry ' + rule.maxEntry + ' · status ' +
          (rule.cacheableStatus.length ? rule.cacheableStatus.join(',') : '全部 2xx');
      const remove = row.createChild('button', 'zz-cache-row-delete') as HTMLButtonElement;
      remove.type = 'button';
      remove.textContent = '删除';
      remove.addEventListener('click', () => {
        this.#rules = this.#rules.filter(item => item.id !== rule.id);
        void this.#commit();
      });
    }
  }

  #openDialog(): void {
    this.#pattern.value = '';
    this.#kind.value = 'include';
    this.#ttl.value = '0';
    this.#maxEntry.value = String(DEFAULT_MAX_ENTRY);
    this.#statuses.value = '200';
    this.#limitError.textContent = '';
    this.#mask.classList.add('show');
    this.#pattern.focus();
  }

  #readNumber(input: HTMLInputElement): number|null {
    const text = input.value.trim();
    if (text === '') {
      return 0;
    }
    if (!/^\d+$/.test(text)) {
      return null;
    }
    return Number(text);
  }

  #readLimits(): {ttl: number, maxEntry: number, statuses: number[]}|null {
    const ttl = this.#readNumber(this.#ttl);
    const maxEntry = this.#readNumber(this.#maxEntry);
    if (ttl === null || maxEntry === null) {
      this.#limitError.textContent = 'ttl 和 maxEntry 要是非负整数。';
      return null;
    }
    const statusText = this.#statuses.value.trim();
    let statuses: number[] = [];
    if (statusText) {
      const parts = statusText.split(',').map(part => part.trim()).filter(Boolean);
      if (!parts.length || parts.some(part => !/^\d+$/.test(part))) {
        this.#limitError.textContent = 'cacheableStatus 要是逗号分隔的状态码。';
        return null;
      }
      statuses = parts.map(Number);
    }
    this.#limitError.textContent = '';
    return {ttl, maxEntry, statuses};
  }

  async #addRule(): Promise<void> {
    const value = this.#pattern.value.trim();
    if (!value) {
      this.#pattern.focus();
      return;
    }
    const limits = this.#readLimits();
    if (!limits) {
      return;
    }
    this.#rules.push({
      id: String(Date.now()),
      pattern: value,
      kind: this.#kind.value === 'exclude' ? 'exclude' : 'include',
      enabled: true,
      ttl: limits.ttl,
      maxEntry: limits.maxEntry,
      cacheableStatus: limits.statuses,
    });
    this.cancel();
    await this.#commit();
  }

  async #toggleAll(enabled: boolean): Promise<void> {
    for (const rule of this.#rules) {
      rule.enabled = enabled;
    }
    await this.#commit();
  }

  async #deleteChecked(): Promise<void> {
    this.#rules = this.#rules.filter(rule => !rule.enabled);
    await this.#commit();
  }

  #rulesObject(): Record<string, unknown> {
    const body: Record<string, unknown> = {};
    const include = this.#rules.filter(rule => rule.enabled && rule.kind === 'include').map(rule => rule.pattern);
    const exclude = this.#rules.filter(rule => rule.enabled && rule.kind === 'exclude').map(rule => rule.pattern);
    if (include.length) {
      body['include'] = include;
    }
    if (exclude.length) {
      body['exclude'] = exclude;
    }
    for (const key of EXTRA_KEYS) {
      if (Array.isArray(this.#extra[key]) && (this.#extra[key] as unknown[]).length) {
        body[key] = this.#extra[key];
      }
    }
    body['items'] = this.#rules.map(rule => ({
                                   pattern: rule.pattern,
                                   kind: rule.kind,
                                   enabled: rule.enabled,
                                   ttl: rule.ttl,
                                   maxEntry: rule.maxEntry,
                                   cacheableStatus: rule.cacheableStatus,
                                 }));
    return body;
  }

  async #commit(): Promise<void> {
    this.#render();
    const agent = this.#agent();
    if (!agent) {
      this.#error.textContent = '当前目标没有 Context 域。';
      return;
    }
    const fresh = await agent.invoke_getCacheState({});
    const freshError = fresh.getError?.();
    if (freshError) {
      this.#error.textContent = freshError;
      return;
    }
    this.#dir = fresh.dir || this.#dir;
    this.#map = fresh.map || this.#map;
    const set = await agent.invoke_setContextOverrides({
      cache: {dir: this.#dir, map: this.#map, rules: JSON.stringify(this.#rulesObject())},
    });
    const setError = set.getError?.();
    if (setError) {
      this.#error.textContent = setError;
      return;
    }
    this.#error.textContent = '';
    await this.#explain(agent);
  }

  #export(): void {
    const params = {cache: {dir: this.#dir, map: this.#map, rules: JSON.stringify(this.#rulesObject())}};
    const blob = new Blob([JSON.stringify(params, null, 2)], {type: 'application/json'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'cache-rules.json';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async #import(file: File): Promise<void> {
    let data: unknown;
    try {
      data = JSON.parse(await file.text());
    } catch {
      this.#error.textContent = '这个文件不是 JSON。';
      return;
    }
    if (!data || typeof data !== 'object') {
      this.#error.textContent = '认不出缓存配置。';
      return;
    }
    const record = data as {cache?: {dir?: unknown, map?: unknown, rules?: unknown}};
    if (!record.cache || typeof record.cache !== 'object') {
      this.#error.textContent = '需要 Context.setContextOverrides 的 cache 参数。';
      return;
    }
    if (typeof record.cache.dir === 'string') {
      this.#dir = record.cache.dir;
    }
    if (typeof record.cache.map === 'string') {
      this.#map = record.cache.map;
    } else if (record.cache.map && typeof record.cache.map === 'object') {
      this.#map = JSON.stringify(record.cache.map);
    }
    const rulesText = typeof record.cache.rules === 'string' ? record.cache.rules : JSON.stringify(record.cache.rules || {});
    this.#readRules(rulesText);
    this.#loaded = true;
    await this.#commit();
  }

  async #explain(agent: ContextAgent): Promise<void> {
    const requests = this.#logView.zzCacheRequests();
    const chunk = 200;
    for (let i = 0; i < requests.length; i += chunk) {
      const slice = requests.slice(i, i + chunk);
      const response = await agent.invoke_explainCache({
        requests: slice.map(request => ({url: request.url(), method: request.requestMethod || 'GET'})),
      });
      const error = response.getError?.();
      if (error) {
        this.#error.textContent = error;
        return;
      }
      const results = response.results || [];
      for (let n = 0; n < slice.length; ++n) {
        this.#paint(slice[n], results[n]?.action || 'pass');
      }
    }
  }

  #onDecision(requestId: string, url: string, action: string): void {
    if (!action) {
      return;
    }
    const request = this.#logView.requestForZzCache(requestId, url);
    if (!request) {
      if (requestId) {
        this.#pendingById.set(requestId, action);
      }
      if (url) {
        this.#pendingByUrl.set(url, action);
      }
      return;
    }
    this.#paint(request, action);
  }

  #flushPending(): void {
    if (!this.#pendingById.size && !this.#pendingByUrl.size) {
      return;
    }
    for (const request of this.#logView.zzCacheRequests()) {
      const byId = this.#pendingById.get(request.requestId());
      const byUrl = this.#pendingByUrl.get(request.url());
      const action = byId || byUrl;
      if (!action) {
        continue;
      }
      this.#paint(request, action);
      this.#pendingById.delete(request.requestId());
      if (byUrl && !byId) {
        this.#pendingByUrl.delete(request.url());
      }
    }
  }

  #paint(request: SDK.NetworkRequest.NetworkRequest, action: string): void {
    this.#logView.applyZzCacheAction(request, action);
  }
}
