'use strict';
const watchKey='guanshi.observations.v1';
let observations=[],watchLoaded=false,reviewVersion=0;
const reviewCache=new Map();
const WATCH_METRICS=[['close','收盘价'],['ma5','MA5'],['ma10','MA10'],['ma20','MA20'],['ma60','MA60'],['rsi14','RSI14'],['volume_ratio5','较前5日均量'],['change1','当日涨跌'],['change20','近20日涨跌'],['bias20','偏离MA20'],['macd_hist','MACD柱']];
const WATCH_METRIC_LABEL=Object.fromEntries(WATCH_METRICS);
function formatPointNumber(n){
  const value=Number(n);
  if(!Number.isFinite(value))return '—';
  const text=String(Math.round(value*10000)/10000);
  return text==='-0'?'0':text;
}
function formatWatchPoint(p){
  if(!p||typeof p!=='object')return '观察点';
  const source=p.source||'观市日K程序计算（前复权）';
  const next=p.next_public_date||'—';
  const tail=`来源：${source} · 下一公开时点：${next}`;
  if(p.kind==='text')return `${p.subject||'文字观察'} · ${tail}`;
  const name=WATCH_METRIC_LABEL[p.metric]||p.metric||'指标';
  const op=p.op==='>='?'≥':p.op==='<='?'≤':'?';
  const right=p.ref_metric?(WATCH_METRIC_LABEL[p.ref_metric]||p.ref_metric):formatPointNumber(p.value);
  const days=Number.isInteger(p.days)?p.days:1;
  return `${name} ${op} ${right}（连续 ${days} 日）· ${tail}`;
}
function reviewPhrase(item){
  if(!item||typeof item!=='object')return '数据缺失';
  if(item.phrase)return item.phrase;
  if(item.status==='appeared')return `已出现（首次 ${item.first_seen_date||'—'}，当日取值 ${formatPointNumber(item.value_at_first_seen)}）`;
  if(item.status==='not_appeared')return `未出现（已核对 ${item.checked_days||0} 个交易日）`;
  if(item.status==='intraday')return '盘中未定稿';
  if(item.status==='pending')return '尚未到期';
  if(item.status==='manual')return '需自行核对';
  return '数据缺失';
}
function pointText(p){return p&&p.label?p.label:formatWatchPoint(p);}
async function saveObservation(body){
  const response=await fetch('/api/observations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'保存失败');return data;
}
function pointListHTML(points){
  if(!Array.isArray(points)||!points.length)return '';
  return `<ul class="watch-point-list">${points.map(p=>`<li>${esc(pointText(p))}</li>`).join('')}</ul>`;
}
function followupHTML(d,observation){
  const points=Array.isArray(observation.watch_points)?observation.watch_points:[];
  const reviewed=d.watch_review&&Array.isArray(d.watch_review.items)?d.watch_review.items:[];
  const grid=(d.items||[]).map(r=>`<div><small>${r.days} 日后 · ${esc(r.date||'待交易日历更新')}</small><b class="${r.change>0?'quote-up':r.change<0?'quote-down':''}">${r.change==null?'—':(r.change>0?'+':'')+r.change.toFixed(2)+'%'}</b><small>${esc(r.status)}</small></div>`).join('');
  const adjust='基于当前查询的前复权序列，历史日不等于当时快照。';
  if(!points.length)return `<p class="footnote">可补充观察点。${adjust} 历史补记不视为事前判断。</p><div class="followup-grid">${grid}</div>`;
  const lines=reviewed.length?reviewed.map(item=>`<li>${esc(item.label||formatWatchPoint(item))} → ${esc(reviewPhrase(item))}</li>`).join(''):points.map(p=>`<li>${esc(pointText(p))} → 尚未到期</li>`).join('');
  const note=d.watch_review&&d.watch_review.note?d.watch_review.note:`${adjust} 历史补记不视为事前判断。`;
  return `<div class="watch-review"><p>当时的核对条件后来是否出现</p><ul class="watch-point-list">${lines}</ul><p class="footnote">${esc(note)} 数据缺失不能当作未出现。</p></div><details class="followup-secondary"><summary>价格变化（次要）</summary><p class="footnote">价格变化仅供参考，不是对“关注是否正确”的判断，也不是策略收益。</p><div class="followup-grid">${grid}</div></details>`;
}
function renderWatch(){
  if(!watchLoaded)return;
  document.dispatchEvent(new Event('records-updated'));
  const rows=observations.filter(o=>o.active||$('show-archived').checked);
  $('watch-count').textContent=`关注 ${observations.filter(o=>o.active).length} 条 · 显示 ${rows.length} 条`;
  $('watch-list').innerHTML=rows.length?rows.map(o=>`<article class="watch-card"><div class="watch-card-heading">${stockLink(o)}<button data-archive="${esc(o.id)}" data-archived="${o.active?1:0}">${o.active?'归档':'恢复关注'}</button></div><p class="observation-note">${esc(o.note)}</p>${pointListHTML(o.watch_points)}${o.report_id?`<button class="text-action" data-open-report="${esc(o.report_id)}">查看关联分析报告 →</button>`:''}<p class="footnote">观察日 ${esc(o.date)} · 记录于 ${esc(new Date(o.createdAt).toLocaleString('zh-CN'))}${o.date<new Date(o.createdAt).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})?' · 历史补记':''}</p><div class="followup-slot" id="review-${esc(o.id)}">${reviewCache.get(o.id+'|'+state.date)||'等待更新后续表现'}</div></article>`).join(''):'<p class="placeholder">从个股研究或线索清单加入关注，留下理由，在这里跟踪后续表现。</p>';
}
async function updateReviews(){
  if(!watchLoaded||!state.date||!$('watch-journal').open)return;const token=++reviewVersion,date=state.date;
  const rows=observations.filter(o=>o.active||$('show-archived').checked);
  let index=0;
  async function worker(){while(index<rows.length&&token===reviewVersion){
    const o=rows[index++],target=$('review-'+o.id);if(!target)continue;
    const key=o.id+'|'+date;if(reviewCache.has(key)){target.innerHTML=reviewCache.get(key);continue;}
    target.textContent='正在核对后续交易日…';
    try{const d=await api('followup',{code:o.thscode,observed:o.date,date,id:o.id});if(token!==reviewVersion)return;
      const html=followupHTML(d,o);reviewCache.set(key,html);if(target.isConnected)target.innerHTML=html;
    }catch(e){if(token===reviewVersion&&target.isConnected)target.textContent=e.message;}
  }}
  await Promise.all([worker(),worker()]);
}
function resetWatchPoints(){
  $('watch-point-rows').textContent='';
  $('add-watch-point').disabled=false;
}
function syncPointRow(row){
  const text=row.querySelector('[data-k="kind"]').value==='text';
  for(const el of row.querySelectorAll('[data-metric-only]'))el.hidden=text;
  const ref=row.querySelector('[data-k="ref"]');
  row.querySelector('[data-k="value"]').disabled=text||!!(ref&&ref.value);
}
function addWatchPoint(){
  const box=$('watch-point-rows');
  if(box.querySelectorAll('.watch-point-row').length>=8)return;
  const metrics=WATCH_METRICS.map(([k,label])=>`<option value="${k}">${label}</option>`).join('');
  const row=document.createElement('div');
  row.className='watch-point-row';
  row.innerHTML=`<label>对象<input data-k="subject" maxlength="80" placeholder="如 RSI14、收盘价 vs MA20"></label><label>类型<select data-k="kind"><option value="metric">指标</option><option value="text">文字</option></select></label><label data-metric-only>指标<select data-k="metric">${metrics}</select></label><label data-metric-only>方向<select data-k="op"><option value=">=">≥</option><option value="<=">≤</option></select></label><label data-metric-only>阈值<input data-k="value" inputmode="decimal" placeholder="数值"></label><label data-metric-only>对照<select data-k="ref"><option value="">不对照其他指标</option>${metrics}</select></label><label data-metric-only>连续交易日<input data-k="days" type="number" min="1" max="60" value="1"></label><label>来源<input data-k="source" maxlength="80" placeholder="默认：观市日K程序计算（前复权）"></label><label>下一公开时点<input data-k="next" type="date"></label><label>说明<input data-k="note" maxlength="200" placeholder="可选，最多 200 字"></label><button type="button" data-remove-point>移除</button>`;
  box.append(row);
  syncPointRow(row);
  $('add-watch-point').disabled=box.querySelectorAll('.watch-point-row').length>=8;
}
function collectWatchPoints(){
  const out=[];
  for(const row of $('watch-point-rows').querySelectorAll('.watch-point-row')){
    const val=k=>row.querySelector(`[data-k="${k}"]`).value.trim();
    const kind=val('kind');
    const point={kind,subject:val('subject'),source:val('source'),next_public_date:val('next'),note:val('note')};
    if(kind==='metric'){
      point.metric=val('metric');point.op=val('op');
      const days=val('days');if(days!=='')point.days=Number(days);
      const ref=val('ref'),raw=val('value');
      if(ref)point.ref_metric=ref;
      else if(raw!==''){const n=Number(raw);point.value=Number.isFinite(n)?n:raw;}
    }
    const empty=!point.subject&&!point.note&&!point.source&&!point.next_public_date&&!point.ref_metric&&point.value==null;
    if(empty)continue;
    out.push(point);
  }
  return out;
}
function draftObservation(stock,note='',date=state.date){
  if(!date)return;watchDraft={thscode:stock.thscode,name:stock.name,date,report_id:typeof stock.report_id==='string'?stock.report_id:''};
  $('watch-target').textContent=`${stock.name} · ${stock.thscode} · 观察日 ${date}`;
  showWorkspace('watch');$('watch-form').hidden=false;$('watch-note').value=note;resetWatchPoints();$('watch-note').focus();$('watch-form').scrollIntoView({block:'center',behavior:'smooth'});
}
$('observe-stock').addEventListener('click',()=>{if(state.stock)draftObservation(state.stock);});
document.addEventListener('click',e=>{const b=e.target.closest('[data-observe]');if(b)draftObservation({thscode:b.dataset.observe,name:b.dataset.name},b.dataset.reason||'');});
$('cancel-watch').addEventListener('click',()=>{$('watch-form').hidden=true;watchDraft=null;resetWatchPoints();});
$('add-watch-point').addEventListener('click',addWatchPoint);
$('watch-point-rows').addEventListener('click',e=>{
  const b=e.target.closest('[data-remove-point]');if(!b)return;
  b.closest('.watch-point-row').remove();$('add-watch-point').disabled=false;
});
$('watch-point-rows').addEventListener('change',e=>{const row=e.target.closest('.watch-point-row');if(row&&(e.target.dataset.k==='kind'||e.target.dataset.k==='ref'))syncPointRow(row);});
$('watch-form').addEventListener('submit',async e=>{
  e.preventDefault();if(!watchDraft)return;const button=e.submitter;button.disabled=true;
  const body={thscode:watchDraft.thscode,name:watchDraft.name,date:watchDraft.date,note:$('watch-note').value.trim(),watch_points:collectWatchPoints()};
  if(watchDraft.report_id)body.report_id=watchDraft.report_id;
  try{const d=await saveObservation(body);observations=d.items;watchLoaded=true;$('watch-form').hidden=true;watchDraft=null;resetWatchPoints();$('watch-message').textContent='已保存到本机，关注理由和记录时间已保留。';renderWatch();updateReviews();}
  catch(err){$('watch-message').textContent=err.message;}finally{button.disabled=false;}
});
$('watch-list').addEventListener('click',async e=>{
  const b=e.target.closest('[data-archive]');if(!b)return;b.disabled=true;
  try{const d=await saveObservation({action:'archive',id:b.dataset.archive,archived:b.dataset.archived==='1'});observations=d.items;renderWatch();updateReviews();}
  catch(err){$('watch-message').textContent=err.message;b.disabled=false;}
});
$('show-archived').addEventListener('change',()=>{renderWatch();updateReviews();});
$('watch-journal').addEventListener('toggle',()=>{if($('watch-journal').open)updateReviews();else ++reviewVersion;});
$('refresh-watch').addEventListener('click',()=>{reviewCache.clear();$('watch-journal').open=true;updateReviews();});
$('export-watch').addEventListener('click',async()=>{
  try{const d=await api('observations');const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,items:d.items},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='观市研究记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){$('watch-message').textContent=e.message;}
});
$('import-watch').addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  try{if(file.size>4000000)throw Error('文件过大，一次最多导入 1000 条记录。');const raw=JSON.parse(await file.text());const d=await saveObservation({action:'import',items:Array.isArray(raw)?raw:raw.items});observations=d.items;watchLoaded=true;renderWatch();updateReviews();$('watch-message').textContent='导入完成，重复编号已跳过，原记录保留。';}catch(err){$('watch-message').textContent=err.message;}finally{e.target.value='';}
});
document.addEventListener('workspace-selected',e=>{if(e.detail==='watch')updateReviews();else ++reviewVersion;});
document.addEventListener('day-selected',()=>{renderWatch();if(location.hash==='#watch')updateReviews();});
(async()=>{
  try{let d=await api('observations');observations=d.items;watchLoaded=true;renderWatch();
    try{const old=JSON.parse(localStorage.getItem(watchKey)||'[]');if(Array.isArray(old)&&old.length){d=await saveObservation({action:'import',items:old});observations=d.items;$('watch-message').textContent='已合并旧浏览器记录，浏览器备份仍保留。';renderWatch();}}catch{$('watch-message').textContent='旧浏览器记录未能合并，原数据保留；本机记录可正常使用。';}
    if(location.hash==='#watch')updateReviews();
  }catch(e){$('watch-message').textContent='本机记录读取失败：'+e.message;}
})();
