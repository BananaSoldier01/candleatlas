'use strict';
(() => {
  let version=0;
  async function load(){
    if(!state.date)return;const token=++version;
    $('home-leaders').textContent='正在读取成交行情…';
    $('breadth-time').textContent=state.date;$('breadth-content').textContent='正在读取全市场行情快照…';
    try{
      const d=await api('overview',{date:state.date});if(token!==version)return;
      $('breadth-time').textContent=new Date(d.timestamp).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
      const money=n=>Number.isFinite(n)?(n/1e8).toLocaleString('zh-CN',{maximumFractionDigits:2})+' 亿':'—';
      const max=Math.max(1,...d.bins),labels=['≤ −5%','−5% ~ −3%','−3% ~ 0','平盘','0 ~ 3%','3% ~ 5%','≥ 5%'];
      $('breadth-content').innerHTML=`<div class="breadth-metrics"><div><span>上涨</span><strong class="quote-up">${d.up}</strong></div><div><span>下跌</span><strong class="quote-down">${d.down}</strong></div><div><span>平盘</span><strong>${d.flat}</strong></div><div><span>有效成交额</span><strong>${money(d.turnover)}</strong></div></div><div class="breadth-columns"><div><h3>涨跌分布 <small>有效样本 ${d.valid} 只</small></h3><div class="breadth-histogram">${d.bins.map((n,i)=>`<div><b>${n}</b><meter min="0" max="${max}" value="${n}" class="${i<3?'negative':i>3?'positive':'neutral'}" aria-label="${labels[i]}：${n} 只"></meter><small>${labels[i]}</small></div>`).join('')}</div></div></div><details class="method-note"><summary>同花顺 · 已取 ${d.received} / ${d.universe} 条 · ${d.excluded} 条未纳入涨跌统计</summary><p class="footnote">${esc(d.note)} 成交额覆盖 ${d.turnover_sample} / ${d.traded} 只有成交股票。区间边界：−5% 计入最左组，−3% 计入第二组，3% 计入第六组，5% 计入最右组。</p></details>`;
      $('home-leaders').innerHTML=d.leaders.map((r,i)=>`<div class="activity-row"><small>${i+1}</small>${stockLink(r)}<span>${money(r.turnover)}</span></div>`).join('')||'<p class="empty-hint">暂无有效行情</p>';
    }catch(e){if(token!==version)return;
      $('home-leaders').innerHTML='<p class="empty-hint">所选日缺少对应行情。可从市场榜单寻找股票。</p>';
      $('breadth-content').innerHTML=`<div class="market-empty"><span>所选日行情暂不可用</span><p>${esc(e.message)}</p><div id="available-snapshots"></div></div>`;
      try{const d=await api('overview-dates');if(token!==version)return;const available=d.dates.filter(day=>day!==state.date).slice(-3).reverse();$('available-snapshots').innerHTML=available.map(day=>`<button class="outline-button" data-observe-day="${esc(day)}">查看 ${esc(day)} 归档 →</button>`).join('');}catch{}
    }
  }
  document.addEventListener('day-selected',load);if(state.date)load();
})();
