'use strict';
const $ = id => document.getElementById(id);
const state = {tradingDates:[], date:'', countDays:20, trendDays:5, stock:null, counts:null, trend:null, generation:0, trendGeneration:0, board:'all', view:'price', prices:null, priceGeneration:0, priceDays:60, priceRange:null, priceCycle:'day'};
const colors = ['#a5c4b1','#549b79','#257555','#e2ab53','#c66441'];
const labels = ['首板','2 连板','3 连板','4 连板','5 连板及以上'];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function formatShares(value){
  if(!Number.isFinite(value)||value<0)return '—';
  if(value>=1e8)return `${(value/1e8).toFixed(2)} 亿股`;
  if(value>=1e4)return `${(value/1e4).toFixed(2)} 万股`;
  return `${value.toLocaleString('zh-CN',{maximumFractionDigits:0})} 股`;
}
const shortDate = d => d.slice(5).replace('-','/');
function message(id, text) { $(id).innerHTML = `<div class="placeholder">${esc(text)}</div>`; }
async function api(path, params={}) {
  const response = await fetch(`/api/${path}?${new URLSearchParams(params)}`);
  const result = await response.json();
  if (!response.ok) {
    const error=new Error(result.error || '请求失败，请重试');error.reason=result.reason;throw error;
  }
  return result;
}
function dataIssueTitle(error) {
  return {date_mismatch:'数据日期不符',incomplete:'数据核验未完整',not_collected:'历史未采集',upstream_empty:'上游返回空数据',invalid_snapshot:'快照数据无效',no_matching_evidence:'暂无匹配的公告线索'}[error.reason]||'数据读取失败';
}
function setSegment(id, n) {
  for (const button of $(id).querySelectorAll('button')) {
    const selected = Number(button.dataset.days) === n;
    button.classList.toggle('active',selected);
    button.setAttribute('aria-pressed',String(selected));
  }
}
function renderCounts() {
  if (!state.counts) return;
  const rows = state.counts.items;
  const selected = rows.find(r=>r.date===state.date);
  $('total').textContent = selected?.total ?? '—';
  $('first').textContent = selected?.counts?.[0] ?? '—';
  $('multi').textContent = selected?.counts ? selected.counts.slice(1).reduce((a,b)=>a+b,0) : '—';
  $('count-caption').textContent = `${state.date} · ${state.counts.provisional ? '盘中数据，尚未定稿' : '涨停池统计'}${selected?.unknown ? ` · ${selected.unknown} 只连板数缺失` : ''}`;
  const W=Math.max($('bars').clientWidth,650), H=250, L=38, R=12, T=32, B=34;
  const ymax=Math.max(10,Math.ceil(Math.max(...rows.map(r=>r.total||0))/10)*10);
  const height=H-T-B, step=(W-L-R)/rows.length, bw=Math.min(38,step*.58);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="每日涨停股票数量堆叠柱状图">`;
  for(let i=0;i<=4;i++) {
    const value=ymax*i/4,y=T+height-height*i/4;
    svg+=`<line class="grid" x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/><text x="${L-10}" y="${y+4}" text-anchor="end">${Math.round(value)}</text>`;
  }
  rows.forEach((row,i)=>{
    const x=L+step*(i+.5), selected=row.date===state.date;
    const description=row.error ? `${row.date}：${row.error}` : `${row.date}，涨停 ${row.total} 只；${labels.map((l,j)=>`${l} ${row.counts[j]} 只`).join('，')}${row.unknown ? `，连板数缺失 ${row.unknown} 只` : ''}`;
    svg+=`<g class="bar-group" tabindex="0" role="button" data-date="${row.date}" aria-label="${esc(description)}"><title>${esc(description)}</title><rect class="bar-bg" x="${x-step/2+2}" y="${T-20}" width="${step-4}" height="${height+40}" rx="4"/>`;
    let base=T+height;
    if(row.counts) {
      [...row.counts,row.unknown].forEach((n,j)=>{
        const h=height*n/ymax;
        base-=h;
        if(n) svg+=`<rect data-board="${j<5?j+1:'all'}" x="${x-bw/2}" y="${base}" width="${bw}" height="${h}" fill="${colors[j]||'#a4a4a4'}"/>`;
      });
      svg+=`<text class="value" x="${x}" y="${base-9}" text-anchor="middle">${row.total}</text>`;
    } else svg+=`<text x="${x}" y="${base-12}" text-anchor="middle">缺失</text>`;
    const labelEvery = Math.max(1, Math.ceil(42 / step));
    if (i === rows.length - 1 || (i % labelEvery === 0 && rows.length - 1 - i >= labelEvery)) {
      svg+=`<text class="${selected?'selected-label':''}" x="${x}" y="${H-10}" text-anchor="middle">${shortDate(row.date)}</text>`;
    }
    svg+='</g>';
  });
  $('bars').innerHTML=svg+'</svg>';
  const failures=rows.filter(r=>r.error);
  const unknown=rows.some(r=>r.unknown);
  $('count-note').textContent=`含首板、ST 及上游收录的新股；按同花顺涨停池统计，不计炸板池。${failures.length?`${failures.length} 日获取失败，未按 0 统计；悬停对应日期查看原因。`:''}${unknown?'灰色为连板数缺失。':''}点击柱子切换观察日。`;
}
function renderPool() {
  for (const button of $('pool-filter').querySelectorAll('button')) {
    const active = button.dataset.board === state.board;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  }
  const stocks = state.counts?.stocks;
  if (!Array.isArray(stocks)) {
    $('pool-summary').textContent = `${state.date} · 清单未就绪`;
    message('pool-list', state.counts?.items.find(r=>r.date===state.date)?.error || '正在载入涨停清单…');
    return;
  }
  const tier = s => Number.isInteger(s.continue_day_cnt) && s.continue_day_cnt >= 1 ? String(Math.min(5,s.continue_day_cnt)) : 'unknown';
  const rows = stocks.filter(s=>state.board==='all'||tier(s)===state.board)
    .sort((a,b)=>(b.continue_day_cnt||0)-(a.continue_day_cnt||0)||String(a.limit_up_time||'99:99').localeCompare(String(b.limit_up_time||'99:99')));
  $('pool-summary').textContent = `${state.date} · 显示 ${rows.length} / ${stocks.length} 只`;
  if (!rows.length) {message('pool-list','该日此层级暂无涨停股票');return;}
  $('pool-list').innerHTML = `<table><thead><tr><th>股票名称</th><th>代码</th><th>连板数</th><th>涨停时间</th><th>涨停原因</th></tr></thead><tbody>${rows.map(s=>`<tr><td><button class="stock-link" data-stock="${esc(s.thscode)}" data-name="${esc(s.name)}">${esc(s.name||'—')}</button></td><td>${esc(s.thscode||s.ticker||'—')}</td><td>${esc(Number.isInteger(s.continue_day_cnt)&&s.continue_day_cnt>=1 ? (s.continue_day_cnt===1?'首板':`${s.continue_day_cnt} 连板`) : '未知')}${s.continue_day_text?`<small>${esc(s.continue_day_text)}</small>`:''}</td><td>${esc(s.limit_up_time||'—')}</td><td>${esc(s.limit_up_reason||'—')}</td></tr>`).join('')}</tbody></table>`;
}
function renderTrend() {
  if(!state.trend) return;
  const items=state.trend.items, valid=items.filter(i=>i.rank!==null);
  const last=items.at(-1)?.rank, first=items[0]?.rank;
  $('last-rank').textContent=last==null?'—':`#${last}`;
  $('best-rank').textContent=valid.length?`#${Math.min(...valid.map(i=>i.rank))}`:'—';
  $('rank-change').textContent=first==null||last==null?'首末日数据不足':first===last?'较窗口首日持平':`${first>last?'上升':'下降'} ${Math.abs(first-last)} 名`;
  if(!valid.length) { message('trend','该窗口暂无排名数据；未用 0 或榜外排名代替。'); return; }
  const W=Math.max($('trend').clientWidth,420),H=235,L=48,R=24,T=25,B=35;
  const worst=Math.max(5,...valid.map(i=>i.rank));
  const maximum=Math.ceil(worst/5)*5;
  const x=i=>L+i*(W-L-R)/Math.max(items.length-1,1);
  const y=rank=>T+(rank-1)/(maximum-1)*(H-T-B);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(state.stock.name)}最近 ${state.trendDays} 个交易日热度排名">`;
  const ticks=[1,...[1,2,3,4].map(i=>Math.round(1+(maximum-1)*i/4))];
  for(const rank of [...new Set(ticks)]) svg+=`<line class="grid" x1="${L}" y1="${y(rank)}" x2="${W-R}" y2="${y(rank)}"/><text x="${L-12}" y="${y(rank)+4}" text-anchor="end">${rank}</text>`;
  let path='', connected=false;
  items.forEach((item,i)=>{
    if(item.rank==null){connected=false;return;}
    path+=`${connected?'L':'M'}${x(i)},${y(item.rank)} `;connected=true;
  });
  svg+=`<path class="rank-line" d="${path}"/>`;
  items.forEach((item,i)=>{
    if(item.rank!==null) svg+=`<g tabindex="0" aria-label="${item.date}，第 ${item.rank} 名"><title>${item.date} · 第 ${item.rank} 名</title><circle class="rank-point" cx="${x(i)}" cy="${y(item.rank)}" r="4"/>${items.length<=10?`<text class="value" x="${x(i)}" y="${y(item.rank)-12}" text-anchor="middle">${item.rank}</text>`:''}</g>`;
    if(items.length<=10||i%3===0||i===items.length-1) svg+=`<text x="${x(i)}" y="${H-10}" text-anchor="middle">${shortDate(item.date)}</text>`;
  });
  $('trend').innerHTML=svg+'</svg>';
  $('trend-note').textContent=`${items[0].date} — ${items.at(-1).date} · ${items.length} 个交易日${valid.length<items.length?`，其中 ${items.length-valid.length} 日缺失（折线断开）`:''}。第 1 名在最上方，周末及休市日已剔除。`;
}
async function loadTrend() {
  const generation=++state.trendGeneration;
  state.trend=null;
  for(const id of ['last-rank','best-rank','rank-change']) $(id).textContent='—';
  $('trend-note').textContent='按交易日查询，缺失点不会填零。';
  if(!state.stock){message('trend','该日暂无热股可选');clearPrice('该日暂无热股可选');return;}
  message('trend','正在读取历史排名…');
  try {
    const result=await api('trend',{date:state.date,days:state.trendDays,code:state.stock.thscode});
    if(generation!==state.trendGeneration)return;
    state.trend=result;renderTrend();
  } catch(e){if(generation===state.trendGeneration)message('trend',e.message);}
}
function selectStock(stock) {
  state.stock=stock;
  for(const row of $('hot-list').querySelectorAll('button')) {
    const chosen=row.dataset.code===stock.thscode;
    row.classList.toggle('selected',chosen);row.setAttribute('aria-pressed',String(chosen));
  }
  $('stock-name').textContent=stock.name;
  $('stock-code').textContent=`${stock.thscode} · 截至 ${state.date}`;
  state.trend=null;state.prices=null;++state.trendGeneration;++state.priceGeneration;
  document.dispatchEvent(new Event('stock-selected'));
  if(state.view==='price')loadPrices();else if(state.view==='heat')loadTrend();
}
async function loadDay() {
  const generation=++state.generation;
  ++state.trendGeneration;++state.priceGeneration;state.prices=null;
  clearPrice('等待选择热股…');
  const previous=state.stock;state.priceRange=null;setPricePeriod(state.priceDays);
  state.counts=null;state.trend=null;state.stock=null;
  renderPool();
  document.dispatchEvent(new Event('day-selected'));
  $('refresh').disabled=true;$('status').textContent='正在读取真实数据…';
  $('global-error').hidden=true;
  for(const id of ['total','first','multi','last-rank','best-rank','rank-change'])$(id).textContent='—';
  $('stock-name').textContent='选择一只热股';$('stock-code').textContent='日 K 与历史热度';
  $('count-caption').textContent='正在逐日汇总完整涨停池';$('count-note').textContent='首次加载需要逐日取数，已读取数据会缓存在本地。';
  $('hot-date').textContent=state.date;
  message('bars','正在逐日统计涨停股票… 首次载入稍需片刻');message('trend','等待选择热股…');
  const countsTask=api('counts',{date:state.date,days:state.countDays}).then(data=>{
    if(generation!==state.generation)return;
    state.counts=data;renderCounts();renderPool();document.dispatchEvent(new Event('context-updated'));
  }).catch(e=>{if(generation===state.generation){message('bars',e.message);message('pool-list',e.message);$('pool-summary').textContent=`${state.date} · 获取失败`;}});
  const hotTask=api('hot',{date:state.date}).then(data=>{
    if(generation!==state.generation)return;
    state.hotItems=data.items;document.dispatchEvent(new Event('context-updated'));
    if(!data.items.length){if(state.stock||previous)selectStock(state.stock||previous);else {message('trend','请搜索或从清单选择股票');clearPrice('请搜索或从清单选择股票');}return;}
    selectStock(state.stock||data.items.find(s=>s.thscode===previous?.thscode)||previous||data.items[0]);
  }).catch(e=>{if(generation===state.generation){if(state.stock||previous)selectStock(state.stock||previous);else {message('trend','请搜索或从清单选择股票');clearPrice('请搜索或从清单选择股票');}}});
  await Promise.all([countsTask,hotTask]);
  if(generation!==state.generation)return;
  $('refresh').disabled=false;
  $('status').textContent=`查询完成 ${new Date().toLocaleTimeString('zh-CN',{hour12:false})} · 历史优先读取本地`;
}
async function init() {
  try {
    const data=await api('calendar');
    if(!data.dates.length)throw new Error('暂无可用交易日');
    state.tradingDates=[...data.dates].sort();
    $('date').min=state.tradingDates[0];$('date').max=state.tradingDates.at(-1);
    $('date').value=state.tradingDates.at(-1);
    state.date=data.dates.at(-1);$('date').disabled=false;$('refresh').disabled=false;
    await loadDay();
  } catch(e) {
    $('global-error').textContent=e.message;$('global-error').hidden=false;
    $('status').textContent='连接失败';$('refresh').disabled=false;
    message('bars','暂时无法加载交易日历');message('hot-list','等待重新连接');
  }
}
$('date').addEventListener('change',()=>{
  const day=$('date').value;
  if(!state.tradingDates.includes(day)){
    $('date').value=state.date;
    $('global-error').textContent=day?'所选日期不是可用交易日，请选择交易日历范围内的开市日期。':'请选择完整日期，已保留原观察日。';
    $('global-error').hidden=false;
    return;
  }
  state.date=day;state.board='all';loadDay();
});
$('pool-filter').addEventListener('click',event=>{
  const button=event.target.closest('[data-board]');if(!button)return;
  state.board=button.dataset.board;renderPool();
});
$('refresh').addEventListener('click',()=>state.date?loadDay():init());
$('count-window').addEventListener('click',event=>{
  const n=Number(event.target.dataset.days);if(!n)return;
  state.countDays=n;setSegment('count-window',n);if(state.date)loadDay();
});
$('trend-window').addEventListener('click',event=>{
  const n=Number(event.target.dataset.days);if(!n)return;
  state.trendDays=n;setSegment('trend-window',n);loadTrend();
});
function barSelect(event){
  if(event.type==='keydown'&&!['Enter',' '].includes(event.key))return;
  const bar=event.target.closest('[data-date]');if(!bar)return;
  event.preventDefault();
  state.board=event.target.closest('[data-board]')?.dataset.board||'all';
  showWorkspace('boards');
  document.dispatchEvent(new CustomEvent('board-view',{detail:'list'}));
  if(state.date===bar.dataset.date){renderPool();return;}
  state.date=bar.dataset.date;$('date').value=state.date;loadDay();
}
$('bars').addEventListener('click',barSelect);$('bars').addEventListener('keydown',barSelect);
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{renderCounts();if(state.view==='price')renderPrices();else if(state.view==='heat')renderTrend();},100);});
let priceGeometry=null,pricePointer=null,pricePointerFrame=0;
function hidePriceCursor(){
  cancelAnimationFrame(pricePointerFrame);pricePointerFrame=0;pricePointer=null;
  $('price-crosshair')?.setAttribute('hidden','');
  $('price-cursor-readout').textContent='移动鼠标查看日期和纵轴刻度；点选或用键盘聚焦 K 线也可查看。';
}
function clearPrice(text) {
  priceGeometry=null;hidePriceCursor();
  for(const id of ['close-price','price-change','price-volume'])$(id).textContent='—';
  $('price-facts').textContent='';$('candle-detail').textContent='悬停或用键盘聚焦 K 线查看当日行情';
  $('price-label').textContent='前复权收盘价';
  $('price-note').textContent=`${state.priceRange?'自选区间':`最近 ${state.priceDays} ${ {day:"个交易日",week:"周",month:"月"}[state.priceCycle]}`} · 前复权 · 红涨绿跌`;
  message('price-chart',text);
  renderPriceTechnical([]);
}
async function loadPrices() {
  const generation=++state.priceGeneration;
  state.prices=null;document.dispatchEvent(new Event('prices-cleared'));clearPrice('正在读取行情数据…');
  if(!state.stock){clearPrice('点击热股查看日 K');return;}
  try {
    const result=await api('prices',{date:state.priceRange?.end||state.date,code:state.stock.thscode,period:state.priceDays,cycle:state.priceCycle,...(state.priceRange?{start:state.priceRange.start}:{}),...(state.priceCycle==='day'?{context:'1'}:{})});
    if(generation!==state.priceGeneration)return;
    state.prices=result;document.dispatchEvent(new Event('prices-loaded'));if(state.view==='price')renderPrices();
  } catch(e){if(generation===state.priceGeneration)clearPrice(e.message);}
}
function renderPriceTechnical(items){
  const daily=state.priceCycle==='day',enabled=daily&&$('price-technical-enabled').checked;
  $('price-technical-enabled').disabled=!daily;
  $('price-indicators-enabled').disabled=!daily;
  $('price-technical-scope').textContent=daily?'均线看走势 · 三角看穿越 · 菱形看放量':'这些标记仅用于日 K';
  $('price-technical-help').hidden=!daily;
  const indicators=daily&&$('price-indicators-enabled').checked;
  const points=enabled||indicators?PriceTechnical.visible(items,state.prices?.context_items||[]):null;
  const last=points?.findLast(p=>p.close!==null);
  const legend=$('price-technical-legend'),events=$('price-technical-events');
  legend.hidden=!(last&&enabled);events.hidden=!(last&&enabled);legend.textContent='';events.textContent='';
  $('price-indicator-summary').hidden=!(last&&indicators);
  $('price-rsi-value').textContent='';$('price-macd-value').textContent='';
  if(last&&indicators){
    $('price-rsi-value').innerHTML=PriceTechnical.glyph('line','rsi')+'RSI14 '+(last.rsi14===null?'样本不足15根':last.rsi14.toFixed(2))+' · '+esc(last.date);
    $('price-macd-value').innerHTML=last.macd_dif===null?'MACD · 样本不足60根':PriceTechnical.glyph('line','dif')+'DIF '+last.macd_dif.toFixed(4)+' '+PriceTechnical.glyph('line','dea')+'DEA '+last.macd_dea.toFixed(4)+' · 柱值 '+last.macd_hist.toFixed(4);
  }
  if(last&&enabled){
    legend.innerHTML=[5,10,20].map(n=>`<span class="ma-key ma${n}">${PriceTechnical.glyph('line','ma'+n)}MA${n} <b>${last['ma'+n]===null?'不足'+n+'根':last['ma'+n].toFixed(2)}</b></span>`).join('')+[['up','up','上穿20日线'],['down','down','下穿20日线'],['diamond','volume','放量≥1.5倍'],['candle','positive','阳线（收≥开）'],['candle','negative','阴线（收<开）']].map(([shape,key,label])=>`<span>${PriceTechnical.glyph(shape,key)}${esc(label)}</span>`).join('');
    const recent=points.flatMap(p=>p.events.map(e=>({point:p,event:e}))).slice(-5).reverse();
    events.innerHTML=recent.length?'<span class="muted">近期标记</span>'+recent.map(({point:p,event:e})=>`<button type="button" class="text-action" data-technical-event="${p.index}">${esc(p.date)} · ${esc(e.label)}</button>`).join(''):'<span class="muted">当前窗口尚无穿越或放量标记；样本不足时不标记。</span>';
  }
  return points;
}
function renderPrices() {
  if(!state.prices)return;
  const items=window.chanRows?window.chanRows(state.prices):state.prices.items;
  const cycleName={day:'日 K',week:'周 K',month:'月 K'}[state.prices.cycle||'day'];
  $('change-label').textContent=`较上一根${cycleName}`;
  const usable=b=>['open_price','close_price','high_price','low_price'].every(k=>Number.isFinite(b[k]))&&b.high_price>=b.low_price;
  const valid=items.filter(usable);
  if(!valid.length){clearPrice('该窗口暂无日 K 数据');return;}
  const last=valid.at(-1), previous=valid.at(-2);
  const technical=renderPriceTechnical(items);
  const previousClose=previous?.close_price??state.prices.previous_close;
  const change=Number.isFinite(previousClose)&&previousClose>0?(last.close_price/previousClose-1)*100:null;
  $('price-label').textContent=`${last.date} 前复权收盘价`;
  $('close-price').textContent=last.close_price.toFixed(2);
  $('price-change').textContent=change===null?'—':`${change>=0?'+':''}${change.toFixed(2)}%`;
  $('price-change').className=change===null?'':change>=0?'price-up':'price-down';
  $('price-volume').textContent=formatShares(last.volume);
  const first=valid[0], rangeChange=valid.length>1&&first.close_price>0?(last.close_price/first.close_price-1)*100:null;
  const facts=[['开盘',last.open_price.toFixed(2)],['最高',last.high_price.toFixed(2)],['最低',last.low_price.toFixed(2)],['区间最高',Math.max(...valid.map(b=>b.high_price)).toFixed(2)],['区间最低',Math.min(...valid.map(b=>b.low_price)).toFixed(2)],['区间首末收盘变化',rangeChange===null?'—':`${rangeChange>=0?'+':''}${rangeChange.toFixed(2)}%`]];
  $('price-facts').innerHTML=facts.map(([k,v])=>`<div><span>${k}</span><b>${v}</b></div>`).join('');
  const subplots=technical&&$('price-indicators-enabled').checked;
  const W=Math.max($('price-chart').clientWidth,420),H=subplots?800:410,L=56,R=14,T=24,PH=250,VT=310,VH=65;
  const averages=technical&&$('price-technical-enabled').checked?technical.flatMap(p=>[p.ma5,p.ma10,p.ma20]).filter(Number.isFinite):[];
  const lo=Math.min(...valid.map(b=>b.low_price),...averages),hi=Math.max(...valid.map(b=>b.high_price),...averages);
  const pad=Math.max((hi-lo)*.08,Math.abs(hi)*.005,.01),min=lo-pad,max=hi+pad;
  const step=(W-L-R)/items.length,body=Math.max(2,Math.min(10,step*.65));
  const y=p=>T+(max-p)/(max-min)*PH;
  const vmax=Math.max(1,...valid.map(b=>Number.isFinite(b.volume)?b.volume:0));
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(state.stock.name)}前复权${cycleName}与成交量${subplots?'、RSI14和MACD副图':''}">`;
  for(let i=0;i<5;i++){
    const price=max-(max-min)*i/4,yy=T+PH*i/4;
    svg+=`<line class="grid" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text x="${L-8}" y="${yy+4}" text-anchor="end">${price.toFixed(2)}</text>`;
  }
  svg+=`<text x="${L}" y="${VT-8}">成交量</text>`;
  items.forEach((b,i)=>{
    const x=L+(i+.5)*step;
    if(usable(b)){
      const color=b.close_price>=b.open_price?'#c65148':'#257555';
      const title=`${b.start_date?b.start_date+' — ':''}${b.date}${b.missing_days?'（'+b.missing_days+' 日无数据）':''} 开 ${b.open_price.toFixed(2)} / 高 ${b.high_price.toFixed(2)} / 低 ${b.low_price.toFixed(2)} / 收 ${b.close_price.toFixed(2)}；成交量 ${formatShares(b.volume)}${technical&&technical[i].close!==null?'；'+PriceTechnical.description(technical[i]):''}`;
      svg+=`<g tabindex="0" class="candle" data-candle="${i}" aria-label="${esc(title)}"><title>${esc(title)}</title><rect x="${x-step/2}" y="${T}" width="${step}" height="${subplots?760-T:VT+VH-T}" fill="transparent"/><line x1="${x}" y1="${y(b.high_price)}" x2="${x}" y2="${y(b.low_price)}" stroke="${color}"/><rect x="${x-body/2}" y="${y(Math.max(b.open_price,b.close_price))}" width="${body}" height="${Math.max(1,Math.abs(y(b.open_price)-y(b.close_price)))}" fill="${color}"/>`;
      if(Number.isFinite(b.volume)&&b.volume>=0){const h=b.volume/vmax*VH;svg+=`<rect x="${x-body/2}" y="${VT+VH-h}" width="${body}" height="${h}" fill="${color}" opacity=".65"/>`;}
      svg+='</g>';
    }
    const every=Math.max(1,Math.ceil(items.length/6));
    if(i===items.length-1||(i%every===0&&items.length-1-i>=every))svg+=`<text x="${x}" y="401" text-anchor="middle">${shortDate(b.date)}</text>`;
  });
  if(technical&&$('price-technical-enabled').checked)svg+=PriceTechnical.overlay(technical,{items,L,R,W,T,PH,VT,VH,step,y,vmax});
  if(window.chanOverlay)svg+=window.chanOverlay({items,L,R,W,T,PH,step,y});
  if(subplots)svg+=PriceTechnical.panels(technical,{items,L,R,W,step});
  svg+='<g id="price-crosshair" class="price-crosshair" hidden><line id="price-crosshair-x"/><line id="price-crosshair-y"/><g id="price-cursor-y"><rect rx="3"/><text class="price-cursor-label" text-anchor="middle"/></g><g id="price-cursor-date"><rect rx="3"/><text class="price-cursor-label" text-anchor="middle"/></g></g>';
  $('price-chart').innerHTML=svg+'</svg>';
  priceGeometry={items,L,R,W,T,PH,VT,VH,step,min,max,vmax,subplots:!!subplots,macdExtent:technical?PriceTechnical.macdExtent(technical):null};
  hidePriceCursor();
  $('price-note').textContent=`${items[0].start_date||items[0].date} — ${items.at(-1).date} · 前复权 · 红涨绿跌（收盘对比开盘）；${valid.length} 根${cycleName}${items.length>valid.length?`，${items.length-valid.length} 个周期无数据留空`:''}。${last.date!==(window.chanReplayEnd?.()||state.prices.end)?`区间末日暂无 K 线，最新数据为 ${last.date}。`:''}${state.prices.aggregation||''}${last.date===new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})?'包含当日数据，末根 K 线可能尚未定稿。':''}`;
}
$('view-tabs').addEventListener('click',event=>{
  const button=event.target.closest('[data-view]');if(!button)return;
  state.view=button.dataset.view;++state.priceGeneration;++state.trendGeneration;
  for(const b of $('view-tabs').querySelectorAll('button')){const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));}
  $('price-view').hidden=state.view!=='price';$('heat-view').hidden=state.view!=='heat';$('intraday-view').hidden=state.view!=='intraday';$('analysis-view').hidden=state.view!=='analysis';
  if(state.view==='price'){
    state.priceCycle=button.dataset.cycle;state.priceDays={day:60,week:12,month:6}[state.priceCycle];state.priceRange=null;
    const options={day:[20,60,120,250],week:[4,12,26,52],month:[3,6,12]}[state.priceCycle],unit={day:'日',week:'周',month:'月'}[state.priceCycle];
    $('price-window').innerHTML=options.map(n=>`<button data-period="${n}">${n} ${unit}</button>`).join('')+(state.priceCycle==='day'?'<button data-period="custom">自选区间</button>':'');
    $('cycle-caption').textContent=`${state.priceCycle==='day'?'交易日':'自然'+unit+'聚合'} · 前复权`;
    setPricePeriod(state.priceDays);if(state.stock)loadPrices();
  }else if(state.view==='heat'){if(state.trend)renderTrend();else loadTrend();}
  else if(state.view==='intraday'){setMinuteMode(button.dataset.mode);}
});
function showCandleDetail(event){
  const candle=event.target.closest('[data-candle]');
  if(candle)$('candle-detail').textContent=candle.getAttribute('aria-label');
  if(candle&&event.type==='focusin'&&priceGeometry){
    const index=Number(candle.dataset.candle),b=priceGeometry.items[index];
    if(Number.isFinite(b?.close_price))showPriceCursor(priceGeometry.L+(index+.5)*priceGeometry.step,priceGeometry.T+(priceGeometry.max-b.close_price)/(priceGeometry.max-priceGeometry.min)*priceGeometry.PH);
  }
}
function showPriceCursor(x,y){
  const g=priceGeometry,hit=PriceTechnical.cursorAt(g,x,y);
  if(!hit){hidePriceCursor();return;}
  const set=(node,values)=>{for(const [name,value]of Object.entries(values))node.setAttribute(name,value);};
  $('price-crosshair').removeAttribute('hidden');
  set($('price-crosshair-x'),{x1:hit.x,x2:hit.x,y1:g.T,y2:g.subplots?760:g.VT+g.VH});
  const dateBox=$('price-cursor-date'),dx=Math.max(g.L,Math.min(g.W-g.R-92,hit.x-46));
  set(dateBox.querySelector('rect'),{x:dx,y:hit.dateY,width:92,height:18});
  set(dateBox.querySelector('text'),{x:dx+46,y:hit.dateY+13});dateBox.querySelector('text').textContent=hit.date;
  const yGroup=$('price-cursor-y'),line=$('price-crosshair-y');
  yGroup.toggleAttribute('hidden',!hit.kind);line.toggleAttribute('hidden',!hit.kind);
  const labels={price:'光标价格',volume:'光标成交量刻度',rsi:'光标 RSI 刻度',macd:'光标 MACD 刻度'};
  if(hit.kind){
    const label=hit.kind==='volume'?hit.value>=1e8?(hit.value/1e8).toFixed(2)+'亿':hit.value>=1e4?(hit.value/1e4).toFixed(1)+'万':hit.value.toFixed(0):hit.value.toFixed(hit.kind==='macd'?4:2);
    const yy=Math.max(hit.top+1,Math.min(hit.bottom-17,hit.y-9));
    set(line,{x1:g.L,x2:g.W-g.R,y1:hit.y,y2:hit.y});
    set(yGroup.querySelector('rect'),{x:2,y:yy,width:g.L-8,height:18});
    set(yGroup.querySelector('text'),{x:(g.L-4)/2,y:yy+13});yGroup.querySelector('text').textContent=label;
  }
  const b=g.items[hit.index],dateText=b.start_date?b.start_date+' — '+b.date:hit.date;
  $('price-cursor-readout').textContent=dateText+(hit.kind?' · '+labels[hit.kind]+' '+(hit.kind==='volume'?formatShares(hit.value):hit.value.toFixed(hit.kind==='macd'?4:2)+(hit.kind==='price'?' 元':''))+'（坐标刻度，不是当天实际值）':' · 移入价格、成交量或副图区可查看纵轴刻度');
  const candle=$('price-chart').querySelector(`.candle[data-candle="${hit.index}"]`);
  $('candle-detail').textContent=candle?candle.getAttribute('aria-label'):hit.date+' · 该周期无有效行情；光标仅表示坐标刻度。';
}
function pricePointerPosition(event){
  const svg=$('price-chart').querySelector('svg'),matrix=svg?.getScreenCTM();
  if(!matrix)return;
  const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
  showPriceCursor(point.x,point.y);
}
$('price-chart').addEventListener('pointermove',event=>{
  if(event.pointerType==='touch')return;
  pricePointer={clientX:event.clientX,clientY:event.clientY};
  if(!pricePointerFrame)pricePointerFrame=requestAnimationFrame(()=>{pricePointerFrame=0;if(pricePointer)pricePointerPosition(pricePointer);});
});
$('price-chart').addEventListener('pointerdown',event=>{if(event.pointerType==='touch')pricePointerPosition(event);});
$('price-chart').addEventListener('pointerleave',hidePriceCursor);
$('price-chart').addEventListener('focusout',event=>{if(!$('price-chart').contains(event.relatedTarget))hidePriceCursor();});
$('price-chart').addEventListener('mouseover',showCandleDetail);
$('price-chart').addEventListener('focusin',showCandleDetail);
$('price-chart').addEventListener('click',showCandleDetail);
$('price-chart').addEventListener('click',pricePointerPosition);
$('price-chart').addEventListener('keydown',event=>{if(event.key==='Escape')hidePriceCursor();});
$('price-chart').addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&event.target.closest('[data-technical-marker]')){event.preventDefault();showCandleDetail(event);}});
$('price-technical-enabled').addEventListener('change',()=>{if(state.prices)renderPrices();});
$('price-indicators-enabled').addEventListener('change',()=>{if(state.prices)renderPrices();});
$('price-technical-events').addEventListener('click',event=>{
  const button=event.target.closest('[data-technical-event]');
  if(button)$('price-chart').querySelector(`.candle[data-candle="${button.dataset.technicalEvent}"]`)?.focus();
});
function setPricePeriod(period){
  for(const b of $('price-window').querySelectorAll('button')){const active=b.dataset.period===String(period);b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));}
  $('price-range').hidden=period!=='custom';$('range-error').textContent='';
}
$('price-window').addEventListener('click',event=>{
  const period=event.target.closest('[data-period]')?.dataset.period;if(!period)return;
  setPricePeriod(period);
  if(period==='custom'){$('price-start').value=state.prices?.items[0]?.date||state.date;$('price-end').value=state.prices?.end||state.date;$('price-start').max=state.date;$('price-end').max=state.date;return;}
  state.priceDays=Number(period);state.priceRange=null;if(state.stock)loadPrices();
});
$('price-range').addEventListener('submit',event=>{
  event.preventDefault();const start=$('price-start').value,end=$('price-end').value;
  if(start>end||end>state.date){$('range-error').textContent='请检查起止日期，结束日不能晚于观察日。';return;}
  state.priceRange={start,end};$('range-error').textContent='';if(state.stock)loadPrices();
});
setSegment('count-window',20);setSegment('trend-window',5);init();
