'use strict';
(() => {
  let mode='topics',offset=0,version=0,detailVersion=0,data=null,selected='',loadedDate='';
  const money=n=>Number.isFinite(n)?n>=1e8?(n/1e8).toFixed(2)+' 亿元':(n/1e4).toFixed(2)+' 万元':'—';
  const pct=n=>`${n>0?'+':''}${n.toFixed(2)}%`;
  const timestamp=n=>new Date(n).toLocaleString('sv-SE',{timeZone:'Asia/Shanghai'});
  function render(){
    $('clue-list').innerHTML=data.items.map(r=>`<button data-clue-code="${esc(r.thscode)}" aria-pressed="${selected===r.thscode}"><span>${esc(r.name)}<small>${esc(r.thscode)}</small></span><b class="${mode==='up'?'quote-up':'quote-down'}">${pct(r.price_change_ratio_pct)}</b></button>`).join('')||'<p class="empty-hint">该门槛下没有符合条件的股票。</p>';
  }
  async function select(code){
    const row=data?.items.find(r=>r.thscode===code);if(!row)return;
    selected=code;render();const token=++detailVersion,cutoff=timestamp(data.timestamp),day=data.date;
    const start=new Date(day+'T00:00:00+08:00');start.setDate(start.getDate()-6);
    const from=start.toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
    $('clue-detail').innerHTML=`<div class="panel-head"><h3>${esc(row.name)} <small>${esc(code)}</small></h3><button class="stock-link" data-stock="${esc(code)}" data-name="${esc(row.name)}">进入个股研究 ↗</button></div><div class="clue-facts"><div><small>快照涨跌幅</small><b class="${row.price_change_ratio_pct>0?'quote-up':'quote-down'}">${pct(row.price_change_ratio_pct)}</b></div><div><small>最新价</small><b>${row.last_price.toFixed(2)}</b></div><div><small>成交额</small><b>${money(row.turnover)}</b></div></div><h3>近期新闻线索</h3><p class="footnote">${from} 至 ${esc(cutoff)} · 仅筛选东财最近 10 条检索结果。同期消息不等于涨跌原因，消息发布时间也不能证明市场何时获知。</p><p id="clue-news-status" class="footnote" role="status">正在查询…</p><div id="clue-news"></div>`;
    try{
      const d=await api('stock-news',{code,date:day});if(token!==detailVersion)return;
      const rows=d.items.filter(r=>r.time>=from+' 00:00:00'&&r.time<=cutoff);
      $('clue-news-status').textContent=`${d.stale?d.warning:'东财按股票代码检索，可能仅提及该股。'} 获取时间 ${d.updated_at}（北京时间）`;
      $('clue-news').innerHTML=rows.map(r=>`<article class="stock-news-item"><time>${esc(r.time)}</time><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a><small>${esc(r.source)} · 搜索相关</small></article>`).join('')||'<p class="empty-hint">最近返回的结果中没有此时段消息；不代表没有相关新闻，也无法据此判断涨跌原因。</p>';
    }catch(e){if(token===detailVersion)$('clue-news-status').textContent=e.message;}
  }
  async function load(){
    const token=++version;++detailVersion;data=null;selected='';loadedDate=state.date;
    $('research-section').hidden=mode!=='limit';$('mover-section').hidden=mode==='limit';$('clue-filters').hidden=mode==='limit';
    for(const b of $('clue-tabs').querySelectorAll('button')){b.classList.toggle('active',b.dataset.clue===mode);b.setAttribute('aria-pressed',String(b.dataset.clue===mode));}
    $('clue-status').textContent='';$('clue-count').textContent='';
    $('clue-source-summary').hidden=true;
    const grouped=['topics','finance','concept','industry'].includes(mode);
    $('grouped-clues').hidden=!grouped;
    if(grouped){$('mover-section').hidden=true;$('clue-filters').hidden=true;document.dispatchEvent(new CustomEvent('clue-kind',{detail:mode}));return;}
    document.dispatchEvent(new CustomEvent('clue-kind',{detail:null}));
    if(mode==='limit')return;
    $('clue-list').textContent='正在读取全市场行情…';$('clue-detail').innerHTML='<p class="empty-hint">选择左侧股票查看相关线索。</p>';
    $('clue-prev').disabled=true;$('clue-next').disabled=true;$('clue-page').textContent='';
    if(!state.date){$('clue-list').textContent='等待交易日历，请先确认数据源配置。';return;}
    try{
      const d=await api('movers',{date:state.date,direction:mode,threshold:$('clue-threshold').value,offset});if(token!==version)return;data=d;
      $('clue-count').textContent=`符合条件 ${d.total} 只 · ${d.date} ${d.snapshot_source==='local'?'本地快照':'上游快照'}`;
      $('clue-status').textContent=`行情时间 ${timestamp(d.timestamp)}（北京时间） · ${d.received} 条行情 / ${d.universe} 个代码。${d.note}`;
      $('clue-page').textContent=d.total?`${Math.floor(offset/50)+1} / ${Math.ceil(d.total/50)}`:'0 / 0';$('clue-prev').disabled=offset===0;$('clue-next').disabled=offset+50>=d.total;
      render();if(d.items.length)select(d.items[0].thscode);
    }catch(e){if(token===version){$('clue-list').textContent=dataIssueTitle(e);$('clue-detail').textContent=e.message;$('clue-status').textContent=e.message;}}
  }
  const families={themes:['topics','finance','limit'],sectors:['concept','industry'],movers:['up','down']};
  $('clue-families').addEventListener('click',e=>{const b=e.target.closest('[data-family]');if(!b)return;
    for(const tab of $('clue-families').querySelectorAll('button')){const active=tab===b;tab.classList.toggle('active',active);tab.setAttribute('aria-pressed',String(active));}
    for(const tab of $('clue-tabs').querySelectorAll('button'))tab.hidden=!families[b.dataset.family].includes(tab.dataset.clue);
    mode=families[b.dataset.family][0];offset=0;load();
  });
  $('clue-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-clue]');if(b){mode=b.dataset.clue;offset=0;load();}});
  $('clue-threshold').addEventListener('change',()=>{offset=0;load();});
  $('clue-list').addEventListener('click',e=>{const b=e.target.closest('[data-clue-code]');if(b)select(b.dataset.clueCode);});
  $('clue-refresh').addEventListener('click',load);
  $('clue-prev').addEventListener('click',()=>{offset=Math.max(0,offset-50);load();});
  $('clue-next').addEventListener('click',()=>{offset+=50;load();});
  document.addEventListener('day-selected',()=>{offset=0;++version;++detailVersion;data=null;if(location.hash==='#themes')load();});
  document.addEventListener('workspace-selected',e=>{if(e.detail==='themes'){const retained=loadedDate===state.date&&(mode==='limit'||(['topics','finance','concept','industry'].includes(mode)&&$('group-stocks')));if(!retained)load();}else {++version;++detailVersion;}});
  if(location.hash==='#themes')load();
})();
