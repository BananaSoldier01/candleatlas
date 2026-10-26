'use strict';
(() => {
  const labels={queued:'未开始',running:'执行中',done:'已完成',partial:'报告不完整',failed:'失败',cancelled:'已取消',skipped_duplicate:'复用已有报告',needs_review:'待人工核对',interrupted:'已中断'};
  let members=[],selected=new Set(),selectedId='',current=null,activeId=null,busy=false,timer=null,generation=0,detailsKey='';
  const here=()=>!location.hash||location.hash==='#watch';
  const status=i=>i.status==='skipped_duplicate'&&i.report_status==='partial'?'复用 · 报告不完整':labels[i.status]||i.status;
  function explanation(i){
    if(i.status==='skipped_duplicate')return i.report_status==='partial'?'复用的报告仍有资料缺失，请打开报告核对。':i.report_status==='unknown'?'已有报告的完整程度待核对，请打开报告查看。':'已复用保存的技术报告，本次未重新请求。';
    if(i.status==='needs_review')return '上次请求的结果尚未核对；请查看已有报告，确认后保留，不会自动重跑。';
    return (i.error||'').replace(/^start_rejected:\s*/, '');
  }
  async function post(path,body){
    const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json();
    if(!r.ok)throw Error(d.error||'批次操作失败');return d;
  }
  function notice(text=''){$('batch-notice').hidden=!text;$('batch-notice').textContent=text;}
  function controls(){
    $('batch-selection-count').textContent=`选择自选股 · 已选 ${selected.size} / ${members.length}`;
    $('batch-run').textContent=`运行所选${selected.size?'（'+selected.size+'）':''}`;
    $('batch-run').disabled=busy||!!activeId||selected.size===0||selected.size>50;
    $('batch-redo').disabled=busy||!!activeId;
    $('batch-cancel').disabled=busy||!current?.active||!current.items.some(i=>i.status==='queued');
    $('batch-retry').disabled=busy||!!activeId||!current||current.batch.status==='interrupted'||!current.items.some(i=>i.status==='failed');
  }
  function renderSelection(){
    $('batch-selection').innerHTML=members.length?members.map(m=>`<label><input type="checkbox" data-batch-code="${esc(m.thscode)}" ${selected.has(m.thscode)?'checked':''}><span>${esc(m.name)}<small>${esc(m.thscode)}</small></span></label>`).join(''):'<p class="muted">先添加自选股票，再选择需要分析的成员。</p>';
    controls();
  }
  function render(){
    controls();
    if(!current){$('batch-state').textContent='选择股票后手动运行；已有批次会保存在本机。';$('batch-results').textContent='';$('batch-details').hidden=true;$('batch-details').open=false;detailsKey='';return;}
    const b=current.batch,items=current.items;
    const attention=current.active||['running','failed','partial','needs_review','interrupted'].includes(b.status)||items.some(i=>['failed','partial','needs_review','interrupted'].includes(i.status)||i.status==='skipped_duplicate'&&i.report_status!=='complete');
    const key=b.batch_id+'|'+b.status+'|'+Boolean(attention);
    $('batch-details').hidden=false;$('batch-details-summary').textContent=`执行明细（${items.length} 只）`;
    if(detailsKey!==key){$('batch-details').open=Boolean(attention);detailsKey=key;}
    const count=s=>items.filter(i=>i.status===s).length;
    const incomplete=items.filter(i=>i.status==='partial'||i.status==='skipped_duplicate'&&i.report_status==='partial').length;
    $('batch-state').textContent=`${b.day} · ${labels[b.status]||b.status} · ${items.length} 只：完成 ${count('done')}，复用 ${count('skipped_duplicate')}，不完整 ${incomplete}，待核对 ${count('needs_review')}，失败 ${count('failed')}，取消 ${count('cancelled')}${b.note?' · '+b.note:''}${b.error?' · '+b.error:''}`;
    $('batch-results').innerHTML=items.map((i,index)=>`<article class="batch-item"><div><strong>${esc(i.name)}</strong><small>${esc(i.code)}</small></div><span class="batch-status ${esc(i.status)}">${esc(status(i))}</span><div class="batch-item-actions">${i.report_id?`<button type="button" class="text-action" data-open-report="${esc(i.report_id)}">打开报告</button>`:''}${i.status==='needs_review'&&i.report_id?`<button type="button" class="outline-button" data-batch-review="${index}" ${busy||activeId?'disabled':''}>已核对，保留此报告</button>`:''}</div>${explanation(i)?`<p class="footnote">${esc(explanation(i))}</p>`:''}${i.status==='needs_review'&&!i.report_id?'<p class="footnote">请到个股分析历史核对；此处不会自动重跑。</p>':''}</article>`).join('');
  }
  function poll(){
    clearTimeout(timer);
    if(here()&&activeId)timer=setTimeout(()=>load(),1200);
  }
  async function load(){
    if(!state.date||!here())return;
    const token=++generation;
    try{
      const history=await api('batch',{date:state.date});if(token!==generation)return;
      activeId=history.active_batch;
      if(!selectedId||!history.items.some(b=>b.batch_id===selectedId))selectedId=activeId||history.items[0]?.batch_id||'';
      $('batch-history').innerHTML=history.items.map(b=>`<option value="${esc(b.batch_id)}">${esc(new Date(b.created_at).toLocaleString('zh-CN'))} · ${esc(labels[b.status]||b.status)} · ${b.member_count} 只</option>`).join('')||'<option value="">暂无批次</option>';
      if(selectedId&&!history.items.some(b=>b.batch_id===selectedId)){$('batch-history').insertAdjacentHTML('afterbegin',`<option value="${esc(selectedId)}">执行中的批次（其他观察日）</option>`);}
      $('batch-history').value=selectedId;
      const snapshot=selectedId?await api('batch',{id:selectedId}):null;if(token!==generation)return;
      const finished=current?.active&&!snapshot?.active;
      current=snapshot;render();poll();
      if(finished)document.dispatchEvent(new CustomEvent('records-updated'));
    }catch(e){if(token===generation){notice(e.message);poll();}}
  }
  async function action(path,body){
    busy=true;notice();controls();
    try{current=await post(path,body);selectedId=current.batch.batch_id;await load();}
    catch(e){notice(e.message);}
    finally{busy=false;render();}
  }
  $('batch-selection').addEventListener('change',e=>{const code=e.target.dataset.batchCode;if(!code)return;if(e.target.checked)selected.add(code);else selected.delete(code);controls();});
  $('batch-all').addEventListener('click',()=>{selected=new Set(members.slice(0,50).map(m=>m.thscode));renderSelection();});
  $('batch-none').addEventListener('click',()=>{selected.clear();renderSelection();});
  $('batch-run').addEventListener('click',()=>action('batch',{date:state.date,mode:'technical',ai:false,reanalyze:$('batch-redo').checked,members:members.filter(m=>selected.has(m.thscode)).map(m=>({code:m.thscode,name:m.name}))}));
  $('batch-cancel').addEventListener('click',()=>current&&action('batch/cancel',{id:current.batch.batch_id}));
  $('batch-retry').addEventListener('click',()=>current&&action('batch/retry',{id:current.batch.batch_id}));
  $('batch-results').addEventListener('click',e=>{const b=e.target.closest('[data-batch-review]');if(b&&current)action('batch/review',{id:current.batch.batch_id,index:Number(b.dataset.batchReview)});});
  $('batch-history').addEventListener('change',()=>{selectedId=$('batch-history').value;load();});
  $('batch-refresh').addEventListener('click',()=>{notice();load();});
  document.addEventListener('watchlist-loaded',e=>{members=e.detail.items;selected=new Set([...selected].filter(c=>members.some(m=>m.thscode===c)));renderSelection();load();});
  document.addEventListener('day-selected',()=>{++generation;clearTimeout(timer);selectedId='';current=null;load();});
  document.addEventListener('workspace-selected',()=>{if(here())load();else{++generation;clearTimeout(timer);}});
  renderSelection();load();
})();
