/* Hebao module contract v1. Trusted bundled modules only; not a JS sandbox. */
(function (root) {
"use strict";
class Scope {
  constructor(report = console.error) { this.disposers = []; this.closed = false; this.report = report; }
  own(dispose) {
    if (typeof dispose !== 'function') throw new TypeError('资源必须提供释放函数');
    let active = true;
    const once = () => { if (active) { active = false; dispose(); } };
    if (this.closed) once(); else this.disposers.push(once);
    return once;
  }
  listen(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    return this.own(() => target.removeEventListener(type, handler, options));
  }
  dispose() {
    if (this.closed) return;
    this.closed = true;
    for (const dispose of this.disposers.reverse()) {
      try { dispose(); } catch (error) { this.report(error); }
    }
    this.disposers.length = 0;
  }
}
class Registry {
  constructor() { this.modules = new Map(); this.listeners = new Set(); }
  register(entry) {
    if (!entry || entry.apiVersion !== 1 || !/^[a-z][a-z0-9.-]{0,39}$/.test(entry.id)
      || typeof entry.title !== 'string' || typeof entry.mount !== 'function'
      || !Array.isArray(entry.commands) || !entry.commands.every(x => typeof x === 'string')) {
      throw new Error('模块接口不兼容');
    }
    if (this.modules.has(entry.id)) throw new Error('模块入口重复：' + entry.id);
    const saved = Object.freeze({...entry, commands: Object.freeze([...entry.commands])});
    this.modules.set(saved.id, saved); this.emit();
    let active = true;
    return () => {
      if (!active) return;
      active = false; this.modules.delete(saved.id); this.emit();
    };
  }
  list() { return [...this.modules.values()].sort((a,b) => (a.order || 0) - (b.order || 0)); }
  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  emit() { for (const listener of this.listeners) listener(); }
}
function clientFor(entry, transport) {
  const allowed = new Set(entry.commands);
  return (command, params = {}, signal) => {
    if (!allowed.has(command)) return Promise.reject(new Error('模块没有申请此接口：' + command));
    return transport(command, params, signal);
  };
}
class PanelHost {
  constructor(registry, element, services, report) {
    this.registry = registry; this.element = element; this.services = services;
    this.report = report; this.scope = null; this.current = null;
    this.unsubscribe = registry.subscribe(() => {
      if (this.current && !registry.modules.has(this.current)) this.open('home');
    });
  }
  open(id, payload) {
    const entry = this.registry.modules.get(id);
    if (!entry) throw new Error('模块未安装：' + id);
    if (this.scope) this.scope.dispose();
    this.services.closeDetails();
    this.element.replaceChildren(); this.current = id;
    const scope = new Scope(this.report); this.scope = scope;
    const abort = new AbortController(); scope.own(() => abort.abort());
    const client = clientFor(entry, this.services.transport);
    const fail = error => {
      if (scope.closed) return;
      scope.dispose(); this.report(error);
      const p = document.createElement('p'); p.className = 'error-state';
      p.textContent = '这个模块暂时没有打开成功。可以切换到其他模块，再回来重试。';
      this.element.replaceChildren(p);
    };
    try {
      const result = entry.mount(this.element, {
        ...this.services, scope, signal: abort.signal,
        call: (command, params = {}, signal = abort.signal) => client(command, params, signal), payload,
      });
      Promise.resolve(result).then(dispose => { if (dispose) scope.own(dispose); }, fail);
    } catch (error) { fail(error); }
  }
  dispose() { if (this.scope) this.scope.dispose(); this.unsubscribe(); }
}
const api = {Scope, Registry, clientFor, PanelHost};
if (typeof module === 'object' && module.exports) module.exports = api;
else root.HebaoRuntime = api;
})(typeof window === 'object' ? window : globalThis);
