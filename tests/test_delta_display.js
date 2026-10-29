const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {deltaToneClass} = require('../web/delta-display.js');

test('only comparable price rows use red or green', () => {
  assert.equal(deltaToneClass({metric_class: 'price', direction: 'up'}), 'quote-up');
  assert.equal(deltaToneClass({metric_class: 'price', direction: 'down'}), 'quote-down');
  assert.equal(deltaToneClass({metric_class: 'price', direction: 'flat', diff: 0}), '');
  for (const metric_class of ['indicator', 'volume', 'count']) {
    assert.equal(deltaToneClass({metric_class, direction: 'up'}), '');
    assert.equal(deltaToneClass({metric_class, direction: 'down'}), '');
  }
  assert.equal(deltaToneClass({metric_class: 'price', direction: 'up', hide_direction: true}), 'delta-na');
  assert.equal(deltaToneClass({metric_class: 'price', direction: 'window_sensitive', display: 'value_only'}), 'delta-na');
  assert.equal(deltaToneClass({metric_class: 'price', direction: 'not_comparable', display: 'hidden_direction'}), 'delta-na');
  assert.equal(deltaToneClass({metric_class: 'indicator', direction: 'up', hide_direction: true}), 'delta-na');
  assert.equal(deltaToneClass({metric_class: 'volume', direction: 'down'}), '');
  assert.equal(deltaToneClass(null), '');
  assert.equal(deltaToneClass({}), '');
});

test('analysis renderer no longer emits undefined delta color classes', () => {
  const src = fs.readFileSync('web/analysis.js', 'utf8');
  assert.equal(/\bdelta-up\b/.test(src), false);
  assert.equal(/\bdelta-down\b/.test(src), false);
  assert.equal(/\bdelta-flat\b/.test(src), false);
  assert.match(src, /DeltaDisplay\.deltaToneClass/);
  assert.match(src, /<details class="delta-metrics" open>/);
  assert.match(src, /<details class="delta-notices"/);
  assert.match(src, /过程对比 · 并排看每份报告怎么得出来的/);
  assert.match(src, /只比较方法与取数范围，不比较结果好坏。/);
  assert.match(src, /披露 \/ 公告材料变化/);
  assert.match(src, /noticeShow/);
  assert.match(src, /noticeSummary/);
});
