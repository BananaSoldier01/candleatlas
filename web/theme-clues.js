'use strict';
(() => {
  let kind=null,catalog=[],detail=null,selected='',version=0,detailVersion=0,financeVersion=0;
  const time=n=>n?new Date(n).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未提供';
  const pct=n=>Number.isFinite(n)?`${n>0?'+':''}${n.toFixed(2)}%`:'—';
  const evidence=row=>(row.evidence||[]).length?`<details><summary>巨潮公告依据 · ${row.evidence.length} 条</summary>${row.evidence.map(e=>`<p class="source-analysis"><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><br><small>公告日 ${esc(e.notice_date)} · 保守可用 ${esc(e.available_at.slice(0,10))} · ${esc(e.source)}</small></p>`).join('')}</details>`:row.analysis?`<details><summary>${esc(row.tag||'异动')} · 来源解读</summary><p class="source-analysis">${esc(row.analysis)}</p></details>`:'同花顺当前成分股';
  function list(){
    const q=$('group-search').value.trim();
    $('group-list').innerHTML=catalog.filter(r=>r.name.includes(q)&&(!['topics','finance'].includes(kind)||!$('group-clusters').checked||r.count>=2)).map(r=>`<button data-group-key="${esc(r.key)}" aria-pressed="${selected===r.key}"><b>${esc(r.name)}</b><span>${r.count==null?'查看成分':r.count+' 只'}</span></button>`).join('')||'<p class="empty-hint">没有匹配的线索。</p>';
  }
  function render(){
    const direction=$('group-direction')?.value||'all';
    const rows=detail.items.filter(r=>direction==='all'||(Number.isFinite(r.pct)&&(direction==='up'?r.pct>0:r.pct<0)));
    $('group-stocks').classList.toggle('announcement-clues',detail.source_kind==='cninfo');
    $('group-stocks').innerHTML=`<table><thead><tr><th>股票</th><th>涨跌幅</th><th>依据</th><th>操作</th></tr></thead><tbody>${rows.map(r=>`<tr><td><button class="stock-link" data-stock="${esc(r.thscode)}" data-name="${esc(r.name)}">${esc(r.name)}<small>${esc(r.thscode)}</small></button></td><td class="${r.pct>0?'quote-up':'quote-down'}">${pct(r.pct)}</td><td>${evidence(r)}</td><td><button data-financial="${esc(r.thscode)}" data-financial-name="${esc(r.name)}">财务指标</button><button data-observe="${esc(r.thscode)}" data-name="${esc(r.name)}" data-reason="${esc(detail.name)}：待核对后续表现">关注</button></td></tr>`).join('')}</tbody></table>${rows.length?'':'<p class="empty-hint">此筛选下暂无股票。</p>'}`;
  }
  async function choose(key){
    selected=key;list();const token=++detailVersion;++financeVersion;
    $('group-detail').textContent='正在读取线索依据与股票清单…';
    try{
      const d=await api('clue-detail',{date:state.date,kind,key});if(token!==detailVersion)return;detail=d;
      $('group-detail').innerHTML=`<h3>${esc(d.name)} · ${d.items.length} 只</h3><p id="group-quote-status" class="footnote" role="status">${d.quote_warning?esc(d.quote_warning)+' 涨跌幅保持缺失。':'行情时间 '+time(d.quote_timestamp)+(d.quote_source==='local'?' · 观察日的本地快照':' · 与观察日匹配的上游快照')}</p><details class="method-note"><summary>${d.source_kind==='cninfo'?'巨潮公告 · 标题规则归类':kind==='finance'?'业绩关键词 · 来源解读':kind==='topics'?'主题关键词 · 来源解读':'正式板块 · 当前归属'} · 查看依据与时间</summary><p class="footnote">${esc(d.note)}</p><p class="footnote">${d.source_kind==='cninfo'?'公告日 '+esc(d.notice_day)+' · 抓取时间 '+esc(d.fetched_at):'线索／成分时间 '+time(d.timestamp)} · 行情时间 ${time(d.quote_timestamp)}</p></details><nav class="detail-tabs" aria-label="线索详情"><button data-detail-view="stocks" class="active" aria-pressed="true">股票清单</button><button data-detail-view="history" aria-pressed="false">跨日跟踪</button></nav><div id="group-current"><label class="group-direction-label">股票表现 <select id="group-direction"><option value="all">全部</option><option value="up">上涨</option><option value="down">下跌</option></select></label><div id="group-financial"></div><div id="group-stocks" class="pool-list"></div></div><div id="group-history" hidden>正在核对跨日快照…</div>`;
      $('group-direction').addEventListener('change',render);render();
      loadHistory(key,token);
    }catch(e){if(token===detailVersion)$('group-detail').textContent=e.message;}
  }
  async function loadHistory(key,token){
    try{const d=await api('clue-history',{date:state.date,kind,key});if(token!==detailVersion)return;
      if(d.tracking_mode==='announcements'){
        $('group-history').innerHTML=`<div class="history-strip">${d.items.map(r=>`<div><small>${esc(r.date.slice(5))}</small><b>${r.count??'—'}</b><small>${r.count==null?'未采集':'只 · 公告样本'}</small></div>`).join('')}</div><p class="footnote">${esc(d.note)}</p>`;return;
      }
      $('group-history').innerHTML=`<div class="history-strip">${d.items.map(r=>`<div><small>${esc(r.date.slice(5))}</small><b>${r.count??'—'}</b><small>${r.count==null?'未采集':'只'}</small></div>`).join('')}</div><p class="footnote">较昨日：新增 ${d.entered??'—'} 只 · 退出 ${d.left??'—'} 只。${d.previous_available?`昨日固定样本行情覆盖 ${d.sample} / ${d.cohort.length} 只`:'昨日成员尚未采集'}${d.sample?`，上涨 ${d.positive} 只，平均涨跌 ${pct(d.average)}`:''}。</p><details><summary>昨日成员今日表现（包含已退出股票）</summary>${!d.previous_available?'<p class="footnote">尚无前一交易日成员快照。</p>':d.cohort.length?`<div class="pool-list"><table><thead><tr><th>股票</th><th>今日涨跌</th><th>当前归属</th></tr></thead><tbody>${d.cohort.map(r=>`<tr><td>${stockLink(r)}</td><td>${pct(r.pct)}</td><td>${r.retained==null?'未采集':r.retained?'仍在其中':'已退出'}</td></tr>`).join('')}</tbody></table></div>`:'<p class="footnote">已采集的昨日样本为空。</p>'}<p class="footnote">${esc(d.note)}</p></details>`;
    }catch(e){if(token===detailVersion)$('group-history').textContent=e.message;}
  }
  async function load(value){
    kind=value;const token=++version;++detailVersion;++financeVersion;catalog=[];detail=null;selected='';
    if(!kind)return;
    $('group-cluster-label').hidden=!['topics','finance'].includes(kind);
    $('group-list').textContent='正在读取…';$('group-detail').textContent='选择左侧主题查看股票及依据。';
    if(!state.date)return;
    try{
      const d=await api('clue-catalog',{date:state.date,kind});if(token!==version)return;
      $('clue-source-summary').hidden=!d.source_summary;$('clue-source-summary').textContent=d.source_summary||'';
      catalog=d.items;$('clue-status').textContent=d.note+' 数据时间 '+time(d.timestamp);$('clue-count').textContent='';list();
      if(catalog.length)choose(catalog[0].key);
      else $('group-detail').textContent='该日已采集的来源清单中，没有匹配的'+(kind==='finance'?'业绩关键词':'线索')+'；不代表全市场没有相关事件。';
    }catch(e){if(token===version){$('group-list').textContent=dataIssueTitle(e);$('group-detail').textContent=e.message;$('clue-status').textContent=e.message;}}
  }
  $('group-search').addEventListener('input',list);
  $('group-clusters').addEventListener('change',list);
  $('group-list').addEventListener('click',e=>{const b=e.target.closest('[data-group-key]');if(b)choose(b.dataset.groupKey);});
  $('group-detail').addEventListener('click',e=>{
    const tab=e.target.closest('[data-detail-view]');if(tab){$('group-current').hidden=tab.dataset.detailView!=='stocks';$('group-history').hidden=tab.dataset.detailView!=='history';for(const b of $('group-detail').querySelectorAll('[data-detail-view]')){b.classList.toggle('active',b===tab);b.setAttribute('aria-pressed',String(b===tab));}return;}
    const b=e.target.closest('[data-financial]');if(!b)return;++financeVersion;
    const year=new Date().getFullYear(),options=[];for(let y=year;y>=year-2;y--)for(let q=4;q>=1;q--)options.push(`${y}-${q}`);
    $('group-financial').innerHTML=`<h3>${esc(b.dataset.financialName)} · 财务核对</h3><form id="group-finance-form"><label>报告期 <select id="group-report">${options.map(x=>`<option value="${x}">${x.split('-')[0]} ${['','一季报','中报','三季报','年报'][Number(x.at(-1))]}</option>`).join('')}</select></label><button>查询指标</button></form><p class="footnote">当前查询值，不以观察日为披露截止日期；报告期尚未披露时可能无数据。</p><div id="group-finance-result" role="status"></div>`;
    const month=new Date().getMonth()+1;$('group-report').value=month>=9?`${year}-2`:month>=5?`${year}-1`:`${year-1}-4`;
    $('group-finance-form').addEventListener('submit',async ev=>{
      ev.preventDefault();const token=++financeVersion;const report=$('group-report').value;$('group-finance-result').textContent='正在查询…';
      try{const d=await api('clue-financial',{code:b.dataset.financial,report});if(token!==financeVersion)return;$('group-finance-result').innerHTML=`<p>报告期 ${esc(d.report)}</p><div class="clue-facts">${d.items.map(r=>`<div><small>${esc(r.label)}</small><b>${pct(r.value)}</b></div>`).join('')||'暂无可用指标'}</div><p class="footnote">${esc(d.note)}</p>`;}catch(err){if(token===financeVersion)$('group-finance-result').textContent=err.message;}
    });
    $('group-financial').scrollIntoView({block:'nearest'});
  });
  document.addEventListener('clue-kind',e=>load(e.detail));
  document.addEventListener('workspace-selected',e=>{if(e.detail!=='themes'){++version;++detailVersion;++financeVersion;}});
  if(location.hash==='#themes')load(document.querySelector('#clue-tabs .active')?.dataset.clue||'topics');
})();
