'use strict';
(function (root) {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const KIND_ORDER = ['T', 'D', 'N', 'F', 'M', 'other'];
  const KIND_LABELS = {T:'程序计算', D:'公告标题', N:'新闻标题', F:'财务指标', M:'无依据说明'};
  const COMPONENT_LABELS = {trend:'趋势', momentum:'动量', volume_coord:'量能配合', overheat:'过热/回撤风险'};

  function kindOf(id, kinds) {
    const known = kinds && typeof kinds === 'object' ? kinds[id] : null;
    if (known && typeof known.code === 'string' && known.code && typeof known.label === 'string' && known.label)
      return {code: known.code, label: known.label};
    const prefix = typeof id === 'string' && id ? id[0] : '';
    if (KIND_LABELS[prefix]) return {code: prefix, label: KIND_LABELS[prefix]};
    return {code: 'other', label: '其他'};
  }

  function kindTags(ids, kinds) {
    const seen = new Map();
    const list = Array.isArray(ids) ? ids : [];
    for (const id of list) {
      const kind = kindOf(id, kinds);
      if (!seen.has(kind.code)) seen.set(kind.code, kind.label);
    }
    const codes = [...seen.keys()].sort((a, b) => {
      const ia = KIND_ORDER.indexOf(a), ib = KIND_ORDER.indexOf(b);
      const da = ia < 0 ? KIND_ORDER.length : ia, db = ib < 0 ? KIND_ORDER.length : ib;
      return da - db || String(a).localeCompare(String(b));
    });
    return codes.map(code => ({code, label: seen.get(code)}));
  }

  function kindTagHTML(ids, kinds) {
    return kindTags(ids, kinds).map(item => `<span class="evidence-kind" data-kind="${esc(item.code)}">${esc(item.label)}</span>`).join('');
  }

  function firstScreenHTML(block, gaps) {
    if (!Array.isArray(block) || !block.length) return '';
    const rows = block.map(item => {
      const row = item && typeof item === 'object' ? item : {};
      const level = row.level === 'ok' || row.level === 'note' || row.level === 'warn' ? row.level : 'note';
      return `<li class="first-screen-${level}" data-key="${esc(row.key)}"><span>${esc(row.label)}</span><b>${esc(row.text)}</b></li>`;
    }).join('');
    let gapLine = '';
    if (Array.isArray(gaps)) {
      const count = gaps.length;
      const sentence = count ? `数据缺口 ${count} 处，影响见下方「材料范围与缺失项」` : '未发现需要说明的缺口';
      gapLine = `<p class="footnote first-screen-gaps">${esc(sentence)}</p>`;
    }
    return `<section class="report-first-screen"><h3>本次报告的前提与不确定性 <small>程序生成 · 不是评分</small></h3><ul>${rows}</ul>${gapLine}</section>`;
  }

  function impactSuffix(gap) {
    const names = [];
    const affects = Array.isArray(gap.affects) ? gap.affects : [];
    for (const key of affects) {
      const label = COMPONENT_LABELS[key];
      if (label && !names.includes(label)) names.push(label);
    }
    if (names.length) return ` → 影响：${esc(names.join('、'))}`;
    if (gap.text) return ` → 影响：${esc(gap.text)}`;
    return ` → 影响：${esc('影响范围未核实')}`;
  }

  function limitationItems(lines, gaps) {
    const list = Array.isArray(lines) ? lines : [];
    const impacts = Array.isArray(gaps) ? gaps.filter(gap => gap && typeof gap.gap === 'string' && gap.gap) : [];
    const used = new Array(impacts.length).fill(false);
    const rows = list.map(line => {
      const text = String(line ?? '');
      const related = [];
      impacts.forEach((gap, index) => {
        if (text.includes(gap.gap)) { used[index] = true; related.push(gap); }
      });
      return `<li>${esc(text)}${related.map(impactSuffix).join('')}</li>`;
    }).join('');
    const extra = impacts.filter((gap, index) => !used[index] && gap.text).map(gap => `<li class="gap-impact">${esc(gap.text)}</li>`).join('');
    return rows + extra;
  }

  root.FirstScreenView = {
    esc, KIND_ORDER, COMPONENT_LABELS, kindTags, kindTagHTML, firstScreenHTML, limitationItems, impactSuffix,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
