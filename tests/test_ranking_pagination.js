const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('expanded attention and quote rankings advance by the returned page size', async () => {
  const calls = [], elements = new Map();
  function $(id) {
    if (!elements.has(id)) elements.set(id, {
      querySelectorAll: () => [],
      classList: {toggle() {}},
      addEventListener(type, fn) { this[type] = fn; }
    });
    return elements.get(id);
  }
  const api = async (path, params) => {
    calls.push([params.offset, params.limit]);
    return {items: [], source_date: params.date, source: '测试样本',
            total: 125, offset: params.offset, limit: params.limit};
  };
  vm.runInNewContext(fs.readFileSync('web/rankings.js', 'utf8'), {
    $, api, document: {addEventListener() {}}, state: {date: '2026-02-17'},
    esc: String, message() {}
  });
  const flush = () => new Promise(resolve => setImmediate(resolve));
  async function click(id, dataset = {}) {
    $(id).click({target: {closest: () => ({dataset})}});
    await flush();
  }
  await flush();
  await click('rank-expand');
  await click('rank-next');
  await click('rank-next');
  await click('rank-prev');
  assert.deepEqual(calls, [[0, 10], [0, 30], [30, 30], [60, 30], [30, 30]]);

  calls.length = 0;
  await click('ranking-groups', {group: 'quotes'});
  await click('rank-expand');
  await click('rank-next');
  await click('rank-prev');
  assert.deepEqual(calls, [[0, 10], [0, 50], [50, 50], [0, 50]]);
});
