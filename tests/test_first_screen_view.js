const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const sandbox = {};
vm.runInNewContext(fs.readFileSync('web/first-screen-view.js', 'utf8'), sandbox);
const view = sandbox.FirstScreenView;

test('evidence tags are deduped and ordered T D N F M then other', () => {
  const tags = view.kindTags(['N2', 'T1', 'F1', 'X9', 'M1', 'D3', 'T2'], {
    T1: {code: 'T', label: '程序计算'},
    T2: {code: 'T', label: '程序计算'},
    D3: {code: 'D', label: '公告标题'},
    N2: {code: 'N', label: '新闻标题'},
    F1: {code: 'F', label: '财务指标'},
    M1: {code: 'M', label: '无依据说明'},
    X9: {code: 'other', label: '其他'},
  });
  assert.equal([...tags].map(tag => tag.code).join(','), 'T,D,N,F,M,other');
  assert.equal(tags.find(tag => tag.code === 'F').label, '财务指标');
  const html = view.kindTagHTML(['F1', '<T>'], {F1: {code: 'F', label: '财务<指标>'}});
  assert.match(html, /data-kind="F"/);
  assert.match(html, /财务&lt;指标&gt;/);
  assert.doesNotMatch(html, /财务<指标>/);
  assert.equal(JSON.stringify(view.kindTags(['ZZ'], {})), JSON.stringify([{code: 'other', label: '其他'}]));
});

test('first screen is omitted for old payloads and escapes text', () => {
  assert.equal(view.firstScreenHTML(undefined, []), '');
  assert.equal(view.firstScreenHTML(null, []), '');
  assert.equal(view.firstScreenHTML([], []), '');
  const html = view.firstScreenHTML([
    {key: 'dates', label: '观察日与数据日', text: '不一致：<script>', level: 'warn'},
  ], []);
  assert.match(html, /class="report-first-screen"/);
  assert.match(html, /first-screen-warn/);
  assert.match(html, /不一致：&lt;script&gt;/);
  assert.match(html, /未发现需要说明的缺口/);
  assert.doesNotMatch(html, /<script>/);
  const counted = view.firstScreenHTML([{key: 'ai', label: '是否含 AI', text: '仅程序计算，未调用 AI', level: 'ok'}], [{gap: 'a'}, {gap: 'b'}]);
  assert.match(counted, /数据缺口 2 处，影响见下方「材料范围与缺失项」/);
  assert.equal(view.firstScreenHTML([{key: 'ai', label: '是否含 AI', text: '仅程序计算', level: 'ok'}]).includes('first-screen-gaps'), false);
});

test('limitations keep their original text and append mapped impacts', () => {
  const html = view.limitationItems([
    '连续有效样本不足 60 个，部分指标不计算；缺失日未填补。',
    '新闻获取失败，不据此认定没有相关事件。',
    '原文 <保留>',
  ], [
    {gap: '不足 60', affects: ['trend', 'momentum'], text: 'MACD 缺失 → 动量部分规则不计'},
    {gap: '新闻获取失败', affects: [], text: 'AI 解读缺少 N 类材料（不据此认定无事件）'},
    {gap: 'volume_ratio5', affects: ['volume_coord'], text: '成交量不足以计算 volume_ratio5 → 量能配合不可算'},
  ]);
  assert.match(html, /连续有效样本不足 60 个，部分指标不计算；缺失日未填补。 → 影响：趋势、动量/);
  assert.match(html, /新闻获取失败，不据此认定没有相关事件。 → 影响：AI 解读缺少 N 类材料（不据此认定无事件）/);
  assert.match(html, /原文 &lt;保留&gt;/);
  assert.match(html, /class="gap-impact"/);
  assert.match(html, /量能配合不可算/);
  assert.doesNotMatch(html, /<保留>/);
});

test('analysis render places the disclosure before the price section', () => {
  const src = fs.readFileSync('web/analysis.js', 'utf8');
  const render = src.slice(src.indexOf('function render'), src.indexOf('async function report'));
  assert.ok(render.indexOf('firstScreenHTML') < render.indexOf('行情状态'));
  assert.ok(render.indexOf('综合解读') < render.indexOf('${aiNote}'));
  assert.ok(render.includes('${aiNote}${gateNote}${sections}'));
  assert.ok(render.includes('（略※）表示数字未在所引新闻/披露中核到出处'));
  assert.ok(render.indexOf('gateHit') < render.indexOf('gateNote'));
  assert.match(render, /证据类型只说明材料来自哪里，不代表该推断已被验证，也不是概率。/);
  assert.match(render, /kindTagHTML/);
  assert.match(render, /limitationItems/);
});
