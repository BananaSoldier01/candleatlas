'use strict';
(() => {
  const board={group:'attention',kind:'hot',period:'day',expanded:false,offset:0,version:0};
  const titles={hot:'人气榜',rising:'热度飙升榜',gainers:'涨幅榜',losers:'跌幅榜',turnover:'成交额榜'};
  const amount=n=>!Number.isFinite(n)?'—':n>=1e8?`${(n/1e8).toFixed(2)} 亿`:n>=1e4?`${(n/1e4).toFixed(2)} 万`:n.toLocaleString('zh-CN');
  const stamp=n=>n?new Date(n).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'';
  function controls(){
    const kinds=board.group==='attention'?['hot','rising']:['gainers','losers','turnover'];
    $('ranking-tabs').innerHTML=kinds.map(k=>`<button data-rank="${k}" class="${k===board.kind?'active':''}" aria-pressed="${k===board.kind}">${titles[k]}</button>`).join('');
    for(const b of $('ranking-groups').querySelectorAll('button')){b.classList.toggle('active',b.dataset.group===board.group);b.setAttribute('aria-pressed',String(b.dataset.group===board.group));}
    $('ranking-period').hidden=board.group!=='attention';
    for(const b of $('ranking-period').querySelectorAll('button')){b.classList.toggle('active',b.dataset.period===board.period);b.setAttribute('aria-pressed',String(b.dataset.period===board.period));b.textContent=b.dataset.period==='hour'?'1 小时':board.kind==='rising'?'日榜':'24 小时';}
  }
  async function load(){
    if(!state.date)return;
    const version=++board.version;controls();
    $('rank-expand').hidden=true;$('rank-pagination').hidden=true;
    $('hot-date').textContent=state.date;$('ranking-note').textContent='';
    message('hot-list',board.group==='quotes'?'正在读取全市场行情，首次载入需要稍等…':'正在读取榜单…');
    try{
      const d=await api('rankings',{date:state.date,kind:board.kind,period:board.period,offset:board.offset,limit:board.expanded?(board.group==='attention'?30:50):10});
      if(version!==board.version)return;
      const attention=board.group==='attention';
      $('hot-date').textContent=`${d.source_date} · ${d.source}`;
      $('hot-list').classList.toggle('expanded',board.expanded);
      $('hot-list').innerHTML=d.items.length?`<table><thead><tr><th>排名</th><th>股票</th><th>涨跌幅</th><th>${attention?'热度':'成交额（元）'}</th>${attention?'<th>排名变化</th>':''}</tr></thead><tbody>${d.items.map(r=>{
        const pct=r.price_change_ratio_pct, change=r.rank_change;
        return `<tr><td class="rank-number">${r.rank}</td><td><button class="stock-link" data-stock="${esc(r.thscode)}" data-name="${esc(r.name)}">${esc(r.name)}<small>${esc(r.thscode)}</small></button></td><td class="${Number.isFinite(pct)?pct>0?'quote-up':pct<0?'quote-down':'':''}">${Number.isFinite(pct)?`${pct>0?'+':''}${pct.toFixed(2)}%`:'—'}</td><td>${attention?esc(r.heat??'—'):amount(r.turnover)}</td>${attention?`<td>${Number.isFinite(change)?change>0?`↑ ${change}`:change<0?`↓ ${Math.abs(change)}`:'持平':'—'}</td>`:''}</tr>`;
      }).join('')}</tbody></table>`:'<p class="empty-hint">当前范围暂无符合条件的股票。</p>';
      $('ranking-note').textContent=[attention?'沿用同花顺原始排名，热度不等于涨幅。':'按行情数值排序。',d.timestamp?`数据时间 ${stamp(d.timestamp)}。`:'历史日榜。',d.quote_timestamp?`行情时间 ${stamp(d.quote_timestamp)}。`:'',d.note,'点击股票进入个股研究。'].filter(Boolean).join(' ');
      $('rank-expand').hidden=d.total<=10&&!board.expanded;
      $('rank-expand').textContent=board.expanded?'收起榜单':`查看全部 ${d.total} 只`;
      $('rank-pagination').hidden=!board.expanded||d.total<=d.limit;
      $('rank-page').textContent=`${Math.floor(d.offset/d.limit)+1} / ${Math.ceil(d.total/d.limit)}`;
      $('rank-prev').disabled=d.offset===0;$('rank-next').disabled=d.offset+d.limit>=d.total;
    }catch(e){if(version===board.version){message('hot-list',e.message);$('ranking-note').textContent='可切换榜单或观察日；点击顶部“刷新视图”重试。';}}
  }
  document.addEventListener('open-ranking',e=>{if(!titles[e.detail])return;board.kind=e.detail;board.group=['hot','rising'].includes(board.kind)?'attention':'quotes';board.offset=0;board.expanded=false;load();});
  $('ranking-groups').addEventListener('click',e=>{const b=e.target.closest('[data-group]');if(!b)return;board.group=b.dataset.group;board.kind=board.group==='attention'?'hot':'gainers';board.offset=0;board.expanded=false;load();});
  $('ranking-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-rank]');if(!b)return;board.kind=b.dataset.rank;board.offset=0;load();});
  $('ranking-period').addEventListener('click',e=>{const b=e.target.closest('[data-period]');if(!b)return;board.period=b.dataset.period;board.offset=0;load();});
  $('rank-expand').addEventListener('click',()=>{board.expanded=!board.expanded;board.offset=0;load();});
  $('rank-prev').addEventListener('click',()=>{board.offset=Math.max(0,board.offset-50);load();});
  $('rank-next').addEventListener('click',()=>{board.offset+=50;load();});
  document.addEventListener('day-selected',()=>{board.offset=0;load();});
  if(state.date)load();
})();
