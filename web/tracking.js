'use strict';
const watchKey='guanshi.observations.v1';
let observations=[],watchLoaded=false,reviewVersion=0;
const reviewCache=new Map();
function observationHTML(text){
  return window.Privacy?Privacy.privateHTML(text,'observation-note',document.body.classList.contains('privacy-on')):`<p class="observation-note private-text">${esc(text)}</p>`;
}
async function saveObservation(body){
  const response=await fetch('/api/observations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'保存失败');return data;
}
function renderWatch(){
  if(!watchLoaded)return;
  document.dispatchEvent(new Event('records-updated'));
  const rows=observations.filter(o=>o.active||$('show-archived').checked);
  $('watch-count').textContent=`关注 ${observations.filter(o=>o.active).length} 条 · 显示 ${rows.length} 条`;
  $('watch-list').innerHTML=rows.length?rows.map(o=>`<article class="watch-card"><div class="watch-card-heading">${stockLink(o)}<button data-archive="${esc(o.id)}" data-archived="${o.active?1:0}">${o.active?'归档':'恢复关注'}</button></div>${observationHTML(o.note)}${o.report_id?`<button class="text-action" data-open-report="${esc(o.report_id)}">查看关联分析报告 →</button>`:''}<p class="footnote">观察日 ${esc(o.date)} · 记录于 ${esc(new Date(o.createdAt).toLocaleString('zh-CN'))}${o.date<new Date(o.createdAt).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})?' · 历史补记':''}</p><div class="followup-grid" id="review-${esc(o.id)}">${reviewCache.get(o.id+'|'+state.date)||'等待更新后续表现'}</div></article>`).join(''):'<p class="placeholder">从个股研究或线索清单加入关注，留下理由，在这里跟踪后续表现。</p>';
}
async function updateReviews(){
  if(!watchLoaded||!state.date||!$('watch-journal').open)return;const token=++reviewVersion,date=state.date;
  const rows=observations.filter(o=>o.active||$('show-archived').checked);
  let index=0;
  async function worker(){while(index<rows.length&&token===reviewVersion){
    const o=rows[index++],target=$('review-'+o.id);if(!target)continue;
    const key=o.id+'|'+date;if(reviewCache.has(key)){target.innerHTML=reviewCache.get(key);continue;}
    target.textContent='正在核对后续交易日…';
    try{const d=await api('followup',{code:o.thscode,observed:o.date,date});if(token!==reviewVersion)return;
      const html=d.items.map(r=>`<div><small>${r.days} 日后 · ${esc(r.date||'待交易日历更新')}</small><b class="${r.change>0?'quote-up':r.change<0?'quote-down':''}">${r.change==null?'—':(r.change>0?'+':'')+r.change.toFixed(2)+'%'}</b><small>${esc(r.status)}</small></div>`).join('');reviewCache.set(key,html);if(target.isConnected)target.innerHTML=html;
    }catch(e){if(token===reviewVersion&&target.isConnected)target.textContent=e.message;}
  }}
  await Promise.all([worker(),worker()]);
}
function draftObservation(stock,note='',date=state.date){
  if(!date)return;watchDraft={...stock,date};$('watch-target').textContent=`${stock.name} · ${stock.thscode} · 观察日 ${date}`;
  showWorkspace('watch');$('watch-form').hidden=false;$('watch-note').value=note;$('watch-note').focus();$('watch-form').scrollIntoView({block:'center',behavior:'smooth'});
}
$('observe-stock').addEventListener('click',()=>{if(state.stock)draftObservation(state.stock);});
document.addEventListener('click',e=>{const b=e.target.closest('[data-observe]');if(b)draftObservation({thscode:b.dataset.observe,name:b.dataset.name},b.dataset.reason||'');});
$('cancel-watch').addEventListener('click',()=>{$('watch-form').hidden=true;watchDraft=null;});
$('watch-form').addEventListener('submit',async e=>{
  e.preventDefault();if(!watchDraft)return;const button=e.submitter;button.disabled=true;
  try{const d=await saveObservation({...watchDraft,note:$('watch-note').value.trim()});observations=d.items;watchLoaded=true;$('watch-form').hidden=true;watchDraft=null;$('watch-message').textContent='已保存到本机，关注理由和记录时间已保留。';renderWatch();updateReviews();}
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
document.addEventListener('privacy-changed',renderWatch);
(async()=>{
  try{let d=await api('observations');observations=d.items;watchLoaded=true;renderWatch();
    try{const old=JSON.parse(localStorage.getItem(watchKey)||'[]');if(Array.isArray(old)&&old.length){d=await saveObservation({action:'import',items:old});observations=d.items;$('watch-message').textContent='已合并旧浏览器记录，浏览器备份仍保留。';renderWatch();}}catch{$('watch-message').textContent='旧浏览器记录未能合并，原数据保留；本机记录可正常使用。';}
    if(location.hash==='#watch')updateReviews();
  }catch(e){$('watch-message').textContent='本机记录读取失败：'+e.message;}
})();
