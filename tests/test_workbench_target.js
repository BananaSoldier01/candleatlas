const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const DAY = '2026-01-05';
const TARGET = '920001.BJ';

function boot({hash = '#watch', date = DAY, privacy = true} = {}) {
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
    var filter = element('desk-filter', 'DIV');
    function filterButton(name) {
      var button = element('', 'BUTTON');
      button.dataset.filter = name;
      button.setAttribute('aria-pressed', name === 'all' ? 'true' : 'false');
      if (name === 'all') button.classList.add('active');
      return button;
    }
    var filters = {all: filterButton('all'), pending: filterButton('pending'), ready: filterButton('ready')};
    filter.children.push(filters.all, filters.pending, filters.ready);
    elements.set('desk-filter', filter);
    function esc(value) {
      return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
      });
    }
    function $(id) { return document.getElementById(id); }
    var location = {hash: ''};
    var state = {date: '', stock: null, view: 'price'};
    function showWorkspace(page) {
      location.hash = '#' + page;
      document.dispatchEvent(new CustomEvent('workspace-selected', {detail: page}));
    }
    function selectStock() {}
    globalThis.pending = pending;
    globalThis.api = api;
    globalThis.CustomEvent = CustomEvent;
    globalThis.elements = elements;
    globalThis.filters = filters;
    globalThis.document = document;
    globalThis.location = location;
    globalThis.state = state;
    globalThis.esc = esc;
    globalThis.$ = $;
    globalThis.showWorkspace = showWorkspace;
    globalThis.selectStock = selectStock;
  `, sandbox);
  sandbox.location.hash = hash;
  sandbox.state.date = date;
  if (privacy) sandbox.document.body.classList.add('privacy-on');
  vm.runInContext(fs.readFileSync('web/workbench.js', 'utf8'), sandbox, {filename: 'web/workbench.js'});
  return sandbox;
}

function row(thscode, name, status) {
  return {
    thscode, name, status,
    technical: {close: 11, asof: DAY, change20: 0, volume_ratio5: 1, trend: '均线交错'},
    note: '核对资料',
    observed: DAY,
    record_count: 1,
    report: null,
    overview: [],
    watch: [],
    limitations: [],
    watch_points: [],
  };
}

function jia() { return row('600001.SH', '甲', 'missing'); }
function yi() { return row('600002.SH', '乙', 'outdated'); }
function bing() { return row(TARGET, '丙', 'ready'); }

function snapshot(items) {
  const pending = items.filter(item => ['missing', 'outdated', 'incomplete'].includes(item.status)).length;
  return {
    date: DAY,
    counts: {stocks: items.length, pending, ready: items.length - pending, records: items.length},
    items,
    future_records: 0,
  };
}

const trio = () => snapshot([jia(), yi(), bing()]);

function flush() {
  return new Promise(resolve => setImmediate(resolve));
}

async function fulfill(call, data) {
  call.resolve(data);
  await flush();
}

function pressFilter(box, name) {
  box.elements.get('desk-filter').dispatchEvent({type: 'click', target: box.filters[name]});
}

function blockTarget(box) {
  const find = box.elements.get('desk-find');
  find.value = '甲';
  pressFilter(box, 'pending');
  return find;
}

function openTarget(box, code = TARGET) {
  box.document.dispatchEvent({type: 'open-desk-stock', detail: code});
}

function assertChosen(box) {
  const detail = box.elements.get('desk-detail').innerHTML;
  const list = box.elements.get('desk-list').innerHTML;
  const message = box.elements.get('desk-message').textContent;
  assert.equal(message.includes('失败'), false, message);
  assert.match(detail, /<h2>丙<\/h2>/);
  assert.equal(detail.includes('<h2>甲</h2>'), false);
  assert.match(detail, /920001\.BJ/);
  assert.match(detail, /data-private="核对资料"/);
  assert.match(detail, /已隐藏 · 点击显示/);
  assert.match(detail, /<details class="rule-note">/);
  assert.match(detail, /当日已有分析/);
  assert.match(list, /class="desk-stock selected" data-desk-stock="920001\.BJ" aria-pressed="true"/);
  assert.equal(list.includes('data-desk-stock="600001.SH" aria-pressed="true"'), false);
  assert.match(list, /600001\.SH/);
  assert.match(list, /600002\.SH/);
  assert.match(list, /920001\.BJ/);
  assert.equal(box.elements.get('desk-find').value, '');
  assert.equal(box.filters.all.getAttribute('aria-pressed'), 'true');
  assert.equal(box.filters.all.classList.contains('active'), true);
  assert.equal(box.filters.pending.getAttribute('aria-pressed'), 'false');
  assert.equal(box.filters.pending.classList.contains('active'), false);
  assert.match(message, /截至观察日 2026-01-05/);
}

test('open-desk-stock clears the text search before choosing the target', () => {
  const src = fs.readFileSync('web/workbench.js', 'utf8');
  const handler = src.slice(src.indexOf("'open-desk-stock'"), src.indexOf("'privacy-changed'"));
  assert.match(handler, /\$\('desk-find'\)\.value=''/);
  assert.match(handler, /filter='all'/);
  assert.match(handler, /showWorkspace\('watch'\)/);
  assert.match(src, /if\(!rows\.some\(r=>r\.thscode===chosen\)\)chosen=rows\[0\]\?\.thscode\|\|''/);
  assert.match(src, /window\.Privacy\?Privacy\.privateHTML/);
  assert.match(src, /LabelRules\.get\('status\.'\+status\)/);
});

test('an active name search and status filter cannot redirect the opened stock', async () => {
  const box = boot();
  assert.equal(box.pending.length, 1);
  await fulfill(box.pending[0], trio());
  const calls = box.pending.length;
  const find = blockTarget(box);
  assert.equal(find.value, '甲');
  assert.equal(box.filters.pending.getAttribute('aria-pressed'), 'true');
  assert.match(box.elements.get('desk-detail').innerHTML, /<h2>甲<\/h2>/);
  assert.equal(box.elements.get('desk-list').innerHTML.includes(TARGET), false);
  openTarget(box);
  assert.equal(box.pending.length, calls);
  assertChosen(box);
});

test('opening from another page waits for load and still keeps the target', async () => {
  const box = boot({hash: '#market'});
  assert.equal(box.pending.length, 0);
  const find = blockTarget(box);
  assert.equal(find.value, '甲');
  assert.equal(box.filters.pending.classList.contains('active'), true);
  openTarget(box);
  assert.equal(box.location.hash, '#watch');
  assert.equal(find.value, '');
  assert.equal(box.filters.all.getAttribute('aria-pressed'), 'true');
  assert.equal(box.pending.length, 1);
  assert.equal(box.pending[0].path, 'workbench');
  assert.equal(box.pending[0].params.date, DAY);
  await fulfill(box.pending[0], trio());
  assertChosen(box);
});

test('loaded data selects the target immediately and a reload keeps it', async () => {
  const box = boot();
  await fulfill(box.pending[0], trio());
  box.location.hash = '#market';
  blockTarget(box);
  assert.match(box.elements.get('desk-detail').innerHTML, /<h2>甲<\/h2>/);
  openTarget(box);
  assert.equal(box.location.hash, '#watch');
  assert.equal(box.pending.length, 2);
  assert.match(box.elements.get('desk-detail').innerHTML, /<h2>丙<\/h2>/);
  assert.equal(box.elements.get('desk-detail').innerHTML.includes('<h2>甲</h2>'), false);
  assert.equal(box.elements.get('desk-find').value, '');
  await fulfill(box.pending[1], trio());
  assertChosen(box);
});

test('a slower workbench response cannot replace the requested stock', async () => {
  const box = boot();
  const stale = box.pending[0];
  blockTarget(box);
  openTarget(box);
  assert.equal(box.pending.length, 2);
  await fulfill(box.pending[1], trio());
  assertChosen(box);
  await fulfill(stale, snapshot([jia()]));
  assertChosen(box);
  assert.match(box.elements.get('desk-list').innerHTML, /920001\.BJ/);
});

test('a blank open request leaves the current search in place', async () => {
  const box = boot();
  await fulfill(box.pending[0], trio());
  const find = blockTarget(box);
  const calls = box.pending.length;
  box.document.dispatchEvent({type: 'open-desk-stock', detail: ''});
  box.document.dispatchEvent({type: 'open-desk-stock', detail: 12});
  assert.equal(find.value, '甲');
  assert.equal(box.filters.pending.getAttribute('aria-pressed'), 'true');
  assert.match(box.elements.get('desk-detail').innerHTML, /<h2>甲<\/h2>/);
  assert.equal(box.pending.length, calls);
});
