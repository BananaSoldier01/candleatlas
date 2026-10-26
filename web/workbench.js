'use strict';
(() => {
  let data=null,version=0,chosen='',filter='all',searchVersion=0;
  const labels={missing:'尚未分析',outdated:'分析待更新',incomplete:'分析不完整',running:'分析进行中',ready:'当日已有分析'};
  const here=()=>!location.hash||location.hash==='#watch';
  const number=(n,suffix='')=>Number.isFinite(n)?n.toFixed(2)+suffix:'—';
  function detail(row){
    if(!row){$('desk-detail').innerHTML='<div class="desk-empty"><h3>选择一只股票，继续研究</h3><p>关注理由、分析依据和下一步操作会集中显示在这里。</p></div>';return;}
    const t=row.technical,r=row.report;
    $('desk-detail').innerHTML=`<div class="desk-detail-heading"><div><h2>${esc(row.name)}</h2><p class="muted">${esc(row.thscode)}</p></div><span class="desk-badge ${row.status}">${labels[row.status]}</span></div>
    <div class="desk-actions"><button data-desk-action="analysis">${r?'更新个股分析':'开始个股分析'}</button><button data-desk-action="chart">查看行情</button><button data-desk-action="chan">缠论结构</button><button data-desk-action="note">补充研究记录</button></div>
    <section><h3>我的关注理由</h3><p class="desk-note">${esc(row.note)}</p><small class="muted">记录观察日 ${esc(row.observed)} · 共 ${row.record_count} 条有效记录</small></section>
    ${r?`<section><div class="desk-section-heading"><h3>最近分析快照</h3><button class="text-action" data-open-report="${esc(r.id)}">打开完整报告 →</button></div><p class="footnote">报告观察日 ${esc(r.day)} · 行情截至 ${esc(t.asof||'未取得')} · ${row.has_ai?'含 AI 解读':'程序技术分析'}<br>生成于 ${esc(new Date(r.created).toLocaleString('zh-CN'))}，可能是事后补做的分析。</p><div class="desk-facts"><div><small>快照收盘价</small><b>${number(t.close)}</b></div><div><small>近 20 日涨跌</small><b>${number(t.change20,'%')}</b></div><div><small>较前 5 日均量</small><b>${number(t.volume_ratio5,' 倍')}</b></div></div><p>${esc(t.trend||'尚无技术结果')}</p>${row.overview.map(x=>`<p>${esc(x.text)}</p>`).join('')}${r.error?`<p class="desk-warning">${esc(r.error)}</p>`:''}</section><section><h3>后续核对事项</h3>${row.watch.length?`<ul>${row.watch.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ul><small class="muted">来自该报告的 AI 解读；可打开完整报告核对引用。</small>`:'<p class="muted">报告尚无核对事项，可以先补充自己的研究记录。</p>'}${row.limitations.length?`<details><summary>本次分析的资料限制</summary><ul>${row.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:''}</section>`:'<div class="desk-empty"><h3>还没有保存的分析</h3><p>先计算均线、量能、RSI 和 MACD；配置模型后，可手动生成带依据的 AI 解读。</p></div>'}
    <p class="footnote">缠论入口目前提供笔、线段、中枢与逐日回放，尚未提供买卖点信号；技术画像分项与报告变化可在完整报告中查看。</p>`;
  }
  function render(){
    if(!data)return;
    const c=data.counts;$('desk-metrics').innerHTML=[['自选股票',c.stocks],['待分析 / 更新',c.pending],['当日已有分析',c.ready],['研究记录',c.records]].map(([label,n])=>`<div><small>${label}</small><strong>${n}</strong></div>`).join('');
    const q=$('desk-find').value.trim().toLowerCase();const rows=data.items.filter(r=>(filter==='all'||filter==='ready'&&r.status==='ready'||filter==='pending'&&['missing','outdated','incomplete'].includes(r.status))&&(!q||(r.name+r.thscode).toLowerCase().includes(q)));
    if(!rows.some(r=>r.thscode===chosen))chosen=rows[0]?.thscode||'';
    $('desk-list').innerHTML=rows.length?rows.map(r=>`<button class="desk-stock ${chosen===r.thscode?'selected':''}" data-desk-stock="${esc(r.thscode)}" aria-pressed="${chosen===r.thscode}"><span><strong>${esc(r.name)}</strong><small>${esc(r.thscode)}</small></span><span><b>${number(r.technical.close)}</b><small>${labels[r.status]}</small></span></button>`).join(''):`<div class="desk-empty"><h3>${data.items.length?'没有符合条件的股票':'从第一只自选股开始'}</h3><p>${data.items.length?'可切回全部或清除筛选。':'在上方查找股票，写下关注理由。已有记录会自动按股票汇总。'}</p></div>`;
    detail(rows.find(r=>r.thscode===chosen));
    $('desk-message').textContent=`截至观察日 ${data.date} · 优先展示待处理股票${data.future_records?` · ${data.future_records} 条较晚观察日的关注记录未显示`:''}`;
  }
  async function load(){
    if(!state.date||!here())return;const token=++version;$('desk-message').textContent='正在读取本机分析与自选记录…';
    try{const d=await api('workbench',{date:state.date});if(token!==version)return;data=d;render();document.dispatchEvent(new CustomEvent('watchlist-loaded',{detail:d}));}
    catch(e){if(token===version){data=null;$('desk-list').textContent='';$('desk-metrics').textContent='';$('desk-detail').textContent='';$('desk-message').textContent='工作台读取失败：'+e.message;}}
  }
  $('desk-list').addEventListener('click',e=>{const b=e.target.closest('[data-desk-stock]');if(b){chosen=b.dataset.deskStock;render();}});
  $('desk-detail').addEventListener('click',e=>{
    const b=e.target.closest('[data-desk-action]'),row=data?.items.find(r=>r.thscode===chosen);if(!b||!row)return;
    if(b.dataset.deskAction==='note'){draftObservation(row,'',state.date);return;}
    document.dispatchEvent(new CustomEvent('research-origin',{detail:'watch'}));selectStock(row);showWorkspace('stocks');
    document.querySelector(b.dataset.deskAction==='analysis'?'[data-view="analysis"]':'[data-view="price"][data-cycle="day"]').click();
    if(b.dataset.deskAction==='chan'){$('chan-enabled').checked=true;$('chan-enabled').dispatchEvent(new Event('change'));}
  });
  $('desk-filter').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;filter=b.dataset.filter;for(const x of $('desk-filter').querySelectorAll('button')){x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b));}render();});
  $('desk-find').addEventListener('input',render);$('desk-refresh').addEventListener('click',load);
  $('desk-search').addEventListener('submit',async e=>{e.preventDefault();const token=++searchVersion;$('desk-search-results').textContent='正在查找…';try{const d=await api('search',{q:$('desk-query').value.trim()});if(token!==searchVersion)return;$('desk-search-results').innerHTML=d.items.length?d.items.map(s=>`<button class="outline-button" data-observe="${esc(s.thscode)}" data-name="${esc(s.name)}">＋ ${esc(s.name)} · ${esc(s.thscode)}</button>`).join(''):'未找到股票，请尝试名称或完整代码。';}catch(e){if(token===searchVersion)$('desk-search-results').textContent=e.message;}});
  document.addEventListener('records-updated',load);
  document.addEventListener('day-selected',load);
  document.addEventListener('workspace-selected',e=>{if(e.detail==='watch')load();else ++version;});
  load();
})();
