const test = require('node:test');
const assert = require('node:assert/strict');
const rules = require('../web/label-rules.js');

const banned = /应买|应卖|看多|看空|目标价|胜率|上涨概率|概率/;

test('every label has a unique key and a non-empty rule without advice wording', () => {
  assert.ok(rules.rules.length >= 8);
  const keys = rules.rules.map(item => item.key);
  assert.equal(new Set(keys).size, keys.length);
  for (const item of rules.rules) {
    assert.equal(typeof item.label, 'string');
    assert.ok(item.label.trim());
    assert.equal(typeof item.rule, 'string');
    assert.ok(item.rule.trim(), item.key);
    assert.equal(typeof item.note, 'string');
    assert.ok(item.note.trim(), item.key);
    assert.doesNotMatch(item.label + item.rule + item.note, banned, item.key);
    assert.equal(rules.get(item.key), item);
    assert.match(rules.ruleNote(item.key), /<details class="rule-note"><summary>规则<\/summary><p>/);
    assert.match(rules.inlineRule(item.key), /class="footnote rule-inline"/);
  }
});

test('the attention sentence states what 需要看 is and is not', () => {
  const item = rules.get('attention.pending');
  assert.equal(item.rule, '‘需要看’= 尚未分析 / 分析待更新 / 分析不完整，只反映本机研究记录的完成度，不是行情信号，也不是买卖建议。');
  assert.match(rules.inlineRule('attention.pending'), /不是行情信号，也不是买卖建议。/);
});

test('rule markup escapes special characters', () => {
  const html = rules.formatRule({rule: '<script>alert(1)</script>', note: `"&'`});
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /&quot;&amp;&#39;/);
  assert.equal(html.includes('<script>'), false);
  const bear = rules.ruleNote('trend.bear');
  assert.match(bear, /MA5 &lt; MA10 &lt; MA20/);
  assert.equal(bear.includes('MA5 < MA10'), false);
  assert.equal(rules.ruleNote('missing.key'), '');
  assert.equal(rules.formatRule({}), '');
});

test('pending preview follows completion priority and ignores scores', () => {
  const rows = [
    {thscode: '600003.SH', status: 'ready', score: 99, name: '高分'},
    {thscode: '600008.SH', status: 'missing', score: 1},
    {thscode: '600001.SH', status: 'outdated', score: 100},
    {thscode: '600002.SH', status: 'incomplete', score: 0},
    {thscode: '600000.SH', status: 'running', score: 50},
    {thscode: '600005.SH', status: 'missing', score: 3},
    {thscode: '600009.SH', status: 'outdated', score: 3},
  ];
  assert.deepEqual(rules.pendingPreview(rows).map(row => row.thscode), ['600002.SH', '600005.SH', '600008.SH']);
  assert.deepEqual(rules.pendingPreview(rows, 10).map(row => row.thscode), ['600002.SH', '600005.SH', '600008.SH', '600001.SH', '600009.SH']);
  assert.deepEqual(rules.pendingPreview(null), []);
  assert.equal(rules.trendKey('均线多头排列'), 'trend.bull');
  assert.equal(rules.trendKey('均线空头排列'), 'trend.bear');
  assert.equal(rules.trendKey('均线交错'), 'trend.mixed');
  assert.equal(rules.trendKey('数据不足'), 'trend.insufficient');
  assert.equal(rules.trendKey('其他'), '');
  assert.equal(rules.statusKey('missing'), 'status.missing');
});

test('attention card copy covers empty, ready, pending and a failed read', () => {
  const banned = /应买|应卖|看多|看空|目标价|胜率|上涨概率/;
  const empty = rules.cardHTML({items: [], counts: {stocks: 0, pending: 0}});
  assert.match(empty, /还没有自选/);
  assert.match(empty, /不是行情信号，也不是买卖建议。/);
  assert.equal(empty.includes('attention-row'), false);
  const ready = rules.cardHTML({items: [{thscode: '600000.SH', name: '甲', status: 'ready'}], counts: {stocks: 1, pending: 0}});
  assert.match(ready, /自选 1 只 · 待处理 0 只/);
  assert.match(ready, /当前观察日没有待处理的自选/);
  const pending = rules.cardHTML({
    counts: {stocks: 2, pending: 1},
    items: [
      {thscode: '600000.SH', name: '甲<script>', status: 'ready'},
      {thscode: '600001.SH', name: '乙"&<script>', status: 'missing'},
    ],
  });
  assert.match(pending, /自选 2 只 · 待处理 1 只/);
  assert.match(pending, /data-open-desk="600001.SH"/);
  assert.match(pending, /尚未分析/);
  assert.equal(pending.includes('600000.SH'), false);
  assert.match(pending, /乙&quot;&amp;&lt;script&gt;/);
  assert.equal(pending.includes('<script>'), false);
  assert.equal(pending.includes('attention-row'), true);
  assert.equal((pending.match(/attention-row/g) || []).length, 1);
  assert.doesNotMatch(empty + ready + pending + rules.loadError, banned);
  assert.match(rules.loadError, /不受影响/);
});
