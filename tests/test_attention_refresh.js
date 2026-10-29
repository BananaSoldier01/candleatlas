const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const DAY = '2026-01-05';

function boot(script, {hash = '#market', date = DAY} = {}) {
  const sandbox = {
    LabelRules: require('../web/label-rules.js'),
    Privacy: require('../web/privacy.js'),
  };
  sandbox.window = {LabelRules: sandbox.LabelRules, Privacy: sandbox.Privacy};
  vm.createContext(sandbox);
  vm.runInContext(`
    var pending = [];
    function api(path, params) {
      return new Promise(function (resolve, reject) {
        pending.push({path: path, params: Object.assign({}, params), resolve: resolve, reject: reject});
      });
    }
    function CustomEvent(type, init) {
      this.type = type;
      this.detail = init ? init.detail : undefined;
    }
    var elements = new Map();
    var docListeners = new Map();
    function matches(el, selector) {
      if (selector === 'button') return el.tagName === 'BUTTON';
      var found = /^\\[data-([A-Za-z-]+)(?:="([^"]*)")?\\]$/.exec(selector);
      if (!found) return false;
      var key = found[1].replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); });
      if (!Object.prototype.hasOwnProperty.call(el.dataset, key)) return false;
      return found[2] === undefined || el.dataset[key] === found[2];
    }
    function element(id, tagName) {
      var listeners = new Map();
      var classes = new Set();
      var el = {
        id: id || '',
        tagName: tagName || 'DIV',
        hidden: false,
        value: '',
        disabled: false,
        dataset: Object.create(null),
        children: [],
        attributes: Object.create(null),
        classList: {
          add: function (name) { classes.add(name); },
          remove: function (name) { classes.delete(name); },
          contains: function (name) { return classes.has(name); },
          toggle: function (name, on) {
            var enable = on === undefined ? !classes.has(name) : !!on;
            if (enable) classes.add(name); else classes.delete(name);
            return enable;
          },
        },
        setAttribute: function (name, value) { this.attributes[name] = String(value); },
        getAttribute: function (name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; },
        addEventListener: function (type, fn) {
          if (!listeners.has(type)) listeners.set(type, []);
          listeners.get(type).push(fn);
        },
        dispatchEvent: function (event) {
          var list = (listeners.get(event.type) || []).slice();
          for (var i = 0; i < list.length; i++) list[i].call(this, event);
          return true;
        },
        closest: function (selector) { return matches(this, selector) ? this : null; },
        querySelectorAll: function (selector) { return this.children.filter(function (child) { return matches(child, selector); }); },
        querySelector: function (selector) { return this.querySelectorAll(selector)[0] || null; },
        append: function (child) { this.children.push(child); },
        prepend: function (child) { this.children.unshift(child); },
        focus: function () {},
      };
      Object.defineProperty(el, 'textContent', {
        get: function () { return el._text || ''; },
        set: function (value) { el._text = String(value == null ? '' : value); el._html = el._text; },
      });
      Object.defineProperty(el, 'innerHTML', {
        get: function () { return el._html || ''; },
        set: function (value) { el._html = String(value == null ? '' : value); el._text = el._html; },
      });
      return el;
    }
    function ensure(id) {
      if (!elements.has(id)) elements.set(id, element(id, 'DIV'));
      return elements.get(id);
    }
    var body = element('body', 'DIV');
    var document = {
      body: body,
      getElementById: function (id) { return ensure(id); },
      addEventListener: function (type, fn) {
        if (!docListeners.has(type)) docListeners.set(type, []);
        docListeners.get(type).push(fn);
      },
      removeEventListener: function () {},
      dispatchEvent: function (event) {
        var list = (docListeners.get(event.type) || []).slice();
        for (var i = 0; i < list.length; i++) list[i].call(document, event);
        return true;
      },
      querySelectorAll: function () { return []; },
      querySelector: function () { return null; },
      createElement: function (tag) { return element('', String(tag || 'div').toUpperCase()); },
    };
    var location = {hash: ''};
    var state = {date: '', stock: null, view: 'price'};
    function $(id) { return document.getElementById(id); }
    function showWorkspace(page) {
      location.hash = '#' + page;
      document.dispatchEvent(new CustomEvent('workspace-selected', {detail: page}));
    }
    globalThis.pending = pending;
    globalThis.api = api;
    globalThis.CustomEvent = CustomEvent;
    globalThis.elements = elements;
    globalThis.document = document;
    globalThis.location = location;
    globalThis.state = state;
    globalThis.$ = $;
    globalThis.showWorkspace = showWorkspace;
  `, sandbox);
  sandbox.location.hash = hash;
  sandbox.state.date = date;
  vm.runInContext(fs.readFileSync(script, 'utf8'), sandbox, {filename: script});
  return sandbox;
}

function card(items) {
  const pending = items.filter(row => ['missing', 'outdated', 'incomplete'].includes(row.status)).length;
  return {date: DAY, items, counts: {stocks: items.length, pending, ready: items.length - pending, records: items.length}};
}

const three = () => card([
  {thscode: '600001.SH', name: '甲', status: 'missing'},
  {thscode: '600002.SH', name: '乙', status: 'outdated'},
  {thscode: '920001.BJ', name: '丙', status: 'incomplete'},
]);
const two = () => card([
  {thscode: '600001.SH', name: '甲', status: 'missing'},
  {thscode: '920001.BJ', name: '丙', status: 'incomplete'},
]);

function flush() {
  return new Promise(resolve => setImmediate(resolve));
}

async function fulfill(call, data) {
  call.resolve(data);
  await flush();
}

test('attention source refreshes on records and on returning to the market', () => {
  const src = fs.readFileSync('web/attention.js', 'utf8');
  assert.match(src, /document\.addEventListener\('day-selected',load\)/);
  assert.match(src, /document\.addEventListener\('records-updated',load\)/);
  assert.match(src, /document\.addEventListener\('workspace-selected',event=>\{if\(event\.detail==='market'\)load\(\);\}\)/);
  assert.match(src, /const token=\+\+version/);
  assert.match(src, /if\(token!==version\)return/);
});

test('analysis polling dispatches records-updated only after running finishes', () => {
  const src = fs.readFileSync('web/analysis.js', 'utf8');
  const renderAt = src.indexOf('function render(d)');
  const reportAt = src.indexOf('async function report');
  const historyAt = src.indexOf('async function history');
  assert.ok(renderAt > 0 && reportAt > renderAt && historyAt > reportAt);
  const render = src.slice(renderAt, reportAt);
  const report = src.slice(reportAt, historyAt);
  assert.equal(render.includes('records-updated'), false);
  assert.equal(src.split('records-updated').length - 1, 1);
  const tokenAt = report.indexOf('if(token!==version)return');
  const runningAt = report.indexOf("d.status==='running'");
  const dispatchAt = report.indexOf("dispatchEvent(new CustomEvent('records-updated'))");
  assert.ok(tokenAt > 0 && report.indexOf('reportWatch') > tokenAt);
  assert.ok(runningAt > tokenAt && dispatchAt > runningAt);
  assert.match(report.slice(runningAt, dispatchAt), /else if\(previous==='running'\)/);
});

test('attention card replaces an archived watchlist and ignores a late response', async () => {
  const box = boot('web/attention.js');
  const body = box.elements.get('attention-body');
  assert.equal(box.pending.length, 1);
  assert.equal(box.pending[0].path, 'workbench');
  assert.equal(box.pending[0].params.date, DAY);
  await fulfill(box.pending[0], three());
  assert.match(body.innerHTML, /自选 3 只 · 待处理 3 只/);
  assert.match(body.innerHTML, /600002\.SH/);
  assert.match(body.innerHTML, /data-open-desk="920001\.BJ"/);

  const refreshed = box.pending.length;
  box.document.dispatchEvent({type: 'records-updated'});
  assert.equal(box.pending.length, refreshed + 1);
  await fulfill(box.pending[refreshed], two());
  assert.match(body.innerHTML, /自选 2 只 · 待处理 2 只/);
  assert.match(body.innerHTML, /600001\.SH/);
  assert.match(body.innerHTML, /920001\.BJ/);
  assert.equal(body.innerHTML.includes('600002.SH'), false);

  const quiet = box.pending.length;
  box.document.dispatchEvent({type: 'workspace-selected', detail: 'stocks'});
  box.document.dispatchEvent({type: 'workspace-selected', detail: 'watch'});
  assert.equal(box.pending.length, quiet);
  box.document.dispatchEvent({type: 'workspace-selected', detail: 'market'});
  box.document.dispatchEvent({type: 'records-updated'});
  assert.equal(box.pending.length, quiet + 2);
  await fulfill(box.pending[quiet + 1], two());
  await fulfill(box.pending[quiet], three());
  assert.match(body.innerHTML, /自选 2 只 · 待处理 2 只/);
  assert.equal(body.innerHTML.includes('600002.SH'), false);
  assert.match(body.innerHTML, /data-open-desk="920001\.BJ"/);

  const day = box.pending.length;
  box.document.dispatchEvent({type: 'day-selected'});
  assert.equal(box.pending.length, day + 1);
  assert.equal(box.pending[day].params.date, DAY);
  await fulfill(box.pending[day], two());
  assert.match(body.innerHTML, /自选 2 只 · 待处理 2 只/);
  assert.equal(body.textContent.includes('失败'), false);
});
