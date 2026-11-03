const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Exercise the chart's actual DOM handlers. Only valid candles have SVG nodes.
function chartHarness() {
  const elements = new Map();
  const document = {getElementById(id) {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  }};
  class Element {
    constructor() { this.attrs = {}; this.handlers = {}; }
    addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
    fire(type, event = {}) { for (const handler of this.handlers[type] || []) handler(event); }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    getAttribute(key) { return this.attrs[key]; }
    querySelectorAll() { return []; }
  }
  const context = {document, window: new Element(), cancelAnimationFrame() {}, fetch: () => new Promise(() => {})};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
  const chart = document.getElementById('price-chart');
  const candles = [0, 2, 3].map(index => {
    const candle = new Element();
    candle.dataset = {candle: String(index), date: '2026-01-0' + (index + 1)};
    candle.closest = selector => ['.candle', '[data-candle]'].includes(selector) ? candle : null;
    candle.focus = () => { document.activeElement = candle; chart.fire('focusin', {target: candle}); };
    return candle;
  });
  chart.querySelector = selector => candles.find(c => selector.includes('"'+c.dataset.candle+'"'));
  context.candles = candles;
  vm.runInContext(`
    priceGeometry = {candles, position:-1, items:[10,null,12,13].map(close_price=>({close_price})), L:0,step:1,T:0,PH:1,min:0,max:20};
    showPriceCursor = () => {};
    selectCandle(candles.at(-1));
  `, context);
  return {candles, document, chart};
}

test('buttons and keyboard navigate available candles without trapping Tab or inventing missing bars', () => {
  const {candles, document, chart} = chartHarness();
  const get = id => document.getElementById(id);
  const selected = () => candles.filter(candle => candle.getAttribute('tabindex') === '0');
  const key = value => {
    let consumed = false;
    chart.fire('keydown', {key: value, target: selected()[0], preventDefault() { consumed = true; }});
    return consumed;
  };
  assert.deepEqual(selected(), [candles[2]]);
  assert.equal(get('candle-next').getAttribute('aria-disabled'), 'true');
  assert.equal(key('Home'), true);
  assert.deepEqual(selected(), [candles[0]]);
  get('candle-prev').fire('click');
  assert.equal(get('candle-prev').getAttribute('aria-disabled'), 'true');
  get('candle-next').fire('click');
  assert.deepEqual(selected(), [candles[1]]);
  assert.match(get('candle-position').textContent, /2026-01-03\n第 2 \/ 3 根/);
  assert.equal(key('ArrowRight'), true);
  assert.equal(key('ArrowLeft'), true);
  assert.deepEqual(selected(), [candles[1]]);
  assert.equal(key('Tab'), false);
  assert.equal(key('End'), true);
  assert.deepEqual(selected(), [candles[2]]);
});
