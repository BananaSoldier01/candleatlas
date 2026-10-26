'use strict';
const minuteState={mode:'intraday',interval:1,count:120,version:0,data:null};
function setMinuteMode(mode){
  minuteState.mode=mode;
  $('minute-options').hidden=mode!=='minute';$('minute-range').hidden=mode!=='minute';
  loadMinute();
}
async function loadMinute(){
  const version=++minuteState.version;minuteState.data=null;
  $('minute-summary').textContent='';$('minute-note').textContent='';$('minute-detail').textContent='悬停或键盘聚焦查看分钟行情';
  if(!state.stock){message('minute-chart','请先选择股票');return;}
  message('minute-chart','正在读取新浪分钟行情…');
  try{
    const data=await api('intraday',{code:state.stock.thscode,date:state.date,mode:minuteState.mode,interval:minuteState.interval,count:minuteState.count});
    if(version!==minuteState.version||state.view!=='intraday')return;
    minuteState.data=data;renderMinute();
  }catch(e){if(version===minuteState.version)message('minute-chart',e.message);}
}
function renderMinute(){
  const data=minuteState.data;if(!data)return;
  const rows=data.items,last=rows.at(-1),baseline=data.previous_close;
  const change=baseline>0?(last.close/baseline-1)*100:null;
  const f=n=>n.toFixed(2);
  $('minute-summary').innerHTML=[['最新分钟价格',f(last.close)],['数据时间',last.time],['窗口最高',f(Math.max(...rows.map(r=>r.high)))],['窗口最低',f(Math.min(...rows.map(r=>r.low)))],['较首日之前收盘',change==null?'—':`${change>=0?'+':''}${change.toFixed(2)}%`]].map(([k,v])=>`<div><span>${k}</span><b>${esc(v)}</b></div>`).join('');
  const candles=data.mode==='minute';
  const times=[];
  if(candles)times.push(...rows.map(r=>r.time));
  else for(const day of data.dates){
    for(let t=570;t<=900;t++){if(t>690&&t<=780)continue;times.push(`${day} ${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`);}
  }
  const byTime=new Map(rows.map(r=>[r.time,r]));
  const W=Math.max($('minute-chart').clientWidth,650),H=390,L=58,R=20,T=24,PH=240,VT=294,VH=60;
  const minRaw=Math.min(...rows.map(r=>candles?r.low:r.close)),maxRaw=Math.max(...rows.map(r=>candles?r.high:r.close));
  const pad=Math.max((maxRaw-minRaw)*.1,maxRaw*.001,.01),min=minRaw-pad,max=maxRaw+pad;
  const step=(W-L-R)/times.length,x=i=>L+(i+.5)*step,y=v=>T+(max-v)/(max-min)*PH;
  const vmax=Math.max(1,...rows.map(r=>r.volume));
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(state.stock.name)}${candles?data.interval+' 分钟 K':data.mode==='five'?'五日分时':'分时'}">`;
  for(let i=0;i<5;i++){const value=max-(max-min)*i/4;svg+=`<line class="grid" x1="${L}" y1="${y(value)}" x2="${W-R}" y2="${y(value)}"/><text x="${L-8}" y="${y(value)+4}" text-anchor="end">${f(value)}</text>`;}
  let path='',connected=false,previousDay='';
  times.forEach((time,i)=>{
    const r=byTime.get(time),day=time.slice(0,10);
    if(!r){connected=false;return;}
    const color=r.close>=r.open?'#c65148':'#257555',bw=Math.max(.5,Math.min(10,step*.65));
    if(!candles){path+=`${connected&&previousDay===day?'L':'M'}${x(i)},${y(r.close)} `;connected=true;previousDay=day;}
    const detail=`${r.time} · 开 ${f(r.open)} / 高 ${f(r.high)} / 低 ${f(r.low)} / 收 ${f(r.close)} · 成交量 ${formatShares(r.volume)}`;
    svg+=`<g tabindex="0" data-minute-detail="${esc(detail)}" aria-label="${esc(detail)}"><title>${esc(detail)}</title><rect x="${x(i)-step/2}" y="${T}" width="${step}" height="${VT+VH-T}" fill="transparent"/>`;
    if(candles)svg+=`<line x1="${x(i)}" y1="${y(r.high)}" x2="${x(i)}" y2="${y(r.low)}" stroke="${color}"/><rect x="${x(i)-bw/2}" y="${y(Math.max(r.open,r.close))}" width="${bw}" height="${Math.max(1,Math.abs(y(r.open)-y(r.close)))}" fill="${color}"/>`;
    const vh=r.volume/vmax*VH;svg+=`<rect x="${x(i)-bw/2}" y="${VT+VH-vh}" width="${bw}" height="${vh}" fill="${color}" opacity=".5"/></g>`;
  });
  if(!candles)svg+=`<path d="${path}" fill="none" stroke="#267aa2" stroke-width="1.6" pointer-events="none"/>`;
  svg+=`<text x="${L}" y="${VT-10}">成交量（股）</text>`;
  if(data.mode==='five')data.dates.forEach((d,i)=>{const pos=x(i*241);svg+=`<line class="grid" x1="${pos}" y1="${T}" x2="${pos}" y2="${VT+VH}"/><text x="${x(i*241+120)}" y="${H-10}" text-anchor="middle">${d.slice(5)}</text>`;});
  else for(let i=0;i<times.length;i++){const every=Math.ceil(times.length/5);if(i%every===0)svg+=`<text x="${x(i)}" y="${H-10}" text-anchor="middle">${candles?times[i].slice(5):times[i].slice(11)}</text>`;}
  $('minute-chart').innerHTML=svg+'</svg>';
  $('minute-note').textContent=`新浪财经 · 不复权 · ${rows[0].time} — ${last.time} · ${rows.length} 个采样点${candles?'，'+data.interval+' 分钟 K':''}。${data.missing_dates.length?'缺少所选交易日：'+data.missing_dates.join('、')+'。':''}分钟采样不是逐笔行情；午休压缩显示，缺失时点不补值，跨日不连线。手动刷新，缓存 60 秒。`;
}
$('minute-options').addEventListener('click',e=>{const b=e.target.closest('[data-interval]');if(!b)return;minuteState.interval=Number(b.dataset.interval);for(const x of $('minute-options').querySelectorAll('button')){x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b));}loadMinute();});
$('minute-range').addEventListener('click',e=>{const b=e.target.closest('[data-count]');if(!b)return;minuteState.count=Number(b.dataset.count);for(const x of $('minute-range').querySelectorAll('button')){x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b));}loadMinute();});
function minuteDetail(e){const el=e.target.closest('[data-minute-detail]');if(el)$('minute-detail').textContent=el.dataset.minuteDetail;}
$('minute-chart').addEventListener('mouseover',minuteDetail);$('minute-chart').addEventListener('focusin',minuteDetail);
document.addEventListener('stock-selected',()=>{++minuteState.version;minuteState.data=null;if(state.view==='intraday')loadMinute();});
document.addEventListener('day-selected',()=>{++minuteState.version;minuteState.data=null;if(state.view==='intraday'){message('minute-chart','正在切换观察日…');$('minute-summary').textContent='';$('minute-note').textContent='';}});
window.addEventListener('resize',()=>{if(state.view==='intraday')renderMinute();});
