'use strict';
(() => {
  const C=window.GuideContent;
  const root=document.getElementById('beginner-guide');
  const get=id=>document.getElementById(id);
  let selected='ohlc',group='all',query='';
  const mobile=matchMedia('(max-width:1050px)');
  const glyph=(shape,key,label)=>`<span class="guide-key">${PriceTechnical.glyph(shape,key)}${esc(label)}</span>`;
  const heading={candle:'一根 K 线怎么形成',ma:'均线窗口每天怎样移动',return:'价格变化怎样变成涨跌幅',rsi:'RSI：看上涨和下跌的力度',macd:'MACD：看两条线和柱值的变化'};
  const nav=get('guide-directory'),article=get('guide-article');
  const n=C.fixed;
  // Learning state is independent of the stock research workspace and never writes a report.
  const market={mode:'sample',stocks:null,listDay:'',code:'',end:'',day:'',period:5,series:null,key:'',loading:false,error:'',token:0};
  let sampleIndicatorDay=C.sampleCloses.length-1;
  const key=()=>market.code+'|'+market.end;
  function redrawLab(){const term=C.terms.find(t=>t.id===selected);if(term?.lab&&get('guide-lab'))renderLab(term.lab);}
  function sourceHTML(){
    const real=market.mode==='real',dates=state.tradingDates.filter(d=>d<=state.date);
    return `<div class="guide-data-source"><div class="guide-source-tabs" aria-label="图解数据来源"><button type="button" id="guide-source-sample" data-guide-source="sample" aria-pressed="${!real}">合成示例</button><button type="button" id="guide-source-real" data-guide-source="real" aria-pressed="${real}">我的自选 · 真实行情</button></div>${real?`<div class="guide-real-selectors"><label>自选股票<select id="guide-real-stock"${!market.stocks?.length?' disabled':''}>${market.stocks?.length?market.stocks.map(s=>`<option value="${esc(s.thscode)}"${s.thscode===market.code?' selected':''}>${esc(s.name)} · ${esc(s.thscode)}</option>`).join(''):'<option value="">'+(market.loading?'正在读取自选…':'暂无自选')+'</option>'}</select></label><label>行情截止日<select id="guide-real-end"${!dates.length?' disabled':''}>${dates.map(d=>`<option value="${d}"${d===(market.end||state.date)?' selected':''}>${d}</option>`).join('')}</select></label></div><p class="guide-small">同花顺历史日 K · 前复权 · 沿用现有行情接口和缓存。五个图解共用股票和学习日期；不生成分析报告。</p>`:`<p class="guide-small">合成价格用于理解公式${selected==='rsi'||selected==='macd'?'，RSI 与 MACD 共用合成日期':'，开高低收示例可修改四价'}；切换“我的自选”可对照自己的股票。</p>`}</div>`;
  }
  async function loadMarket(){
    const token=++market.token;
    market.loading=true;market.error='';redrawLab();
    try{
      if(!state.date)throw Error('交易日历尚未就绪，请稍后重试。');
      if(!market.stocks||market.listDay!==state.date){
        const result=await api('workbench',{date:state.date});
        if(token!==market.token||market.mode!=='real')return;
        market.stocks=[...new Map((result.items||[]).filter(s=>/^\d{6}\.(SH|SZ|BJ)$/.test(s.thscode)).map(s=>[s.thscode,{thscode:s.thscode,name:s.name||s.thscode}])).values()];
        market.listDay=state.date;
      }
      if(!market.stocks.length)throw Error('当前观察日没有自选股票，可先到“我的工作台”添加。');
      if(!market.stocks.some(s=>s.thscode===market.code))market.code=market.stocks.find(s=>s.thscode===state.stock?.thscode)?.thscode||market.stocks[0].thscode;
      if(!market.end||market.end>state.date)market.end=state.date;
      redrawLab();
      if(!market.series||market.key!==key()){
        const code=market.code,end=market.end;
        const payload=await api('prices',{code,date:end,period:60,cycle:'day',context:'1'});
        if(token!==market.token||market.mode!=='real')return;
        market.series=C.prepareMarket(payload,code,end);market.key=code+'|'+end;
      }
      if(!market.series.items.some(b=>b.date===market.day))market.day=market.series.items.at(-1).date;
    }catch(e){
      if(token!==market.token||market.mode!=='real')return;
      market.series=null;market.key='';market.error=e.message||'行情读取失败，请重试。';
    }finally{
      if(token===market.token&&market.mode==='real'){market.loading=false;redrawLab();}
    }
  }
  function renderMarketLab(type,controls){
    if(market.loading||market.error||!market.series||market.key!==key()){
      controls.innerHTML=`<p id="guide-real-status" role="status" class="${market.error?'guide-validation':'guide-small'}">${esc(market.error||'正在读取所选自选股行情…')}</p>${market.error?'<button type="button" data-guide-retry>重试读取</button><button type="button" data-guide-route="watch">去我的工作台</button>':''}`;
      return;
    }
    const series=market.series,index=Math.max(0,series.items.findIndex(b=>b.date===market.day)),f=C.marketFrame(series,index,market.period);
    const stock=market.stocks.find(s=>s.thscode===market.code),last=series.points.slice(series.offset).findLast(p=>p.close!==null);
    controls.innerHTML=`<p id="guide-real-status" role="status" class="guide-real-status">${esc(stock.name)} · ${esc(market.code)} · ${esc(series.items[0].date)}～${esc(series.items.at(-1).date)}<br>当前学习：<strong>${esc(f.item.date)}</strong>${f.current===null?' · 本日缺失或四价无效':''} · 最新有效日 ${esc(last?.date||'暂无')}。包含截止日未收盘数据时可能变化，非实时盘口。</p><div class="guide-step-controls"><button type="button" id="guide-real-prev" data-real-step="-1"${index===0?' disabled':''}>← 前一日</button><label class="guide-real-date-label">学习日期<select id="guide-real-day">${series.items.map((b,i)=>`<option value="${b.date}"${i===index?' selected':''}>${b.date}${series.points[series.offset+i].close===null?' · 缺失':''}</option>`).join('')}</select></label><button type="button" id="guide-real-next" data-real-step="1"${index===series.items.length-1?' disabled':''}>后一日 →</button></div>${type==='ma'?`<label class="guide-real-period">均线周期 <select id="guide-real-period">${[5,10,20].map(p=>`<option value="${p}"${p===market.period?' selected':''}>MA${p}</option>`).join('')}</select></label>`:''}`;
    if(type==='rsi'||type==='macd'){
      drawIndicator(type,series.points.slice(series.offset),index,series.points[series.offset+index-1]||null,stock.name+' · '+market.code);
      get('guide-lab-result').innerHTML+=`<p class="guide-small">与主日 K 共用同次读取的历史上下文（最多 250 根）进行平滑初始化；不是只用图上的 60 根。学习日期截断不代表当时保存的原始数据版本。</p>`;
      return;
    }
    if(type==='candle'){
      controls.innerHTML+=`<div class="guide-real-ohlc">${[['开盘',f.item.open_price],['最高',f.item.high_price],['最低',f.item.low_price],['收盘',f.item.close_price]].map(([label,value])=>`<div><span>${label}</span><strong>${n(value)}</strong></div>`).join('')}</div><p class="guide-small">真实四价只读。想试着改变价格形状，请切回合成示例。</p>`;
      if(!f.candle.valid){get('guide-lab-result').innerHTML='<p class="guide-validation">本日缺失或四价无效，暂不绘制蜡烛，也不借用前一日的价格。</p>';return;}
      drawCandle(f.candle,f.item.date);
      get('guide-lab-result').innerHTML+=`<p class="guide-small">前收日期：${esc(f.previousDate||'区间前一交易日（上游参考）')}；前收 ${n(f.previous)} 元。前收缺失时涨跌幅留空。</p>`;
      return;
    }
    const points=series.points.slice(series.offset,series.offset+index+1);
    const extent=points.flatMap(p=>[p.close,type==='ma'?p['ma'+market.period]:null]).concat(type==='ma'?f.window.map(b=>b.close_price):[]).filter(Number.isFinite);
    if(!extent.length){get('guide-lab-result').innerHTML='<p class="guide-validation">截至学习日没有有效价格，暂不能绘图或计算。</p>';return;}
    const min=Math.min(...extent),max=Math.max(...extent),span=Math.max(max-min,max*.02,.02),low=Math.max(0,min-span*.15),high=max+span*.15;
    const x=i=>50+i*560/Math.max(1,series.items.length-1),y=v=>190-(v-low)/(high-low)*145;
    let drawing='<text x="10" y="19">前复权价格（元）</text>';
    for(let i=0;i<4;i++){const value=low+(high-low)*i/3;drawing+=`<line x1="46" y1="${y(value)}" x2="620" y2="${y(value)}" class="guide-gridline"/><text x="3" y="${y(value)+4}">${n(value)}</text>`;}
    const color={5:'#ad792c',10:'#39799b',20:'#975b89'}[market.period];
    if(type==='ma'&&f.window.length){const left=Math.max(0,index-market.period+1);drawing+=`<rect data-real-ma-window="${market.period}" x="${x(left)-4}" y="33" width="${Math.max(8,x(index)-x(left)+8)}" height="164" fill="${color}" fill-opacity=".09" stroke="${color}" stroke-dasharray="3 3"/>`;}
    const line=field=>{
      let path='',joined=false;
      points.forEach((p,i)=>{if(p[field]===null){joined=false;return;}path+=(joined?'L':'M')+x(i)+' '+y(p[field]);joined=true;});return path;
    };
    const priceColor=type==='ma'?'#89958b':'#39799b';
    drawing+=`<path data-real-price-line d="${line('close')}" stroke="${priceColor}" stroke-width="1.3" fill="none"/>`;
    if(type==='ma')drawing+=`<path data-real-ma-line="${market.period}" d="${line('ma'+market.period)}" stroke="${color}" stroke-width="2" fill="none"/>`;
    points.forEach((p,i)=>{
      if(p.close===null)drawing+=`<text data-real-missing="${p.date}" x="${x(i)}" y="187" text-anchor="middle">×</text>`;
      else drawing+=`<circle data-real-price="${p.date}" cx="${x(i)}" cy="${y(p.close)}" r="${i===index?4:2}" fill="${type==='ma'&&f.window.some(b=>b.date===p.date)?color:priceColor}"><title>${p.date} 收盘 ${n(p.close)} 元</title></circle>`;
      if(i===0||i===index||(i%Math.max(1,Math.ceil(series.items.length/5))===0&&index-i>5))drawing+=`<text x="${x(i)}" y="219" text-anchor="middle">${p.date.slice(5).replace('-','/')}</text>`;
    });
    get('guide-lab-chart').innerHTML=svg(drawing,`${stock.name}真实行情，学习日${f.item.date}，${type==='ma'?'均线窗口':'价格变化'}。仅绘制截至学习日的价格。`);
    if(type==='ma'){
      const hidden=f.window.filter(b=>b.date<series.items[0].date).length;
      get('guide-lab-result').innerHTML=`<div class="guide-keys">${glyph('line','ma'+market.period,'MA'+market.period)}${glyph('circle','reference','收盘价')}${glyph('box','ma'+market.period,'参与均值的窗口')}</div>`+(f.ma===null?`<p class="guide-formula">MA${market.period}：连续有效日 K 不足 ${market.period} 根，暂不可计算；缺失不补零。</p>`:`<div class="guide-formula">(${f.window.map(b=>n(b.close_price)).join(' + ')}) ÷ ${market.period}<br><strong>MA${market.period} = ${n(f.ma)}</strong></div><p>窗口：${f.window[0].date}～${f.item.date}，包含当日收盘。${f.leaving?`${f.leaving.date}（${n(f.leaving.close_price)} 元）退出，${f.item.date}（${n(f.current)} 元）进入。`:''}${hidden?`窗口中 ${hidden} 根早于图左端，来自同次读取的历史上下文，仍参与计算。`:''}</p>`);
    }else{
      get('guide-lab-result').innerHTML=f.change===null?'<p class="guide-formula">当前或前一交易日价格缺失，日涨跌幅暂不可计算；不跳过缺失日期代算。</p>':`<div class="guide-formula">(${n(f.current)} ÷ ${n(f.previous)} − 1) × 100% = <strong class="${f.change<0?'price-down':'price-up'}">${f.change>0?'+':''}${n(f.change)}%</strong></div><p>分母来自 ${esc(f.previousDate||'区间前一交易日（上游参考）')} 的前复权收盘 ${n(f.previous)} 元。</p>`;
      get('guide-lab-result').innerHTML+=`<p>相对显示区间首日 ${f.baselineDate}（${n(f.baseline)} 元）的累计价格变化：<strong>${f.total===null?'缺少有效首末价格，暂不可计算':(f.total>0?'+':'')+n(f.total)+'%'}</strong>。按首末价格计算，不将每日涨跌相加；未计交易成本与现金分红。${f.missingCount?`期间 ${f.missingCount} 日缺失，图中断开；累计值仅表示首末变化，不表示中间路径完整。`:''}</p>`;
    }
    get('guide-lab-result').innerHTML+='<p class="guide-small">图中只画到学习日期；之后的价格没有参与当前计算或纵轴范围。</p>';
  }
  function renderDirectory(){
    const rows=C.search(query,group);
    get('guide-result-count').textContent=`${rows.length} / ${C.terms.length} 个词条`;
    get('guide-categories').innerHTML=[['all','全部'],...C.groups].map(([id,title])=>`<button type="button" data-guide-group="${id}" aria-pressed="${group===id}">${esc(title)}</button>`).join('');
    get('guide-term-list').innerHTML=rows.length?C.groups.map(([id,title])=>{
      const found=rows.filter(t=>t.group===id);return found.length?`<div class="guide-term-group"><h3>${esc(title)}</h3>${found.map(t=>`<button type="button" data-guide-term="${t.id}"${t.id===selected?' aria-current="true"':''}>${esc(t.title)}${t.lab?'<span aria-label="含交互图解">↗</span>':''}</button>`).join('')}</div>`:'';
    }).join(''):'<p class="guide-empty">没有匹配词条。试试“均线”“RSI”或“披露”。</p><button type="button" data-guide-clear>清除筛选</button>';
  }
  function sourcesHTML(ids){
    return ids.map(id=>{
      const s=C.sources[id];return `<li>${s.url?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a>`:`<strong>${esc(s.title)}</strong>`}<p>${esc(s.note)}</p></li>`;
    }).join('');
  }
  function chanDiagram(term){
    if(!['fractal','bi','segment','center','confirmation'].includes(term.id))return '';
    return `<figure class="guide-structure"><svg viewBox="0 0 620 170" role="img" aria-label="合成结构示意：蓝色笔、紫色线段、橙色价格重叠框和虚线尾部"><rect x="155" y="58" width="235" height="63" fill="#b98436" fill-opacity=".12" stroke="#b98436"/><path d="M30 133L100 40L165 116L225 59L290 107L350 62L410 96L480 25" stroke="#647db4" stroke-width="2" fill="none"/><path d="M30 133L480 25" stroke="#8058a1" stroke-width="3" fill="none"/><path d="M480 25L565 86" stroke="#8058a1" stroke-width="3" stroke-dasharray="7 5" fill="none"/><circle cx="565" cy="86" r="6" fill="white" stroke="#977a43" stroke-width="2"/><text x="185" y="49">上边：重叠区上沿</text><text x="185" y="141">下边：重叠区下沿</text><text x="458" y="117">虚线：形成中</text><text x="458" y="140">空心点：未确认候选</text></svg><figcaption>合成示意，不是当前股票。方框左右边是结构起止时间；线条不表示未来路径。</figcaption></figure>`;
  }
  function select(id,{focus=false}={}){
    const term=C.terms.find(t=>t.id===id);if(!term)return;
    selected=id;
    for(const b of get('guide-term-list').querySelectorAll('[data-guide-term]')){
      if(b.dataset.guideTerm===id)b.setAttribute('aria-current','true');else b.removeAttribute('aria-current');
    }
    const index=C.terms.indexOf(term),category=C.groups.find(g=>g[0]===term.group)[1];
    article.innerHTML=`<div class="guide-article-head"><span class="eyebrow">${esc(category)} · ${index+1} / ${C.terms.length}</span><span class="muted">约 2 分钟</span></div><h3 id="guide-title" tabindex="-1">${esc(term.title)}</h3><p class="guide-intro">${esc(term.intro)}</p>${term.glyphs&&!['rsi','macd'].includes(term.lab)?`<div class="guide-keys">${term.glyphs.map(g=>glyph(...g)).join('')}</div>`:''}${term.body.map(p=>`<p>${esc(p)}</p>`).join('')}${chanDiagram(term)}<div class="guide-example"><h4>代入一个例子${term.lab?' · 合成':''}</h4><p>${esc(typeof term.example==='function'?term.example():term.example)}</p></div>${term.lab?`<section class="guide-lab" id="guide-lab" aria-label="${heading[term.lab]}"></section>`:''}<div class="guide-misconception"><h4>容易看错的地方</h4><p>${esc(term.mistake)}</p></div>${C.selfCheckHTML(term,esc)}<div class="guide-location"><div><h4>在观市哪里看</h4><p>${esc(term.where)}</p></div><button type="button" class="outline-button" data-guide-route="${term.target}">去${term.target==='watch'?'我的工作台':term.target==='boards'?'连板跟踪':term.target==='market'?'市场总览':'个股研究'} →</button></div><div class="guide-related">接着看：${(term.group==='chan'?['bi','center','confirmation']:term.group==='indicator'?['ma','rsi','macd']:['ohlc','ma','return']).filter(x=>x!==term.id).map(id=>`<button type="button" data-guide-term="${id}">${esc(C.terms.find(t=>t.id===id).title)}</button>`).join('')}</div><details class="guide-sources"><summary>来源、应用口径与核对日期 · ${C.checked}</summary><ul>${sourcesHTML(term.sources)}</ul><p>本页文字、合成数据与 SVG 独立编写。外部资料用于定义核对及教学思路参考；数值以观市本版计算口径为准，未引入外部图表库。</p></details><div class="guide-article-footer"><button type="button" data-guide-term="${C.terms[(index+C.terms.length-1)%C.terms.length].id}">← 上一词条</button><span>${index+1} / ${C.terms.length}</span><button type="button" data-guide-term="${C.terms[(index+1)%C.terms.length].id}">下一词条 →</button></div>`;
    if(term.lab)renderLab(term.lab);
    if(mobile.matches)nav.open=false;
    if(focus){get('guide-title').focus({preventScroll:true});article.scrollIntoView({block:'start'});}
  }
  function svg(content,label,viewBox='0 0 660 225'){
    return `<svg viewBox="${viewBox}" role="img" aria-label="${esc(label)}">${content}</svg>`;
  }
  function drawIndicator(type,allPoints,index,previous,name){
    const points=allPoints.slice(0,index+1),point=allPoints[index],reading=C.indicatorReading(type,point,previous);
    const W=660,L=58,R=24,T=30,H=155,B=T+H,step=(W-L-R)/allPoints.length,x=i=>L+(i+.5)*step;
    const isRSI=type==='rsi',keys=isRSI?['rsi14']:['macd_dif','macd_dea','macd_hist'];
    const extent=Math.max(.01,...points.flatMap(p=>keys.map(k=>p[k])).filter(Number.isFinite).map(Math.abs))*1.15;
    const y=isRSI?value=>T+(100-value)/100*H:value=>T+(extent-value)/(extent*2)*H;
    let drawing=`<text x="${L}" y="17">${isRSI?'RSI14 · 0～100':'MACD(12,26,9) · 元'}</text>`;
    for(const level of isRSI?[0,30,50,70,100]:[-extent,0,extent])drawing+=`<line data-indicator-reference="${level}" x1="${L}" y1="${y(level)}" x2="${W-R}" y2="${y(level)}" class="guide-gridline${isRSI&&[30,70].includes(level)?' guide-indicator-reference':''}"/><text x="${L-8}" y="${y(level)+4}" text-anchor="end">${isRSI?level:n(level,4)}</text>`;
    const path=field=>{
      let d='',joined=false;points.forEach((p,i)=>{if(!Number.isFinite(p[field])){joined=false;return;}d+=(joined?'L':'M')+x(i)+' '+y(p[field]);joined=true;});return d;
    };
    if(isRSI)drawing+=`<path data-guide-indicator="rsi14" d="${path('rsi14')}" fill="none" stroke="#7767ad" stroke-width="2"/>`;
    else{
      points.forEach((p,i)=>{if(!Number.isFinite(p.macd_hist))return;const yy=y(p.macd_hist),zero=y(0);drawing+=`<rect data-guide-indicator="macd_hist" data-date="${esc(p.date)}" data-sign="${p.macd_hist>0?'positive':p.macd_hist<0?'negative':'zero'}" x="${x(i)-Math.min(8,step*.7)/2}" y="${Math.min(yy,zero)}" width="${Math.min(8,step*.7)}" height="${Math.abs(yy-zero)}" fill="${p.macd_hist>=0?'#c65148':'#257555'}"/>`;});
      for(const [key,color] of [['dif','#ad792c'],['dea','#39799b']])drawing+=`<path data-guide-indicator="macd_${key}" d="${path('macd_'+key)}" fill="none" stroke="${color}" stroke-width="1.8"/>`;
    }
    drawing+=`<line data-indicator-cursor="${esc(point.date)}" x1="${x(index)}" y1="${T}" x2="${x(index)}" y2="${B}" stroke="#697b70" stroke-dasharray="4 4"/>`;
    if(isRSI&&reading.available)drawing+=`<circle cx="${x(index)}" cy="${y(reading.value)}" r="4" fill="#fff" stroke="#7767ad" stroke-width="2"/>`;
    const every=Math.max(1,Math.ceil(allPoints.length/5)),label=p=>market.mode==='real'?p.date.slice(5).replace('-','/'):'第'+(p.index+1)+'日';
    points.forEach((p,i)=>{if(i===0||i===index||(i%every===0&&index-i>5))drawing+=`<text x="${x(i)}" y="209" text-anchor="middle">${esc(label(p))}</text>`;});
    if(!reading.available)drawing+=`<text x="${L+12}" y="${T+H/2}">${isRSI?'RSI14 不足15根，暂不可计算':'MACD 不足60根，暂不可计算'}</text>`;
    // Future dates are selectable, but neither their values nor their scale are exposed.
    allPoints.forEach((p,i)=>{drawing+=`<g data-guide-indicator-index="${i}" role="button" tabindex="-1" aria-label="选择 ${esc(p.date)}"><title>${esc(p.date)}${i<=index&&Number.isFinite(p[isRSI?'rsi14':'macd_hist'])?' · '+(isRSI?'RSI14 '+n(p.rsi14):'柱值 '+n(p.macd_hist,4)):''}</title><rect x="${L+i*step}" y="${T}" width="${step}" height="${H}" fill="transparent"/></g>`;});
    get('guide-lab-chart').innerHTML=svg(drawing,`${name} · ${point.date} · ${isRSI?'RSI14':'MACD'}。点击日期位置，或聚焦图表后用左右键切换。`).replace('role="img"','role="group" tabindex="0" id="guide-indicator-svg"');
    const legends=isRSI?[['line','rsi','RSI14'],['dashed','reference','30 / 70 参考线']]:[['line','dif','DIF'],['line','dea','DEA'],['bar','positive','正柱'],['bar','negative','负柱']];
    let result=`<div class="guide-keys">${legends.map(g=>glyph(...g)).join('')}</div><p class="guide-small">点击图中日期位置，或聚焦图表后用 ← / → 切换日期。图中只画到学习日，之后的价格不参与当前指标或坐标范围。</p><p class="guide-indicator-context">${esc(point.date)} · 前复权收盘 <strong>${n(point.close)} 元</strong>${previous?.close>0&&point.close!==null?' · 日涨跌 '+n(C.priceReturn(previous.close,point.close))+'%':''}</p>`;
    if(!reading.available)result+=`<p class="guide-validation" data-indicator-unavailable>${esc(reading.message)}</p>`;
    else if(isRSI)result+=`<div class="guide-formula">RSI14 = <strong data-indicator-value="rsi14">${n(reading.value)}</strong> / 100</div><div class="guide-indicator-lesson"><h4>这一天怎么读</h4><p>位于${esc(reading.zone)}。${reading.delta===null?'前一交易日没有可比 RSI，不比较变化。':'较前一交易日'+(reading.delta>0?'上升 ':reading.delta<0?'下降 ':'变化 ')+n(Math.abs(reading.delta))+' 点（不是股价涨跌百分比）。'}</p><p>${esc(reading.message)}</p></div><details class="guide-indicator-method"><summary>怎么算、为什么有空白</summary><p>先把14次收盘变化分为上涨和下跌，分别取均值，再用 Wilder 平滑：新均值 =（旧均值 × 13 + 本次变动）÷ 14。RSI = 100 − 100 ÷（1 + 平均上涨 ÷ 平均下跌）。需要至少15根连续有效收盘；全平为50，平均下跌为0但存在上涨时为100。</p></details>`;
    else result+=`<div class="guide-macd-values"><div><span>DIF · 快慢均线差</span><strong data-indicator-value="macd_dif">${n(reading.dif,4)}</strong></div><div><span>DEA · DIF的平滑线</span><strong data-indicator-value="macd_dea">${n(reading.dea,4)}</strong></div><div><span>柱值 · 两线距离×2</span><strong data-indicator-value="macd_hist" class="${reading.value<0?'price-down':'price-up'}">${n(reading.value,4)}</strong></div></div><div class="guide-formula">柱值 = 2 ×（DIF − DEA）= ${n(reading.value,4)}</div><div class="guide-indicator-lesson"><h4>这一天怎么读</h4><p>当前为${esc(reading.sign)}。${esc(reading.movement)}</p><p>${esc(reading.message)}</p></div><details class="guide-indicator-method"><summary>怎么算、为什么与别处可能不同</summary><p>DIF = EMA12 − EMA26；DEA 用9期 EMA 平滑 DIF；柱值 = 2 ×（DIF − DEA），单位与价格相同，不是百分比。观市至少60根连续有效收盘才显示，EMA 从窗口首价初始化，DEA 从0起算。按未舍入值计算，展示4位小数，所以展示数值手算末位可能略有差异；其他软件可能用1倍柱值或不同初值。</p></details>`;
    get('guide-lab-result').innerHTML=result;
  }
  function renderSampleIndicator(type,controls){
    const points=C.sample(),index=sampleIndicatorDay;
    controls.innerHTML=`<div class="guide-step-controls"><button type="button" id="guide-indicator-prev" data-indicator-step="-1"${index===0?' disabled':''}>← 前一日</button><label class="guide-real-date-label">合成日期<select id="guide-indicator-sample-day">${points.map((p,i)=>`<option value="${i}"${i===index?' selected':''}>${esc(p.date)}</option>`).join('')}</select></label><button type="button" id="guide-indicator-next" data-indicator-step="1"${index===points.length-1?' disabled':''}>后一日 →</button></div><p class="guide-small">同一组80根确定性合成收盘；RSI 与 MACD 共用日期，可回到起始日观察样本不足时的空白。</p>`;
    drawIndicator(type,points,index,points[index-1]||null,'合成行情');
  }
  function setIndicatorDay(index){
    const length=market.mode==='real'?market.series?.items.length:C.sampleCloses.length;
    if(!Number.isInteger(index)||index<0||index>=length)return;
    if(market.mode==='real')market.day=market.series.items[index].date;else sampleIndicatorDay=index;
    redrawLab();
  }
  function drawCandle(p,label='示例某一日'){
    const range=Math.max(p.high-p.low,p.high*.015,.01),top=p.high+range*.3,bottom=Math.max(0,p.low-range*.3),y=value=>18+(top-value)/(top-bottom)*180;
    let drawing=`<line x1="225" y1="18" x2="225" y2="202" class="guide-axis"/><text x="26" y="20">价格（元）</text>`;
    if(p.high===p.low)drawing+=`<line x1="335" y1="${y(p.high)}" x2="397" y2="${y(p.high)}" class="guide-gridline"/><text x="408" y="${y(p.high)+4}">高 = 低 ${n(p.high)}</text>`;
    else for(const [price,label,offset] of [[p.high,'最高 H',-1],[p.low,'最低 L',1]]){
      const labelY=y(price)+(y(p.low)-y(p.high)<24?offset*12:0);
      drawing+=`<path d="M335 ${y(price)}L397 ${labelY}" class="guide-gridline" fill="none"/><text x="408" y="${labelY+4}">${label} ${n(price)}</text>`;
    }
    if(p.open===p.close)drawing+=`<line x1="175" y1="${y(p.open)}" x2="283" y2="${y(p.open)}" class="guide-gridline"/><text x="26" y="${y(p.open)+4}">开 = 收 ${n(p.open)}</text>`;
    else for(const [price,label,offset] of [[p.open,'开盘 O',p.open>p.close?-1:1],[p.close,'收盘 C',p.close>p.open?-1:1]]){
      const labelY=y(price)+(Math.abs(y(p.open)-y(p.close))<24?offset*12:0);
      drawing+=`<path d="M175 ${labelY}L283 ${y(price)}" class="guide-gridline" fill="none"/><text x="26" y="${labelY+4}">${label} ${n(price)}</text>`;
    }
    drawing+=`<path d="M310 ${y(p.high)}V${y(p.low)}" stroke="${p.color}" stroke-width="2"/><rect data-guide-candle="${p.kind}" x="285" y="${Math.min(y(p.open),y(p.close))}" width="50" height="${Math.max(2,Math.abs(y(p.open)-y(p.close)))}" fill="${p.color}"/><text x="26" y="202" fill="${p.color}">${esc(p.kind)}</text><text x="270" y="222">${esc(label)}</text>`;
    get('guide-lab-chart').innerHTML=svg(drawing,`${label==='示例某一日'?'合成':'真实行情 · '+label+' · '}${p.kind}：开盘${n(p.open)}，最高${n(p.high)}，最低${n(p.low)}，收盘${n(p.close)}`);
    get('guide-lab-result').innerHTML=`<p class="guide-formula">实体 ${n(p.body)}　·　上影 ${n(p.upper)}　·　下影 ${n(p.lower)} 元</p><p><b>${p.kind}</b> 比较开盘与收盘；相对前收的涨跌幅为 <strong class="${p.change===null?'':p.change<0?'price-down':'price-up'}">${p.change===null?'缺少有效前收，暂不可计算':(p.change>0?'+':'')+n(p.change)+'%'}</strong>。</p>`;
  }
  function renderLab(type){
    const lab=get('guide-lab'),focusId=document.activeElement?.id;
    lab.innerHTML=`<div class="guide-lab-heading"><div><span class="eyebrow">动手试一试 · ${market.mode==='real'?'真实行情':'合成行情'}</span><h4>${heading[type]}</h4></div><button type="button" data-lab-reset>重置</button></div><nav class="guide-lab-switch" aria-label="切换图解，保留股票和学习日期">${[['ohlc','candle','K 线'],['ma','ma','MA'],['return','return','涨跌幅'],['rsi','rsi','RSI'],['macd','macd','MACD']].map(([id,kind,label])=>`<button type="button" data-guide-term="${id}" aria-pressed="${kind===type}">${label}</button>`).join('')}</nav>${sourceHTML()}<div id="guide-lab-controls"></div><div id="guide-lab-chart" class="guide-lab-chart"></div><div id="guide-lab-result" role="status" aria-live="polite"></div>`;
    const controls=get('guide-lab-controls');
    if(market.mode==='real')renderMarketLab(type,controls);
    else if(type==='rsi'||type==='macd')renderSampleIndicator(type,controls);
    else if(type==='candle'){
      const defaults={open:10,high:12,low:9,close:11,previous:10};
      controls.innerHTML=`<div class="guide-candle-presets"><button type="button" data-candle-preset="up">阳线</button><button type="button" data-candle-preset="green-up">阴线但上涨</button><button type="button" data-candle-preset="cross">十字 K</button></div><div class="guide-number-grid">${[['open','开盘 O'],['high','最高 H'],['low','最低 L'],['close','收盘 C'],['previous','前收（可留空）']].map(([key,title])=>`<label>${title}<input id="guide-${key}" type="number" min="0.01" step="0.01" value="${defaults[key]}"></label>`).join('')}</div><p class="guide-small">输入价格后图形同步变化。最高须 ≥ 开盘和收盘，最低须 ≤ 两者；用 Tab 切换输入框。</p>`;
      const update=()=>{
        const v=Object.fromEntries(Object.keys(defaults).map(k=>[k,get('guide-'+k).valueAsNumber])),p=C.candle(v);
        get('guide-lab-chart').innerHTML='';
        if(!p.valid){get('guide-lab-result').innerHTML='<p class="guide-validation">四价不合法：请使用正数，并让最高 ≥ 开盘/收盘、最低 ≤ 开盘/收盘。</p>';return;}
        drawCandle(p);
      };
      controls.addEventListener('input',update);
      controls.addEventListener('click',event=>{
        const b=event.target.closest('[data-candle-preset]');if(!b)return;
        const presets={up:defaults,'green-up':{open:12,high:12.5,low:10.5,close:11,previous:10},cross:{open:10,high:12,low:9,close:10,previous:10}};
        for(const [key,value] of Object.entries(presets[b.dataset.candlePreset]))get('guide-'+key).value=value;
        update();
      });update();
    }else if(type==='ma'){
      const closes=Array.from({length:30},(_,i)=>i<5?10+i:i===5?20:Number((14+Math.sin(i*.55)*2+(i-6)*.12).toFixed(2)));
      controls.innerHTML='<div class="guide-step-controls"><label>均线周期 <select id="guide-ma-period"><option value="5">MA5</option><option value="10">MA10</option><option value="20">MA20</option></select></label><label><input type="checkbox" id="guide-ma-gap"> 在第8日加入缺失行情</label></div><div class="guide-step-controls"><button type="button" data-step="-1">← 前一天</button><label class="guide-range-label">观察日 <input type="range" id="guide-ma-day" min="0" max="29" value="4"><output id="guide-ma-day-label"></output></label><button type="button" data-step="1">后一天 →</button></div>';
      const update=()=>{
        const period=Number(get('guide-ma-period').value),index=Number(get('guide-ma-day').value),data=closes.slice();if(get('guide-ma-gap').checked)data[7]=null;
        const f=C.movingFrame(data,period,index),color={5:'#ad792c',10:'#39799b',20:'#975b89'}[period],xs=i=>42+i*20,ys=value=>190-(value-8)*12;
        get('guide-ma-day-label').textContent='第 '+(index+1)+' 日';
        for(const b of controls.querySelectorAll('[data-step]'))b.disabled=Number(b.dataset.step)<0?index===0:index===29;
        let drawing=`<text x="12" y="18">价格（元）</text><text x="493" y="18">合成示例 · 共30日</text>`;
        for(const value of [10,15,20])drawing+=`<line x1="38" y1="${ys(value)}" x2="632" y2="${ys(value)}" class="guide-gridline"/><text x="8" y="${ys(value)+4}">${value}</text>`;
        if(f.value!==null)drawing+=`<rect data-ma-window="${period}" x="${xs(f.windowIndices[0])-8}" y="30" width="${period*20-4}" height="170" fill="${color}" fill-opacity=".09" stroke="${color}" stroke-dasharray="3 3"/>`;
        let path='',joined=false;
        for(let i=0;i<=index;i++){const value=f.points[i]['ma'+period];if(value===null){joined=false;continue;}path+=(joined?'L':'M')+xs(i)+' '+ys(value);joined=true;}
        drawing+=`<path data-guide-ma-line="${period}" d="${path}" stroke="${color}" stroke-width="2" fill="none"/>`;
        data.forEach((value,i)=>{
          const active=f.windowIndices.includes(i),future=i>index;
          if(value===null)drawing+=`<text x="${xs(i)}" y="192" text-anchor="middle">×</text>`;
          else drawing+=`<circle data-ma-price="${i}" cx="${xs(i)}" cy="${ys(value)}" r="${i===index?5:3}" fill="${active?color:'#a8b2ab'}" opacity="${future?.3:1}"><title>第${i+1}日 收盘${n(value)}${future?'（未参与当前计算）':''}</title></circle>`;
          if(i===0||(i+1)%5===0)drawing+=`<text x="${xs(i)}" y="219" text-anchor="middle">${i+1}日</text>`;
        });
        get('guide-lab-chart').innerHTML=svg(drawing,`MA${period}滚动窗口，观察第${index+1}日。${f.value===null?'连续样本不足':`当前均值${n(f.value)}`}`);
        get('guide-lab-result').innerHTML=f.value===null?`<p class="guide-formula">MA${period}：连续有效收盘不足 ${period} 根，暂不可计算。</p><p>缺失不补 0；断点之后重新累计。右侧浅灰点属于后面的示例日，没有参与当前计算。</p>`:`<div class="guide-formula">(${f.windowIndices.map(i=>n(data[i])).join(' + ')}) ÷ ${period}<br><strong>MA${period} = ${n(f.value)}</strong></div><p>方框中的第 ${f.windowIndices[0]+1}～${index+1} 日参与均值，包含当前收盘 ${n(data[index])} 元。${f.leaving!==null?`从前一日移动到此日时，第 ${f.leaving+1} 日退出，第 ${index+1} 日进入。`:''}浅灰点未参与当前窗口。</p>`;
      };
      controls.addEventListener('input',update);
      controls.addEventListener('click',event=>{const b=event.target.closest('[data-step]');if(!b)return;get('guide-ma-day').value=Number(get('guide-ma-day').value)+Number(b.dataset.step);update();});update();
    }else{
      const prices=[10,11,9.9,10.4,10.4,9.36,10.3];
      controls.innerHTML='<div class="guide-step-controls"><button type="button" data-step="-1">← 上一步</button><label class="guide-range-label">观察日 <input type="range" id="guide-return-day" min="0" max="6" value="1"><output id="guide-return-day-label"></output></label><button type="button" data-step="1">下一步 →</button></div><p class="guide-small">逐日代入价格。第 1 日没有前收；后面的日期不会参与当前收益率计算。</p>';
      const update=()=>{
        const index=Number(get('guide-return-day').value),current=prices[index],previous=prices[index-1],change=C.priceReturn(previous,current),total=C.priceReturn(prices[0],current),xs=i=>55+i*89,ys=value=>175-(value-9)*55;
        get('guide-return-day-label').textContent='第 '+(index+1)+' 日';
        for(const b of controls.querySelectorAll('[data-step]'))b.disabled=Number(b.dataset.step)<0?index===0:index===prices.length-1;
        let drawing='<text x="14" y="19">收盘价（元）</text><line x1="35" y1="195" x2="630" y2="195" class="guide-axis"/>';
        const path=prices.slice(0,index+1).map((p,i)=>(i?'L':'M')+xs(i)+' '+ys(p)).join('');
        drawing+=`<path d="${path}" stroke="#39799b" stroke-width="2" fill="none"/>`;
        prices.forEach((p,i)=>{const active=i===index||i===index-1;drawing+=`<circle cx="${xs(i)}" cy="${ys(p)}" r="${active?6:3}" fill="${i===index?'#207452':'#39799b'}" opacity="${i>index?.22:1}"/><text x="${xs(i)}" y="${ys(p)-14}" text-anchor="middle" opacity="${i>index?.4:1}">${n(p)}</text><text x="${xs(i)}" y="218" text-anchor="middle">${i+1}日</text>`;});
        get('guide-lab-chart').innerHTML=svg(drawing,`收益率示例，当前第${index+1}日，收盘${n(current)}元`);
        get('guide-lab-result').innerHTML=change===null?'<p class="guide-formula">第1日：缺少前值，暂不可计算日涨跌幅。</p><p>没有前值与涨跌为 0% 不同。观察从这里开始，后续才有比较基准。</p>':`<div class="guide-formula">(${n(current)} ÷ ${n(previous)} − 1) × 100% = <strong class="${change<0?'price-down':'price-up'}">${change>0?'+':''}${n(change)}%</strong></div><p>分母是前一日 ${n(previous)} 元。相对第1日的累计变化为 <strong class="${total<0?'price-down':'price-up'}">${total>0?'+':''}${n(total)}%</strong>；按首末价格计算，不把每日百分比相加。未计交易成本与现金分红。</p>`;
      };
      controls.addEventListener('input',update);
      controls.addEventListener('click',event=>{const b=event.target.closest('[data-step]');if(!b)return;get('guide-return-day').value=Number(get('guide-return-day').value)+Number(b.dataset.step);update();});update();
    }
    lab.querySelector('[data-lab-reset]').addEventListener('click',()=>{if(market.mode==='real'&&market.series){market.day=market.series.items.at(-1).date;market.period=5;}if(type==='rsi'||type==='macd')sampleIndicatorDay=C.sampleCloses.length-1;renderLab(type);get('guide-lab').querySelector('[data-lab-reset]').focus();});
    if(focusId)get(focusId)?.focus({preventScroll:true});
  }
  root.addEventListener('click',event=>{
    const hit=event.target.closest('[data-guide-indicator-index]');
    if(hit){setIndicatorDay(Number(hit.dataset.guideIndicatorIndex));get('guide-indicator-svg')?.focus({preventScroll:true});return;}
    const indicatorStep=event.target.closest('[data-indicator-step]');
    if(indicatorStep){setIndicatorDay(sampleIndicatorDay+Number(indicatorStep.dataset.indicatorStep));return;}
    const source=event.target.closest('[data-guide-source]');
    if(source){
      if(source.dataset.guideSource===market.mode)return;
      market.mode=source.dataset.guideSource;
      if(market.mode==='real')loadMarket();
      else{++market.token;market.loading=false;market.error='';redrawLab();}
      return;
    }
    if(event.target.closest('[data-guide-retry]')){if(!market.stocks?.length)market.stocks=null;loadMarket();return;}
    const step=event.target.closest('[data-real-step]');
    if(step&&market.series){
      const items=market.series.items,index=items.findIndex(b=>b.date===market.day),next=Math.max(0,Math.min(items.length-1,index+Number(step.dataset.realStep)));
      market.day=items[next].date;redrawLab();return;
    }
    const term=event.target.closest('[data-guide-term]');if(term){select(term.dataset.guideTerm,{focus:true});return;}
    const category=event.target.closest('[data-guide-group]');if(category){group=category.dataset.guideGroup;renderDirectory();get('guide-categories').querySelector(`[data-guide-group="${group}"]`).focus();return;}
    if(event.target.closest('[data-guide-clear]')){query='';group='all';get('guide-search').value='';renderDirectory();get('guide-search').focus();return;}
    const route=event.target.closest('[data-guide-route]');if(route)showWorkspace(route.dataset.guideRoute);
  });
  root.addEventListener('change',event=>{
    const id=event.target.id;
    if(id==='guide-real-stock'||id==='guide-real-end'){
      if(id==='guide-real-stock')market.code=event.target.value;else market.end=event.target.value;
      market.day='';loadMarket();
    }else if(id==='guide-real-day'){market.day=event.target.value;redrawLab();}
    else if(id==='guide-real-period'){market.period=Number(event.target.value);redrawLab();}
    else if(id==='guide-indicator-sample-day')setIndicatorDay(Number(event.target.value));
  });
  root.addEventListener('keydown',event=>{
    if(!event.target.closest('#guide-indicator-svg')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const index=market.mode==='real'?market.series.items.findIndex(b=>b.date===market.day):sampleIndicatorDay;
    const last=(market.mode==='real'?market.series.items.length:C.sampleCloses.length)-1;
    setIndicatorDay(event.key==='Home'?0:event.key==='End'?last:Math.max(0,Math.min(last,index+(event.key==='ArrowRight'?1:-1))));
  });
  get('guide-search').addEventListener('input',event=>{query=event.target.value;renderDirectory();});
  document.addEventListener('click',event=>{
    const link=event.target.closest('[data-open-guide]');if(!link)return;
    showWorkspace('guide');select(link.dataset.openGuide,{focus:true});
  });
  document.addEventListener('records-updated',()=>{market.stocks=null;if(market.mode==='real'&&location.hash==='#guide')loadMarket();});
  document.addEventListener('day-selected',()=>{
    ++market.token;market.loading=false;market.end=state.date;market.day='';market.series=null;market.key='';
    if(market.mode==='real'&&location.hash==='#guide')loadMarket();else redrawLab();
  });
  document.addEventListener('workspace-selected',event=>{
    if(event.detail==='guide'&&market.mode==='real'&&(!market.series||market.listDay!==state.date||market.key!==key()))loadMarket();
  });
  nav.open=!mobile.matches;mobile.addEventListener('change',()=>{nav.open=!mobile.matches;});
  renderDirectory();select(selected);
})();
