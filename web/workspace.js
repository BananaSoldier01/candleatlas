'use strict';
let researchData=null, researchVersion=0, activeTheme=null, watchDraft=null, searchVersion=0;
const stockLink=s=>`<button class="stock-link" data-stock="${esc(s.thscode)}" data-name="${esc(s.name)}">${esc(s.name)} <small>${esc(s.thscode)}</small></button>`;
const signed=n=>n==null?'—':`${n>0?'+':''}${n.toFixed(1)}`;
function renderContext(){
  $('observe-stock').disabled=!state.stock;
  if(!state.stock){$('stock-context').textContent='从热股榜、题材或搜索结果选择股票。';return;}
  const code=state.stock.thscode;
  const pool=state.counts?.stocks?.find(s=>s.thscode===code);
  const hot=state.hotItems?.find(s=>s.thscode===code);
  $('stock-context').textContent=`${pool?`${pool.continue_day_text||'涨停'} · ${pool.limit_up_reason||'原因未披露'}`:state.counts?.stocks?'未在当日涨停池':'涨停身份待数据确认'}${hot?` · 热榜第 ${hot.rank} 名`:state.hotItems?' · 未入当日 Top30':' · 热榜待确认'}。`;
}
async function loadResearch(){
  const version=++researchVersion;researchData=null;activeTheme=null;state.hotItems=null;
  renderContext();$('research-status').textContent=`${state.date} · 读取中`;
  $('research-errors').hidden=true;$('market-metrics').textContent='正在查询涨跌停、炸板和上一交易日数据…';
  $('theme-list').textContent='正在读取…';$('theme-detail').textContent='';$('promotion-list').textContent='';$('promotion-summary').textContent='';
  try{
    const data=await api('research',{date:state.date});if(version!==researchVersion)return;
    researchData=data;
    $('research-status').textContent=`${data.date} · ${data.provisional?'盘中，尚未定稿':'日度复盘'}`;
    $('market-metrics').innerHTML=[['up','涨停'],['down','跌停'],['broken','炸板'],['break_rate','炸板率'],['height','最高连板']].map(([key,label])=>{
      const n=data.summary[key],old=data.previous?.[key],delta=n==null||old==null?null:n-old;
      return `<div><span>${label}</span><strong>${n==null?'—':key==='break_rate'?n.toFixed(1)+'%':n}</strong><small>${delta==null?'缺少可比数据':`较 ${data.previous_date} ${signed(delta)}${key==='break_rate'?' 个百分点':''}`}</small></div>`;
    }).join('');
    const errors=Object.entries(data.errors);if(errors.length){$('research-errors').hidden=false;$('research-errors').textContent=errors.map(([key])=>{const [day,kind]=key.split(':');return `${day} ${ {up:'涨停池',down:'跌停池',break:'炸板池'}[kind]||'数据'}暂不可用，相关指标显示缺失`;}).join('；');}
    if(data.themes===null)$('theme-list').textContent='涨停池获取失败，无法归类';
    else if(!data.themes.length)$('theme-list').textContent='该日涨停池为空';
    else renderThemes();
    const rows=data.promotions;
    if(rows===null){$('promotion-summary').textContent='缺少当日或前一交易日数据，暂不判断晋级';return;}
    const advanced=rows.filter(r=>r.status==='晋级').length;
    $('promotion-summary').textContent=`${data.previous_date||'无前日'} → ${data.date} · 昨日连板 ${rows.length} 只，${advanced} 只晋级${rows.length?`（${(advanced/rows.length*100).toFixed(1)}%）`:''}${data.provisional?' · 盘中暂态':''}`;
    $('promotion-list').innerHTML=rows.length?`<table><thead><tr><th>股票</th><th>昨日</th><th>今日</th><th>跟踪结果</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${stockLink(r)}</td><td>${r.previous_boards} 板</td><td>${r.current_boards??'—'}</td><td>${esc(r.status)}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">上一交易日没有 2 连板及以上样本。</p>';
  }catch(e){if(version===researchVersion){$('research-status').textContent='获取失败';$('market-metrics').textContent=e.message;$('theme-list').textContent='暂无可用数据';}}
}
function renderThemes(){
  if(!researchData?.themes)return;
  const query=$('theme-search').value.trim().toLowerCase(),cluster=$('theme-clusters').checked;
  const rows=researchData.themes.map((g,i)=>({g,i})).filter(({g})=>(!cluster||g.count>=2)&&g.name.toLowerCase().includes(query));
  $('theme-count').textContent=`${rows.length} 条`;
  $('theme-list').innerHTML=rows.length?rows.map(({g,i})=>`<button data-theme="${i}"><b>${esc(g.name)}</b><span>${g.count} 只 <small>最高 ${g.height} 板</small></span></button>`).join(''):'<p class="empty-hint">暂无匹配线索，试试取消筛选。</p>';
  if(rows.length)selectTheme(rows.some(r=>r.i===activeTheme)?activeTheme:rows[0].i);
  else $('theme-detail').innerHTML='<div class="placeholder">选择左侧线索查看股票明细</div>';
}
$('theme-search').addEventListener('input',renderThemes);
$('theme-clusters').addEventListener('change',renderThemes);
function selectTheme(index){
  const group=researchData?.themes?.[index];if(!group)return;activeTheme=index;
  for(const b of $('theme-list').querySelectorAll('button'))b.setAttribute('aria-pressed',String(Number(b.dataset.theme)===index));
  $('theme-detail').innerHTML=`<h3>${esc(group.name)} · ${group.count} 只</h3><table><thead><tr><th>股票</th><th>连板</th><th>涨停时间</th><th>原始原因</th></tr></thead><tbody>${group.stocks.map(s=>`<tr><td>${stockLink(s)}</td><td>${esc(s.continue_day_text||'—')}</td><td>${esc(s.limit_up_time||'—')}</td><td>${esc(s.limit_up_reason||'—')}</td></tr>`).join('')}</tbody></table>`;
}
$('theme-list').addEventListener('click',e=>{const b=e.target.closest('[data-theme]');if(b)selectTheme(Number(b.dataset.theme));});
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-stock]');if(!b)return;
  const origin=location.hash.slice(1)||'market';
  if(origin!=='stocks')document.dispatchEvent(new CustomEvent('research-origin',{detail:origin}));
  selectStock({thscode:b.dataset.stock,name:b.dataset.name});
  if(b.closest('#search-results'))$('search-results').textContent='';
  showWorkspace('stocks');
});
$('stock-search').addEventListener('submit',async e=>{
  e.preventDefault();const version=++searchVersion,q=$('search-query').value.trim();if(!q)return;
  $('search-results').textContent='搜索中…';
  try{const data=await api('search',{q});if(version!==searchVersion)return;$('search-results').innerHTML=data.items.length?data.items.map(stockLink).join(''):'未找到匹配的 A 股，请尝试完整名称或代码。';}
  catch(err){if(version===searchVersion)$('search-results').textContent=err.message;}
});
document.addEventListener('stock-selected',renderContext);
document.addEventListener('context-updated',renderContext);
document.addEventListener('day-selected',loadResearch);
if(state.date)loadResearch();

const pages={guide:['新手指南','从看懂一根 K 线开始'],news:['资讯','关注最新市场消息'],settings:['设置','管理本机数据源与连接'],market:['市场总览','把握市场结构与每日变化'],themes:['异动线索','从全市场涨跌追踪相关事件'],boards:['连板跟踪','晋级表现与完整涨停清单'],stocks:['个股研究','搜索 A 股 · 行情与热度'],watch:['我的工作台','以自选股为中心，继续你的研究']};
function showWorkspace(page,updateHash=true){
  if(!pages[page])page='watch';
  for(const section of document.querySelectorAll('[data-workspace]'))section.hidden=section.dataset.workspace!==page;
  for(const link of document.querySelectorAll('[data-page]')){const active=link.dataset.page===page;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  $('page-title').textContent=pages[page][0];$('page-description').textContent=pages[page][1];
  if(updateHash&&location.hash!=='#'+page)location.hash=page;
  document.querySelector('main').scrollTop=0;
  document.querySelector('.tools').hidden=page==='news'||page==='guide';
  document.dispatchEvent(new CustomEvent('workspace-selected',{detail:page}));
  requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
}
document.querySelector('.workspace-nav').addEventListener('click',event=>{const link=event.target.closest('[data-page]');if(!link)return;event.preventDefault();showWorkspace(link.dataset.page);});
window.addEventListener('hashchange',()=>showWorkspace(location.hash.slice(1),false));
showWorkspace(location.hash.slice(1),false);

document.addEventListener('day-selected',()=>{$('sync-day').disabled=false;});
if(state.date)$('sync-day').disabled=false;
$('sync-day').addEventListener('click',async()=>{
  const day=state.date;if(!day)return;
  $('sync-day').disabled=true;$('sync-message').hidden=false;$('sync-message').textContent=`正在重新同步 ${day} 的股票池和热榜…`;
  try{
    const response=await fetch(`/api/sync-day?date=${encodeURIComponent(day)}`,{method:'POST'});
    const result=await response.json();if(!response.ok)throw Error(result.error||'同步失败');
    const names={up:'涨停',down:'跌停',break:'炸板',hot:'热榜'};
    if(state.date===day)await loadDay();
    $('sync-message').textContent=`${day}：`+Object.entries(result.results).map(([k,v])=>`${names[k]}${v.ok?'已更新':'同步失败，原记录保留'}`).join('；');
  }catch(e){$('sync-message').textContent=e.message;}
  finally{$('sync-day').disabled=false;}
});
