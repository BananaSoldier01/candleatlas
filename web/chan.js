'use strict';
(() => {
  $('chan-legend').innerHTML=[['line','bi','笔（相邻转折）'],['line','seg','线段（更大一级走势）'],['box','zs','中枢（价格重叠区）'],['line','reference','结构已确认'],['dashed','reference','结构暂未确认'],['circle','candidate','候选 · 未确认']].map(([shape,key,label])=>`<span>${PriceTechnical.glyph(shape,key)}${label}</span>`).join('');
  for(const [id,shape,key]of [['bi','line','bi'],['seg','line','seg'],['zs','box','zs'],['state','dashed','reference']])$('chan-intro-'+id).innerHTML=PriceTechnical.glyph(shape,key);
  let data=null,key='',version=0,selected='',loading=false,error='',available=[];
  const enabled=()=>$('chan-enabled').checked&&state.priceCycle==='day'&&state.view==='price';
  const sourceKey=()=>state.stock&&state.prices?`${state.stock.thscode}|${state.prices.end}|${$("chan-candidates-enabled").checked?1:0}`:'';
  const ready=()=>enabled()&&data&&key===sourceKey();
  function frame(){return ready()?data.frames.find(f=>f.date===selected):null;}
  function renderCandidates(f){
    const panel=$('chan-candidate-panel'),live=$('chan-candidate-live'),events=$('chan-candidate-events');
    panel.hidden=!(enabled()&&$('chan-candidates-enabled').checked);
    live.textContent='';events.textContent='';
    if(panel.hidden)return;
    const status=$('chan-candidate-status');
    if(!f){status.textContent=loading?'正在计算候选…':'候选数据尚未就绪。';return;}
    if(!data.candidate_meta){status.textContent='当前服务未提供候选数据，结构图仍可查看。';return;}
    if(data.candidate_meta.status!=='ok'||!Array.isArray(f.candidates)){
      status.textContent='候选计算未完成，结构图仍可查看。';return;
    }
    status.textContent=`${f.date} · 当前 ${f.candidates.length} 条未确认候选 · 观察 ${(data.candidate_meta.types||[]).join('/')} 类型；结构稳定度不代表交易确认。`;
    live.innerHTML=f.candidates.length?f.candidates.map(c=>`<p class="chan-candidate-entry" data-first-seen="${esc(c.first_seen_at)}" data-pivot-date="${esc(c.pivot_date)}">${c.is_buy?'买向候选':'卖向候选'} · ${esc(c.types.join('/'))} · ${Number(c.pivot_price).toFixed(2)}<br>拐点日 ${esc(c.pivot_date)} · 首次可见日 ${esc(c.first_seen_at)} · 未确认</p>`).join(''):'<p>当前范围尚未出现候选。</p>';
    const names={appearing:'出现',type_extended:'类型变化',moved:'结构编号变化',target_flag_changed:'目标条件变化',vanished:'消失'};
    const history=data.frames.filter(x=>x.date<=f.date).flatMap(x=>x.candidate_events||[]).slice(-12).reverse();
    events.innerHTML=history.length?history.map(e=>`<li data-observed="${esc(e.observed_at)}">${esc(e.observed_at)} · ${esc(names[e.event]||'状态变化')} · 拐点 ${esc(e.identity.pivot_date)} · 首次可见 ${esc(e.first_seen_at)} · 未确认</li>`).join(''):'<li>截至此日暂无候选变化记录。</li>';
  }

  function update(){
    const daily=state.priceCycle==='day';$('chan-enabled').disabled=!daily;
    $('chan-help').textContent=daily?'日 K · 本地计算 · 实线已确认 / 虚线暂未确认':'缠论第一版仅支持日 K';
    $('chan-panel').hidden=!enabled();$('chan-layers').hidden=!enabled();
    renderCandidates(null);
    if(!enabled())return;
    const f=frame();const dates=$('chan-date');
    dates.disabled=!f;for(const id of ['chan-prev','chan-next','chan-latest'])$(id).disabled=!f;
    $('chan-structures').textContent='';$('chan-notes').textContent='';
    if(!f){$('chan-status').textContent=loading?'正在计算历史结构…':error||'没有连续有效的历史日 K 可用于计算。';return;}
    $('chan-prev').disabled=available.findIndex(f=>f.date===selected)===0;$('chan-next').disabled=available.findIndex(f=>f.date===selected)===available.length-1;
    renderCandidates(f);
    const last=data.frames.at(-1);const count=k=>f[k].filter(x=>x.sure).length;
    $('chan-status').textContent=`${f.date} ${f.date!==last.date?'· 回放中，图表仅显示截至此日的数据':'· 当前计算末日'} · 已确认 ${count('bi')} 笔 / ${count('seg')} 线段 / ${count('zs')} 中枢；当前 K 线窗口仅显示与之重叠的结构。`;
    $('chan-structures').innerHTML=['bi','seg','zs'].map(k=>`<h4>${{bi:'笔',seg:'线段',zs:'中枢'}[k]}</h4>${f[k].length?`<ul>${f[k].map(x=>`<li>${esc(x.start)} → ${esc(x.end)} · ${k==='zs'?`${x.low.toFixed(2)}–${x.high.toFixed(2)}`:`${x.a.toFixed(2)} → ${x.b.toFixed(2)}`} · ${x.sure?`本窗口确认日 ${esc(x.confirmed_at)}`:'暂未确认'}</li>`).join('')}</ul>`:'<p>尚未形成</p>'}`).join('');
    $('chan-notes').innerHTML=[...data.notes,`计算上下文 ${data.start} 至 ${f.date}；当前输入 ${data.frames.findIndex(x=>x.date===f.date)+1} 根。`,`计算引擎 chan.py · 版本 ${data.revision.slice(0,12)}`].map(n=>`<li>${esc(n)}</li>`).join('');
  }
  function choices(){
    const visible=new Set(state.prices.items.map(x=>x.date));
    available=data.frames.filter(f=>visible.has(f.date));
    if(!available.some(f=>f.date===selected))selected=available.at(-1)?.date||'';
    $('chan-date').min=available[0]?.date||'';$('chan-date').max=available.at(-1)?.date||'';
    $('chan-date').value=selected;
  }
  async function load(){
    update();if(!enabled()||!state.prices||!sourceKey())return;
    const wanted=sourceKey();
    if(key===wanted&&data){choices();update();renderPrices();return;}
    const token=++version;loading=true;data=null;error='';selected='';key=wanted;update();
    try{const result=await api('chan',{code:state.stock.thscode,date:state.prices.end,...($('chan-candidates-enabled').checked?{candidates:'1'}:{})});if(token!==version||wanted!==sourceKey())return;data=result;choices();}
    catch(e){if(token===version)error=e.message;}
    finally{if(token===version){loading=false;update();if(state.prices&&state.view==='price')renderPrices();}}
  }
  window.chanReplayEnd=()=>frame()?.date;
  window.chanRows=prices=>{
    const f=frame();return f?prices.items.filter(x=>x.date<=f.date):prices.items;
  };
  window.chanOverlay=({items,L,R,W,T,PH,step,y})=>{
    const f=frame();if(!f||!items.length)return '';
    const indices=new Map(data.frames.map((x,i)=>[x.date,i]));
    const offset=indices.get(items.find(x=>indices.has(x.date))?.date);
    const local=items.findIndex(x=>indices.has(x.date));
    if(offset===undefined)return '';
    const x=date=>L+(indices.get(date)-offset+local+.5)*step;
    let svg=`<defs><clipPath id="chan-clip"><rect x="${L}" y="${T}" width="${W-L-R}" height="${PH}"/></clipPath></defs><g clip-path="url(#chan-clip)" class="chan-overlay">`;
    for(const k of ['zs','bi','seg']){
      if(!document.querySelector(`[data-chan-layer="${k}"]`).checked)continue;
      for(const s of f[k]){
        if(s.end<items[0].date||s.start>items.at(-1).date)continue;
        const a=x(s.start),b=x(s.end);if(!Number.isFinite(a)||!Number.isFinite(b))continue;
        const dash=s.sure?'':' stroke-dasharray="6 4"';
        if(k==='zs')svg+=`<rect x="${a}" y="${y(s.high)}" width="${Math.max(1,b-a)}" height="${Math.max(1,y(s.low)-y(s.high))}" fill="#dba04b" fill-opacity=".13" stroke="#b98436"${dash}/>`;
        else svg+=`<line x1="${a}" y1="${y(s.a)}" x2="${b}" y2="${y(s.b)}" stroke="${k==='bi'?'#647db4':'#8058a1'}" stroke-width="${k==='bi'?1.4:2.4}"${dash}/>`;
      }
    }
    if($('chan-candidates-enabled').checked&&data.candidate_meta?.status==='ok'){
      for(const c of f.candidates||[]){
        if(c.pivot_date<items[0].date||c.pivot_date>items.at(-1).date)continue;
        const cx=x(c.pivot_date),cy=y(c.pivot_price);
        if(!Number.isFinite(cx)||!Number.isFinite(cy))continue;
        svg+=`<circle class="chan-candidate-marker" cx="${cx}" cy="${cy}" r="4" fill="#fff" stroke="#977a43" stroke-width="1.5"><title>未确认候选 · 首次可见 ${esc(c.first_seen_at)} · 拐点 ${esc(c.pivot_date)}</title></circle>`;
      }
    }

    return svg+'</g>';
  };
  function change(){const date=$('chan-date').value;if(!available.some(f=>f.date===date)){$('chan-date').value=selected;$('chan-status').textContent='该日期没有可回放的日 K，请选择范围内的有效交易日。';return;}selected=date;update();renderPrices();}
  $('chan-date').addEventListener('change',change);
  for(const [id,delta] of [['chan-prev',-1],['chan-next',1]])$(id).addEventListener('click',()=>{const i=available.findIndex(f=>f.date===selected);$('chan-date').value=available[Math.max(0,Math.min(available.length-1,i+delta))]?.date||'';change();});
  $('chan-latest').addEventListener('click',()=>{$('chan-date').value=available.at(-1)?.date||'';change();});
  $('chan-candidates-enabled').addEventListener('change',()=>{if(enabled())load();else update();});
  $('chan-enabled').addEventListener('change',()=>{if(enabled())load();else {++version;loading=false;update();if(state.prices)renderPrices();}});
  $('chan-layers').addEventListener('change',()=>{if(state.prices)renderPrices();});
  document.addEventListener('prices-loaded',load);
  document.addEventListener('prices-cleared',()=>{++version;loading=false;selected='';$('chan-date').value='';available=[];update();});
  $('view-tabs').addEventListener('click',()=>{update();});
  update();
})();
