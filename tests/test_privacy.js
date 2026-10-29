const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const privacy = require('../web/privacy.js');

function memory() {
  const mem = new Map();
  return {
    getItem: key => mem.has(key) ? mem.get(key) : null,
    setItem: (key, value) => mem.set(key, String(value)),
  };
}

test('mask keeps text when off and replaces it when on', () => {
  assert.equal(privacy.maskNote('核对业绩 <script>', false), '核对业绩 <script>');
  assert.equal(privacy.maskNote('核对业绩', true), '已隐藏 · 点击显示');
  assert.equal(privacy.maskNote('', true), '');
  assert.equal(privacy.maskNote(null, true), '');
  assert.equal(privacy.maskNote(null, false), '');
});

test('preference defaults off, persists, and ignores other values', () => {
  const storage = memory();
  assert.equal(privacy.readPref(storage), false);
  assert.equal(privacy.writePref(storage, true), true);
  assert.equal(privacy.readPref(storage), true);
  assert.equal(storage.getItem(privacy.KEY), '1');
  assert.equal(privacy.writePref(storage, false), true);
  assert.equal(privacy.readPref(storage), false);
  assert.equal(storage.getItem(privacy.KEY), '0');
  storage.setItem(privacy.KEY, 'true');
  assert.equal(privacy.readPref(storage), false);
});

test('storage exceptions degrade to off', () => {
  const storage = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
  };
  assert.equal(privacy.readPref(storage), false);
  assert.equal(privacy.writePref(storage, true), false);
});

test('rendered notes escape text and hide it only on screen', () => {
  const hidden = privacy.privateHTML('<img src=x onerror="alert(1)">&', 'desk-note', true);
  assert.match(hidden, /class="desk-note private-text"/);
  assert.match(hidden, /role="button"/);
  assert.match(hidden, /data-private="&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;&amp;"/);
  assert.match(hidden, />已隐藏 · 点击显示</);
  assert.equal(hidden.includes('<img'), false);
  const shown = privacy.privateHTML('<b>', 'observation-note', false);
  assert.match(shown, /data-private="&lt;b&gt;"/);
  assert.match(shown, />&lt;b&gt;</);
  assert.equal(shown.includes('role="button"'), false);
  assert.equal(shown.includes('<b>'), false);
});

test('demo mode does not disable the privacy switch', () => {
  const demo = fs.readFileSync('web/demo.js', 'utf8');
  assert.match(demo, /n\.id==='privacy-toggle'/);
  assert.equal(demo.includes('#privacy-toggle'), false);
  assert.equal(demo.includes('privacy-toggle\''), true);
});

test('the switch writes aria-pressed and survives a storage failure', () => {
  function harness(storage) {
    const attrs = new Map([['aria-pressed', 'false']]);
    const classes = new Set();
    const button = {
      id: 'privacy-toggle',
      getAttribute: key => attrs.get(key),
      setAttribute: (key, value) => attrs.set(key, value),
      addEventListener(type, fn) { button.listeners[type] = fn; },
      listeners: {},
    };
    const doc = {
      body: {classList: {toggle(name, on) { if (on) classes.add(name); else classes.delete(name); }}},
      getElementById: id => id === 'privacy-toggle' ? button : null,
      addEventListener() {},
      querySelectorAll: () => [],
      dispatchEvent() {},
    };
    privacy.bind(doc, storage);
    return {button, classes};
  }
  const storage = memory();
  const ui = harness(storage);
  assert.equal(ui.button.getAttribute('aria-pressed'), 'false');
  assert.equal(ui.classes.has('privacy-on'), false);
  ui.button.listeners.click();
  assert.equal(ui.button.getAttribute('aria-pressed'), 'true');
  assert.equal(ui.classes.has('privacy-on'), true);
  assert.equal(storage.getItem(privacy.KEY), '1');
  ui.button.listeners.click();
  assert.equal(ui.button.getAttribute('aria-pressed'), 'false');
  assert.equal(ui.classes.has('privacy-on'), false);
  const blocked = harness({
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
  });
  assert.equal(blocked.button.getAttribute('aria-pressed'), 'false');
  blocked.button.listeners.click();
  assert.equal(blocked.button.getAttribute('aria-pressed'), 'false');
  assert.equal(blocked.classes.has('privacy-on'), false);
});
