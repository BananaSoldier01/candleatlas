'use strict';
(function(factory){
  const api=factory();
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.LabelRules=api;
})(function(){
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rules=[
    {key:'status.missing',label:'尚未分析',rule:'观察日及以前没有保存的分析报告。',note:'只说明本机还没有这份分析，不是行情信号，也不是买卖建议。'},
    {key:'status.running',label:'分析进行中',rule:'已保存的报告状态是 running。只要仍是 running，就不记为不完整、待更新或当日已有分析。',note:'表示本机分析尚未结束，不是行情信号，也不是买卖建议。'},
    {key:'status.incomplete',label:'分析不完整',rule:'已有报告，状态不是 running，且报告状态不是 complete，或技术结果没有收盘价。',note:'只说明这份分析记录不完整，不是行情信号，也不是买卖建议。'},
    {key:'status.outdated',label:'分析待更新',rule:'报告状态是 complete、有收盘价，但报告观察日早于当前观察日，或行情截至日不同于当前观察日。',note:'只说明记录还没对齐当前观察日，不是行情信号，也不是买卖建议。'},
    {key:'status.ready',label:'当日已有分析',rule:'报告状态是 complete、有收盘价、报告观察日等于当前观察日，且行情截至日也等于当前观察日。',note:'只说明本机已有对齐观察日的分析记录，不是行情信号，也不是买卖建议。'},
    {key:'attention.pending',label:'需要看',rule:'‘需要看’= 尚未分析 / 分析待更新 / 分析不完整，只反映本机研究记录的完成度，不是行情信号，也不是买卖建议。',note:'待处理不含分析进行中和当日已有分析。排序为分析不完整、尚未分析、分析待更新，同状态按代码升序，最多 3 只。不按涨跌或评分排序。'},
    {key:'trend.bull',label:'均线多头排列',rule:'连续有效收盘不少于 20 根，且 MA5 > MA10 > MA20。三条均线都是截至观察日、含当日的收盘算术平均。',note:'只描述三条均线的相对位置，不是行情信号，也不是买卖建议。'},
    {key:'trend.bear',label:'均线空头排列',rule:'连续有效收盘不少于 20 根，且 MA5 < MA10 < MA20。',note:'只描述三条均线的相对位置，不是行情信号，也不是买卖建议。'},
    {key:'trend.mixed',label:'均线交错',rule:'连续有效收盘不少于 20 根，但不满足 MA5 > MA10 > MA20，也不满足 MA5 < MA10 < MA20。',note:'只说明三条均线没有形成单向排列，不是行情信号，也不是买卖建议。'},
    {key:'trend.insufficient',label:'数据不足',rule:'连续有效收盘少于 20 根，算不出 MA20，因此不判断均线排列。',note:'样本不足就留空，不把缺失补成 0，也不是买卖建议。'},
    {key:'indicator.windows',label:'样本门槛',rule:'RSI14 至少需要 15 根连续有效收盘；MACD(12,26,9) 至少需要 60 根连续有效收盘才计算 DIF、DEA 和柱值；均线排列至少需要 20 根。',note:'不够长度时对应结果留空，不补零，也不是买卖建议。'},
    {key:'breadth.bins',label:'涨跌分布',rule:'七组互不重叠：≤ −5% 含 −5% 为最左组；−5% 与 −3% 之间含 −3%、不含 −5% 为第二组；−3% 与 0 之间不含两端；0 为平盘；0 与 3% 之间不含两端；3% 与 5% 之间含 3%、不含 5% 为第六组；≥ 5% 含 5% 为最右组。',note:'只统计有成交且涨跌幅有效的股票。分组边界不是买卖建议。'},
    {key:'temperature.break_rate',label:'炸板率',rule:'炸板率 = 炸板池股票数 ÷ 涨停池与炸板池按代码去重后的并集。涨停池或炸板池缺失，或并集为空时留空，不记为 0。与前一交易日对比；盘中数据尚未定稿。',note:'涨跌停与连板反映短线情绪。炸板率只描述池子的数量关系，不是买卖建议。'}
  ];
  const byKey=Object.fromEntries(rules.map(r=>[r.key,r]));
  const pendingRank={incomplete:0,missing:1,outdated:2};
  function get(key){return byKey[key]||null;}
  function formatRule(entry){
    if(!entry||!entry.rule)return '';
    return `<details class="rule-note"><summary>规则</summary><p>${esc(entry.rule)}</p>${entry.note?`<p class="rule-note-aside">${esc(entry.note)}</p>`:''}</details>`;
  }
  function ruleNote(key){return formatRule(byKey[key]);}
  function inlineRule(key){
    const entry=byKey[key];
    if(!entry||!entry.rule)return '';
    return `<p class="footnote rule-inline">${esc(entry.rule)}</p>${entry.note?`<p class="footnote rule-inline">${esc(entry.note)}</p>`:''}`;
  }
  function pendingPreview(items,limit){
    const n=Number.isInteger(limit)&&limit>0?limit:3;
    return (Array.isArray(items)?items:[]).filter(row=>row&&Object.prototype.hasOwnProperty.call(pendingRank,row.status)).slice()
      .sort((a,b)=>pendingRank[a.status]-pendingRank[b.status]||String(a.thscode).localeCompare(String(b.thscode))).slice(0,n);
  }
  function trendKey(label){
    return {'均线多头排列':'trend.bull','均线空头排列':'trend.bear','均线交错':'trend.mixed','数据不足':'trend.insufficient'}[label]||'';
  }
  function statusKey(status){return 'status.'+status;}
  const loadError='自选完成度读取失败，市场概览其余部分不受影响。';
  function cardHTML(data){
    const rule=inlineRule('attention.pending');
    const items=Array.isArray(data&&data.items)?data.items:[];
    if(!items.length)return `<p class="empty-hint">还没有自选。到「我的工作台」写下关注后，这里会按研究记录是否完成，列出需要看的股票。</p>${rule}`;
    const stocks=Number.isFinite(data.counts&&data.counts.stocks)?data.counts.stocks:items.length;
    const pending=Number.isFinite(data.counts&&data.counts.pending)?data.counts.pending:items.filter(row=>Object.prototype.hasOwnProperty.call(pendingRank,row&&row.status)).length;
    const rows=pendingPreview(items,3);
    const list=rows.length?`<div class="attention-list">${rows.map(row=>{
      const name=get('status.'+row.status);
      return `<button type="button" class="attention-row" data-open-desk="${esc(row.thscode)}"><span><strong>${esc(row.name||'—')}</strong><small>${esc(row.thscode)}</small></span><span class="desk-badge ${esc(row.status)}">${esc(name?name.label:row.status)}</span></button>`;
    }).join('')}</div>`:'<p class="empty-hint">当前观察日没有待处理的自选。</p>';
    return `<p class="attention-count">自选 ${stocks} 只 · 待处理 ${pending} 只</p>${list}${rule}`;
  }
  return {rules,get,formatRule,ruleNote,inlineRule,pendingPreview,trendKey,statusKey,esc,pendingRank,loadError,cardHTML};
});
