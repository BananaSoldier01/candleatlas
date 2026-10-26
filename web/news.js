'use strict';
(() => {
  let items=[],busy=false,loaded=false;
  function render(){
    const query=$('news-search').value.trim().toLowerCase();
    const topic=$('news-topic').value;
    const rows=items.filter(r=>r.content.toLowerCase().includes(query)&&(!topic||(r.topics||[]).includes(topic)));
    let day='';
    $('news-list').innerHTML=rows.map(r=>{
      const date=r.time.slice(0,10),heading=date!==day?`<h3 class="news-day">${esc(date)}</h3>`:'';day=date;
      return `${heading}<article class="news-item"><time datetime="${esc(r.time.replace(' ','T'))}+08:00">${esc(r.time.slice(11))}</time><div><p>${esc(r.content)}</p><div class="news-meta"><span>${esc(r.source)}</span>${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a>`:''}</div><div class="news-tags">${(r.topics||[]).map(t=>`<button data-topic="${esc(t)}">${esc(t)}</button>`).join('')}${(r.stocks||[]).length?`<span>来源关联</span>${r.stocks.map(x=>`<button data-stock="${esc(x.thscode)}" data-name="${esc(x.name)}">${esc(x.name)}</button>`).join('')}`:''}</div></div></article>`;
    }).join('')||'<p class="empty-hint">暂无匹配资讯。</p>';
  }
  async function load(){
    if(busy)return;busy=true;$('news-refresh').disabled=true;$('news-status').textContent='正在读取新浪快讯…';
    try{const d=await api('news');items=d.items;loaded=true;const old=$('news-topic').value;const topics=[...new Set(items.flatMap(r=>r.topics||[]))].sort();$('news-topic').innerHTML='<option value="">全部主题</option>'+topics.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join('');if(topics.includes(old))$('news-topic').value=old;render();$('news-updated').textContent=`获取时间 ${d.updated_at} · 北京时间`;$('news-status').textContent=d.stale?d.warning:`已载入 ${items.length} 条 · 60 秒内复用缓存`;}
    catch(e){$('news-status').textContent=e.message+(items.length?' 以下保留上次结果。':'');}
    finally{busy=false;$('news-refresh').disabled=false;}
  }
  $('news-refresh').addEventListener('click',load);
  $('news-search').addEventListener('input',render);
  $('news-topic').addEventListener('change',render);
  $('news-list').addEventListener('click',e=>{const b=e.target.closest('[data-topic]');if(b){$('news-topic').value=b.dataset.topic;render();}});
  document.addEventListener('workspace-selected',e=>{if(e.detail==='news'&&!loaded)load();});
  if(location.hash==='#news')load();
})();

(() => {
  let version=0,expanded=true;
  const active=()=>location.hash==='#stocks';
  async function load(){
    const token=++version,stock=state.stock,date=state.date;
    $('stock-news-list').textContent='';
    $('stock-news-target').textContent=stock?`${stock.name} · 截至 ${date}`:'选择股票查看';
    if(!stock||!date){$('stock-news-status').textContent='请选择股票。';return;}
    if(!expanded||!active())return;
    $('stock-news-status').textContent='正在查询相关资讯…';
    try{
      const d=await api('stock-news',{code:stock.thscode,date});
      if(token!==version)return;
      $('stock-news-status').textContent=`${d.stale?d.warning:'已载入 '+d.items.length+' 条'} 获取时间 ${d.updated_at}（北京时间）。`;
      $('stock-news-list').innerHTML=d.items.map(r=>`<article class="stock-news-item"><time>${esc(r.time)}</time><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a><small>${esc(r.source)} · 东方财富检索</small></article>`).join('')||'<p class="empty-hint">最近返回的消息中，没有观察日及之前的匹配资讯；不代表当时没有新闻。</p>';
    }catch(e){if(token===version)$('stock-news-status').textContent=e.message;}
  }
  $('stock-news-toggle').addEventListener('click',()=>{
    expanded=!expanded;$('stock-news-panel').hidden=!expanded;
    document.querySelector('.stock-workspace').classList.toggle('with-news',expanded);
    $('stock-news-toggle').textContent=expanded?'收起相关资讯':'展开相关资讯';
    $('stock-news-toggle').setAttribute('aria-expanded',String(expanded));
    if(expanded)load();else ++version;
    window.dispatchEvent(new Event('resize'));
  });
  $('stock-news-refresh').addEventListener('click',load);
  document.addEventListener('stock-selected',load);
  document.addEventListener('day-selected',()=>{++version;$('stock-news-list').textContent='';$('stock-news-status').textContent='等待加载所选日期…';});
  document.addEventListener('workspace-selected',e=>{if(e.detail==='stocks')load();else ++version;});
  if(active())load();
})();
