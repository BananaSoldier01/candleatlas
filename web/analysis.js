'use strict';
(() => {
  let configured=false,version=0,timer=null,current=null,busy=false,pinnedId='',stockCode='',openVersion=0;
  const names={close:'观察日收盘',ma5:'MA5',ma10:'MA10',ma20:'MA20',ma60:'MA60',change1:'当日涨跌（%）',change20:'近 20 日涨跌（%）',bias20:'偏离 MA20（%）',volume_ratio5:'较前 5 日均量（倍）',rsi14:'RSI14',macd_dif:'MACD DIF',macd_dea:'MACD DEA',macd_hist:'MACD 柱值'};
  const value=n=>Number.isFinite(n)?n.toFixed(2):'—';
  const trendRules=label=>{if(!window.LabelRules)return '';return (label?LabelRules.ruleNote(LabelRules.trendKey(label)):'')+LabelRules.ruleNote('indicator.windows');};
  async function post(path,body){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'操作失败');return d;}
  function controls(){ $('analyze-ai').disabled=busy||!configured||!state.stock;$('analyze-technical').disabled=busy||!state.stock; }
  async function settings(){
    try{const d=await api('model-settings');configured=d.configured;$('model-url').value=d.base_url;$('model-name').value=d.model;$('model-config-state').textContent=d.configured?'已配置'+(d.has_key?' · 密钥已保存':' · 无密钥'):'未配置';$('analysis-model-status').innerHTML=d.configured?`模型：${esc(d.model)} · 仅手动生成时调用`:'尚未配置模型，可先计算技术分析。<button class="text-action" data-route="settings">前往设置 →</button>';controls();}
    catch(e){$('model-message').textContent=e.message;$('analysis-model-status').textContent=e.message;}
  }
  $('model-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('save-model');b.disabled=true;
    try{await post('model-settings',{base_url:$('model-url').value,model:$('model-name').value,key:$('model-key').value,clear_key:$('model-clear').checked});$('model-key').value='';$('model-clear').checked=false;$('model-message').textContent='已保存；已有报告不会自动重新生成。';await settings();}
    catch(err){$('model-message').textContent=err.message;}finally{b.disabled=false;}
  });
  $('test-model').addEventListener('click',async()=>{const b=$('test-model');b.disabled=true;$('model-message').textContent='正在发送测试请求…';try{$('model-message').textContent=(await post('model-settings/test',{})).message;}catch(e){$('model-message').textContent=e.message;}finally{b.disabled=false;}});
  const year=new Date().getFullYear();for(let y=year;y>=year-3;y--)for(let q=4;q>=1;q--){const o=document.createElement('option');o.value=`${y}-${q}`;o.textContent=`${y} ${['','一季报','中报','三季报','年报'][q]}`;$('analysis-quarter').append(o);}
  let disclosureVersion=0;
  const disclosureKinds={annual_report:'年报原版',revised_report:'完整修订版',correction_notice:'更正公告'};
  function disclosureHTML(d){
    if(!d)return '';
    const officialURL=url=>typeof url==='string'&&/^https:\/\/static\.cninfo\.com\.cn\/finalpage\/\d{4}-\d{2}-\d{2}\/\d+\.PDF$/i.test(url)?url:null;
    const itemHTML=item=>`<article class="disclosure-item" data-disclosure-id="${esc(item.id)}"><strong>${esc(disclosureKinds[item.document_kind]||'官方材料')} · ${esc(item.period_end)}</strong><p>${esc(item.title)}</p><p>披露日期 ${esc(item.notice_date)} · 保守可用 ${esc(item.available_at.replace('T',' '))}</p><p class="footnote">核验抓取 ${esc(item.fetched_at.replace('T',' '))}</p>${officialURL(item.url)?`<a href="${esc(officialURL(item.url))}" target="_blank" rel="noopener noreferrer">查看官方原文 ↗</a>`:"原文链接无效"}</article>`;
    const previous=(d.versions||[]).filter(x=>!(d.items||[]).some(item=>item.id===x.id));
    return `<div class="disclosure-snapshot" data-disclosure-status="${esc(d.status)}" data-disclosure-code="${esc(d.code)}" data-disclosure-date="${esc(d.date)}" data-disclosure-period="${esc(d.period_end)}"><p class="disclosure-status">观察日 ${esc(d.date)} · 报告期 ${esc(d.period_end)} · ${esc(d.note)}</p>${(d.items||[]).map(itemHTML).join('')}${previous.length?`<details><summary>此前已可用版本（${previous.length}）</summary>${previous.map(itemHTML).join('')}</details>`:''}<p class="footnote">${esc(d.rule)}</p><p class="footnote">${esc(d.scope)}</p></div>`;
  }
  async function loadDisclosures(){
    const token=++disclosureVersion,box=$('disclosure-materials');
    if(state.view!=='analysis'||!state.stock||!$('analysis-quarter').value){box.innerHTML='<p class="footnote">选择财务报告期后，查看本机已核验的官方材料。</p>';return;}
    box.textContent='正在核对本机披露资料…';
    try{const d=await api('disclosures',{code:state.stock.thscode,date:state.date,report:$('analysis-quarter').value});if(token===disclosureVersion)box.innerHTML=disclosureHTML(d);}
    catch(e){if(token===disclosureVersion)box.textContent='披露资料读取未完成：'+e.message;}
  }
  $('analysis-quarter').addEventListener('change',loadDisclosures);
  function evidenceHTML(r){
    const v=r.value;let text='';
    if(r.id==='T1')text=Object.entries(names).map(([k,label])=>`${label}：${value(v[k])}`).join('；')+'。'+v.method;
    else if(Array.isArray(v))text=v.join('\n');
    else if(r.id.startsWith('D'))text=`报告期 ${v.period_end}；披露日期 ${v.notice_date}；保守可用时间 ${v.available_at}；核验抓取 ${v.fetched_at}。`;
    else if(r.id==='F1')text=`报告期 ${v.report}；`+v.items.map(x=>`${x.label}：${value(x.value)}%`).join('；')+'。'+v.note;
    else text=[v.time,v.source,v.title].filter(Boolean).join(' · ');
    const url=typeof v?.url==='string'&&/^https?:\/\//.test(v.url)?v.url:null;
    return `<details id="analysis-evidence-${esc(r.id)}"><summary>${esc(r.id)} · ${esc(r.title)}</summary><p>${esc(text)}</p><small>${esc(r.source)}</small>${url?` <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a>`:''}</details>`;
  }

  function assessmentHTML(a,notes){
    if(!a)return '<p class="footnote">此报告未保存技术画像；已有技术指标仍可查看。</p>';
    const labels={trend:'趋势',momentum:'动量',volume_coord:'量能配合',overheat:'过热/回撤风险'};
    const rows=Object.entries(labels).map(([key,label])=>{
      const c=a.components?.[key]||{},score=Number.isFinite(c.score)?c.score.toFixed(1):'—';
      const coverage=Number.isFinite(c.coverage)?Math.round(c.coverage*100)+'%':'未知';
      return `<div><small>${label}${key==='overheat'?' · 越高风险越高':''}</small><b>${score}<small> / 100</small></b><small>规则覆盖 ${coverage}${c.status==='partial'?' · 部分数据':''}</small></div>`;
    }).join('');
    const explanations=Object.values(a.components||{}).map(c=>`<li>${esc(c.explanation||'资料不足')}</li>`).join('');
    const lines=Array.isArray(notes)?notes.filter(x=>x&&x.text):[];
    const invalid=lines.length?`<h4>读法失效条件</h4><ul class="reading-notes">${lines.map(x=>`<li>${esc(x.text)}</li>`).join('')}</ul>`:'';
    return `<section class="technical-assessment"><h3>技术画像 <small>固定规则 · 分项查看</small></h3><div class="assessment-grid">${rows}</div><details><summary>分项解释与规则</summary><p class="footnote">规则 ${esc(a.rule_version||'')} · 行情截至 ${esc(a.asof||'未取得')} · ${esc(a.method_note||'')}</p><ul>${explanations}</ul></details>${invalid}<p class="footnote">技术画像不是上涨概率；风险分项低也不代表安全。</p></section>`;
  }
  function deltaToneClass(r){
    if(typeof DeltaDisplay!=='undefined'&&typeof DeltaDisplay.deltaToneClass==='function')return DeltaDisplay.deltaToneClass(r);
    const hide=!!(r&&(r.hide_direction||r.display==='hidden_direction'||r.direction==='not_comparable'||r.direction==='window_sensitive'));
    if(hide)return 'delta-na';
    if(r&&r.metric_class==='price'&&r.direction==='up')return 'quote-up';
    if(r&&r.metric_class==='price'&&r.direction==='down')return 'quote-down';
    return '';
  }
  function processHTML(p){
    if(!p||!Array.isArray(p.columns)||!p.columns.length)return '';
    const rowDefs=Array.isArray(p.rows)&&p.rows.length?p.rows:[
      {key:'method',label:'方法'},{key:'window',label:'窗口'},{key:'sample',label:'样本'},
      {key:'ai',label:'是否含 AI'},{key:'backfilled',label:'是否事后补做'},{key:'prompt_version',label:'prompt_version'}];
    const head=p.columns.map(c=>{
      const tags=(c.marks||[]).map(m=>`<span class="delta-kind">${esc(m)}</span>`).join('');
      const here=c.current?'<span class="delta-kind">本次</span>':'';
      return `<th scope="col" data-process-id="${esc(c.id)}">${esc(c.day||'未记录')}${here}${tags}</th>`;
    }).join('');
    const body=rowDefs.map(def=>`<tr><th scope="row">${esc(def.label||def.key)}</th>${p.columns.map(c=>{
      const cells=c.cells||{};
      const text=Object.prototype.hasOwnProperty.call(cells,def.key)?cells[def.key]:'未记录';
      return `<td>${esc(text==null||text===''?'未记录':text)}</td>`;
    }).join('')}</tr>`).join('');
    return `<details class="delta-process"><summary>过程对比 · 并排看每份报告怎么得出来的</summary><p class="footnote">只比较方法与取数范围，不比较结果好坏。</p><div class="delta-scroll"><table class="delta-table process-table"><thead><tr><th>项目</th>${head}</tr></thead><tbody>${body}</tbody></table></div></details>`;
  }
  function deltaHTML(d){
    const v=d&&d.delta; if(!v) return '';
    const status=v.status_text||v.status||'';
    const rows=v.rows||[];
    const body=rows.map(r=>{
      const hide=r.hide_direction||r.display==='hidden_direction'||r.direction==='not_comparable'||r.direction==='window_sensitive';
      const diffTxt=r.diff==null?'—':hide?(r.direction==='window_sensitive'?'窗口不同':'不可比'):(r.diff>0?'+':'')+value(r.diff);
      const cls=deltaToneClass(r);
      const kind=r.kind_label?`<span class="delta-kind" data-kind="${esc(r.kind||'')}">${esc(r.kind_label)}</span>`:'';
      return `<tr data-delta-metric="${esc(r.metric)}" data-metric-class="${esc(r.metric_class||'')}"><th scope="row">${kind}${esc(r.label||r.metric)}${r.note?`<small>${esc(r.note)}</small>`:''}</th><td>${value(r.old)}</td><td>${value(r.new)}</td><td${cls?` class="${cls}"`:''} data-delta-tone="${esc(cls)}">${esc(diffTxt)}</td></tr>`;
    }).join('');
    const metrics=body?`<details class="delta-metrics" open><summary>数值变化（${rows.length}）</summary><div class="delta-scroll"><table class="delta-table"><thead><tr><th>指标</th><th>此前</th><th>本次</th><th>变化</th></tr></thead><tbody>${body}</tbody></table></div></details>`:'<p class="empty-hint">暂无基线，保存后续报告后可查看变化。</p>';
    const noticeBlock=v.notices&&typeof v.notices==='object'?v.notices:null;
    const notices=noticeBlock&&Array.isArray(noticeBlock.items)?noticeBlock.items:[];
    const noticeSummary=noticeBlock&&typeof noticeBlock.summary==='string'?noticeBlock.summary:'';
    const noticeShow=Boolean(noticeBlock&&(notices.length||noticeSummary));
    const noticeOpen=noticeShow&&!notices.length?' open':'';
    const noticeTitle=notices.length?`披露 / 公告材料变化（${notices.length}）`:'披露 / 公告材料变化';
    const noticeList=notices.length?`<ul class="delta-notice-list">${notices.map(n=>`<li data-notice-id="${esc(n.id)}" data-notice-kind="${esc(n.kind||'')}"><span class="delta-kind">${esc(n.kind_label||'')}</span>${esc(n.title||n.id||'')} <small>${esc(n.notice_date||'')}</small></li>`).join('')}</ul>`:'';
    const noticeHTML=noticeShow?`<details class="delta-notices"${noticeOpen}><summary>${noticeTitle}</summary><p class="footnote">${esc(noticeSummary||'只比较材料清单的变化，不判断利好或利空。')}</p>${noticeBlock.note?`<p class="footnote">${esc(noticeBlock.note)}</p>`:''}${noticeList}</details>`:'';
    return `<section class="report-delta"><h3>较上次变化 <small>${esc(status)}</small></h3><p class="footnote">${esc((v.reasons||[]).join('；')||'')}</p>${metrics}${noticeHTML}${processHTML(v.process)}</section>`;
  }
  function render(d){
    current=d;busy=d.status==='running';controls();$('analysis-status').textContent=d.phase+(d.error?' · '+d.error:'');
    const p=d.report;if(!p){$('analysis-result').innerHTML='<p class="empty-hint">正在准备分析材料，可离开页面，任务会继续在本机执行。</p>';return;}
    const t=p.technical,view=globalThis.FirstScreenView;
    const screen=view?view.firstScreenHTML(d.first_screen,d.gap_impacts):'';
    const limits=Array.isArray(p.limitations)?p.limitations:[];
    const limitHTML=view?view.limitationItems(limits,d.gap_impacts):limits.map(x=>`<li>${esc(x)}</li>`).join('');
    const evidence=Array.isArray(p.evidence)?p.evidence:[];
    const aiNote='<p class="footnote ai-evidence-note">证据类型只说明材料来自哪里，不代表该推断已被验证，也不是概率。</p>';
    const gateHit=!!(p.ai&&['overview','supporting','opposing','watch'].some(key=>Array.isArray(p.ai[key])&&p.ai[key].some(row=>String(row&&row.text||'').includes('（略※）'))));
    const gateNote=gateHit?'<p class="footnote ai-number-gate">（略※）表示数字未在所引新闻/披露中核到出处</p>':'';
    const sections=p.ai?`<div class="analysis-sections">${Object.entries({overview:'当前状态',supporting:'支持关注的依据',opposing:'相反证据与风险',watch:'后续核对事项'}).map(([k,title])=>`<section><h4>${title}</h4>${p.ai[k].map(row=>{const tagHTML=view?view.kindTagHTML(row.evidence,d.evidence_kinds):'';return `<p>${esc(row.text)}</p><div class="evidence-buttons">${row.evidence.map(id=>`<button data-evidence="${esc(id)}">依据 ${esc(id)}</button>`).join('')}${tagHTML}</div>`;}).join('')}</section>`).join('')}</div>`:`<p class="analysis-no-ai">${busy?'正在准备或生成解读…':d.error?esc(d.error):'尚未生成 AI 解读。技术指标与材料已保存，可配置模型后手动生成。'}</p>`;
    $('analysis-result').innerHTML=`<div class="analysis-report-head"><div><h3>${esc(p.name)} · ${esc(p.date)} 分析</h3><p class="footnote">生成于 ${esc(new Date(d.created).toLocaleString('zh-CN'))} · ${p.model?'模型 '+esc(p.model):'仅程序计算'}${p.date!==state.date?' · 与当前观察日不同，以下为所选历史报告':''}</p></div><button id="analysis-observe" ${busy?'disabled':''}>关联到关注记录</button></div>${screen}<h3>行情状态 <small>程序计算</small></h3>${t?`<p class="trend-label">${esc(t.trend)} · 连续有效样本 ${t.sample} 个交易日</p>${trendRules(t.trend)}<div class="analysis-facts">${Object.entries(names).map(([k,label])=>`<div><small>${label}</small><b>${value(t[k])}</b></div>`).join('')}</div>`:'<p class="empty-hint">行情未取得，本次无技术指标。</p>'}${assessmentHTML(p.assessment,d.reading_notes)}${deltaHTML(d)}${p.disclosures?`<section class="disclosure-panel"><h3>本次报告保存的披露资料</h3>${disclosureHTML(p.disclosures)}</section>`:""}<h3>综合解读 <small>AI 生成，需结合依据核对</small></h3>${aiNote}${gateNote}${sections}<details class="analysis-limitations" open><summary>材料范围与缺失项</summary><ul>${limitHTML}</ul></details><div class="analysis-evidence"><h3>本次分析依据</h3>${evidence.map(evidenceHTML).join('')}</div><p class="footnote">引用编号已检查；引用存在不代表解释或推断必然正确。指标和报告用于研究核对，不是收益保证。</p>`;
  }
  let reportWatch={id:'',status:''};
  async function report(id,token=version){
    clearTimeout(timer);pinnedId=id;
    try{
      const d=await api('analysis',{id});if(token!==version)return;
      const previous=reportWatch.id===id?reportWatch.status:'';
      reportWatch={id,status:typeof d.status==='string'?d.status:''};
      render(d);
      if(d.status==='running')timer=setTimeout(()=>report(id,token),2500);
      else if(previous==='running')document.dispatchEvent(new CustomEvent('records-updated'));
    }
    catch(e){if(token===version){busy=false;controls();$('analysis-status').textContent=e.message;}}
  }
  async function history(){
    loadDisclosures();
    const token=++version;clearTimeout(timer);current=null;busy=false;controls();
    $('analysis-history').innerHTML='<option value="">正在读取…</option>';$('analysis-result').innerHTML='<p class="empty-hint">选择股票后生成或查看本机报告。</p>';$('analysis-status').textContent='';
    if(!state.stock){$('analysis-history').innerHTML='<option value="">请先选择股票</option>';return;}
    try{const d=await api('analysis-history',{code:state.stock.thscode});if(token!==version)return;
      $('analysis-history').innerHTML='<option value="">选择历史报告</option>'+d.items.map(r=>`<option value="${esc(r.id)}">${esc(r.day)} · ${esc(new Date(r.created).toLocaleString('zh-CN'))} · ${esc(r.phase)}</option>`).join('');
      const chosen=pinnedId||d.items.find(r=>r.day===state.date)?.id;if(chosen){if(!d.items.some(r=>r.id===chosen)){const o=document.createElement('option');o.value=chosen;o.textContent='关联的历史报告';$('analysis-history').prepend(o);}$('analysis-history').value=chosen;await report(chosen,token);}
    }catch(e){if(token===version)$('analysis-status').textContent=e.message;}
  }
  async function generate(ai){
    if(!state.stock||busy)return;const token=++version;clearTimeout(timer);busy=true;controls();$('analysis-status').textContent='正在提交分析任务…';
    try{const d=await post('analysis',{code:state.stock.thscode,name:state.stock.name,date:state.date,report:$('analysis-quarter').value,ai});if(token!==version)return;
      const o=document.createElement('option');o.value=d.id;o.textContent=`${state.date} · 本次分析`; $('analysis-history').prepend(o);$('analysis-history').value=d.id;await report(d.id,token);
    }catch(e){if(token===version){busy=false;controls();$('analysis-status').textContent=e.message;}}
  }
  $('analyze-technical').addEventListener('click',()=>generate(false));$('analyze-ai').addEventListener('click',()=>generate(true));
  $('analysis-reload').addEventListener('click',history);$('analysis-history').addEventListener('change',()=>{if($('analysis-history').value)report($('analysis-history').value,++version);});
  $('analysis-result').addEventListener('click',e=>{
    const b=e.target.closest('[data-evidence]');if(b){const el=$('analysis-evidence-'+b.dataset.evidence);if(el){el.open=true;el.scrollIntoView({block:'nearest',behavior:'smooth'});}}
    if(e.target.closest('#analysis-observe')&&current?.report){const p=current.report;const note=p.ai?.watch?.map(r=>r.text).join('\n')||`技术分析：${p.technical?.trend||'资料待补充'}；继续核对量价及相关事件。`;draftObservation({thscode:p.code,name:p.name,report_id:current.id},note.slice(0,2000),p.date);}
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-open-report]');if(!b)return;const token=++openVersion;
    try{const d=await api('analysis',{id:b.dataset.openReport});if(token!==openVersion)return;selectStock({thscode:d.code,name:d.report?.name||d.code});showWorkspace('stocks');document.querySelector('[data-view="analysis"]').click();clearTimeout(timer);pinnedId=d.id;await history();}
    catch(err){$('watch-message').textContent=err.message;}
  });
  $('view-tabs').addEventListener('click',e=>{if(!e.target.closest('[data-view]'))return;if(state.view==='analysis'){settings();history();}else{++version;++disclosureVersion;clearTimeout(timer);}});
  document.addEventListener('stock-selected',()=>{const code=state.stock?.thscode||'';if(code!==stockCode)pinnedId='';stockCode=code;if(state.view==='analysis')history();else{++version;++disclosureVersion;clearTimeout(timer);}});
  document.addEventListener('day-selected',()=>{++disclosureVersion;$('disclosure-materials').textContent='观察日已切换，正在重新核对资料…';pinnedId='';++version;clearTimeout(timer);current=null;busy=false;controls();if(state.view==='analysis'){$('analysis-result').textContent='正在切换股票与日期…';$('analysis-status').textContent='';}});
  document.addEventListener('workspace-selected',e=>{if(e.detail==='stocks'&&state.view==='analysis'){settings();history();}else if(e.detail!=='stocks'){++version;clearTimeout(timer);}});
  settings();controls();
})();
