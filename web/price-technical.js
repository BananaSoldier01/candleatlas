'use strict';
(() => {
  const colors={ma5:'#ad792c',ma10:'#39799b',ma20:'#975b89',up:'#39799b',down:'#a46542',volume:'#8b743d',rsi:'#7767ad',dif:'#ad792c',dea:'#39799b',positive:'#c65148',negative:'#257555',reference:'#89958b',bi:'#647db4',seg:'#8058a1',zs:'#b98436',candidate:'#977a43'};
  const escape=text=>String(text??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const usable=b=>['open_price','close_price','high_price','low_price'].every(k=>Number.isFinite(b[k])&&b[k]>0)
    &&b.high_price>=Math.max(b.open_price,b.close_price)&&b.low_price<=Math.min(b.open_price,b.close_price);
  function compute(items){
    let tail=[],previous=null,gain=0,loss=0,fast=null,slow=null,dea=0;
    return items.map((b,index)=>{
      const point={index,date:b.date,close:null,ma5:null,ma10:null,ma20:null,rsi14:null,macd_dif:null,macd_dea:null,macd_hist:null,volume_ratio5:null,events:[]};
      if(!usable(b)){tail=[];previous=null;gain=loss=dea=0;fast=slow=null;return point;}
      point.close=b.close_price;tail.push(b);
      const n=tail.length;
      if(n>1){
        const delta=point.close-previous.close,up=Math.max(delta,0),down=Math.max(-delta,0);
        if(n<=15){gain+=up;loss+=down;if(n===15){gain/=14;loss/=14;}}
        else{gain=(gain*13+up)/14;loss=(loss*13+down)/14;}
      }
      if(n>=15)point.rsi14=gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss);
      if(n===1)fast=slow=point.close;
      else{fast+=(point.close-fast)*2/13;slow+=(point.close-slow)*2/27;}
      const dif=fast-slow;dea+=(dif-dea)*2/10;
      if(n>=60){point.macd_dif=dif;point.macd_dea=dea;point.macd_hist=2*(dif-dea);}
      for(const n of [5,10,20])if(tail.length>=n)point['ma'+n]=tail.slice(-n).reduce((sum,r)=>sum+r.close_price,0)/n;
      if(previous&&previous.ma20!==null&&point.ma20!==null){
        if(previous.close<=previous.ma20&&point.close>point.ma20)point.events.push({kind:'up',label:'上穿20日线'});
        if(previous.close>=previous.ma20&&point.close<point.ma20)point.events.push({kind:'down',label:'下穿20日线'});
      }
      const volumes=tail.slice(-6).map(r=>r.volume);
      if(volumes.length===6&&volumes.every(v=>Number.isFinite(v)&&v>=0)){
        const mean=volumes.slice(0,5).reduce((sum,v)=>sum+v,0)/5;
        if(mean>0){
          point.volume_ratio5=volumes[5]/mean;
          if(point.volume_ratio5>=1.5)point.events.push({kind:'volume',label:'放量 '+point.volume_ratio5.toFixed(2)+' 倍'});
        }
      }
      previous=point;return point;
    });
  }
  function visible(items,history=[]){
    if(!items.length)return [];
    const warmup=history.filter(b=>b.date<items[0].date);
    return compute([...warmup,...items]).slice(warmup.length).map((p,index)=>({...p,index}));
  }
  function glyph(shape,key){
    const color=colors[key]||colors.reference;
    const paths={line:`<path d="M1 7h20" fill="none" stroke="${color}" stroke-width="${key==='seg'?2.4:1.5}"/>`,dashed:`<path d="M1 7h20" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="6 4"/>`,box:`<rect x="2" y="2" width="18" height="10" fill="${color}" fill-opacity=".13" stroke="${color}"/>`,circle:`<circle cx="11" cy="7" r="4" fill="white" stroke="${color}" stroke-width="1.5"/>`,up:`<path d="M11 3l4 7H7Z" fill="${color}"/>`,down:`<path d="M11 11l4-7H7Z" fill="${color}"/>`,diamond:`<path d="M11 3l4 4-4 4-4-4Z" fill="${color}"/>`,bar:`<rect x="8" y="2" width="6" height="10" fill="${color}"/>`,candle:`<path d="M11 0v14" stroke="${color}"/><rect x="7" y="4" width="8" height="6" fill="${color}"/>`};
    return `<svg class="legend-glyph" data-legend-shape="${shape}" data-legend-key="${key}" viewBox="0 0 22 14" aria-hidden="true">${paths[shape]||paths.line}</svg>`;
  }
  function description(p){
    const values=[5,10,20].map(n=>'MA'+n+' '+(p['ma'+n]===null?'样本不足':p['ma'+n].toFixed(2)));
    if(p.volume_ratio5!==null)values.push('成交量 / 前5日均量 '+p.volume_ratio5.toFixed(2)+' 倍');
    values.push('RSI14 '+(p.rsi14===null?'样本不足':p.rsi14.toFixed(2)));
    values.push(p.macd_dif===null?'MACD 样本不足':'DIF '+p.macd_dif.toFixed(4)+' / DEA '+p.macd_dea.toFixed(4)+' / 柱值 '+p.macd_hist.toFixed(4));
    return values.concat(p.events.map(e=>e.label)).join('；');
  }
  function overlay(points,{items,L,R,W,T,PH,VT,VH,step,y,vmax}){
    let svg=`<defs><clipPath id="price-ma-clip"><rect x="${L}" y="${T}" width="${W-L-R}" height="${PH}"/></clipPath></defs><g class="price-ma-lines" clip-path="url(#price-ma-clip)">`;
    for(const n of [5,10,20]){
      let path='',joined=false;
      for(const p of points){
        if(p['ma'+n]===null){joined=false;continue;}
        path+=(joined?' L':'M')+(L+(p.index+.5)*step).toFixed(2)+' '+y(p['ma'+n]).toFixed(2);joined=true;
      }
      if(path)svg+=`<path data-ma="${n}" d="${path}" stroke="${colors['ma'+n]}" fill="none" stroke-width="1.5"/>`;
    }
    svg+='</g><g class="price-technical-markers">';
    for(const p of points)for(const event of p.events){
      const b=items[p.index],x=L+(p.index+.5)*step;
      const label=p.date+' · '+event.label+'；'+description(p);
      let shape='';
      if(event.kind==='volume'){
        const cy=VT+VH-b.volume/vmax*VH-7;
        shape=`<path d="M${x} ${cy-4}l4 4 -4 4 -4 -4Z" fill="${colors.volume}"/>`;
      }else{
        const up=event.kind==='up',cy=up?Math.min(T+PH-5,y(b.low_price)+10):Math.max(T+5,y(b.high_price)-10);
        shape=`<path d="M${x} ${cy+(up?-4:4)}l4 ${up?7:-7}h-8Z" fill="${colors[event.kind]}"/>`;
      }
      svg+=`<g tabindex="0" role="button" data-candle="${p.index}" data-technical-marker="${event.kind}" aria-label="${escape(label)}"><title>${escape(label)}</title>${shape}</g>`;
    }
    return svg+'</g>';
  }
  function macdExtent(points){
    return Math.max(.01,...points.flatMap(p=>[p.macd_dif,p.macd_dea,p.macd_hist]).filter(Number.isFinite).map(Math.abs))*1.1;
  }
  function cursorAt(g,x,y){
    if(!g||!g.items.length||!Number.isFinite(x)||!Number.isFinite(y)||x<g.L||x>g.W-g.R||y<g.T||y>(g.subplots?760:g.VT+g.VH))return null;
    const index=Math.min(g.items.length-1,Math.max(0,Math.floor((x-g.L)/g.step)));
    const hit={index,date:g.items[index].date,x:g.L+(index+.5)*g.step,y,kind:null,value:null,dateY:385};
    if(y<=g.T+g.PH)Object.assign(hit,{kind:'price',value:g.max-(y-g.T)/g.PH*(g.max-g.min),top:g.T,bottom:g.T+g.PH});
    else if(y>=g.VT&&y<=g.VT+g.VH)Object.assign(hit,{kind:'volume',value:(g.VT+g.VH-y)/g.VH*g.vmax,top:g.VT,bottom:g.VT+g.VH});
    else if(g.subplots&&y>=450&&y<=560)Object.assign(hit,{kind:'rsi',value:(560-y)/110*100,top:450,bottom:560,dateY:574});
    else if(g.subplots&&y>=650&&y<=760)Object.assign(hit,{kind:'macd',value:g.macdExtent*(1-2*(y-650)/110),top:650,bottom:760,dateY:770});
    return hit;
  }
  function panels(points,{items,L,R,W,step}){
    const x=p=>L+(p.index+.5)*step;
    const line=(key,y)=>{let path='',joined=false;for(const p of points){if(p[key]===null){joined=false;continue;}path+=(joined?' L':'M')+x(p).toFixed(2)+' '+y(p[key]).toFixed(2);joined=true;}return path;};
    const ry=value=>450+(100-value)/100*110;
    const last=points.findLast(p=>p.close!==null);
    let svg='<g class="indicator-panels">';
    svg+=`<text class="indicator-title" x="${L}" y="429">RSI14 · 涨跌力度</text><line x1="${L+126}" y1="425" x2="${L+142}" y2="425" stroke="${colors.rsi}" stroke-width="1.5"/><text x="${L+149}" y="429">${last?.rsi14==null?'不足15根':last.rsi14.toFixed(2)}</text>`;
    for(const level of [0,30,50,70,100])svg+=`<line data-rsi-level="${level}" x1="${L}" y1="${ry(level)}" x2="${W-R}" y2="${ry(level)}" stroke="${colors.reference}" stroke-opacity=".4" stroke-dasharray="${level===30||level===70?'6 4':'2 5'}"/><text x="${L-8}" y="${ry(level)+4}" text-anchor="end">${level}</text>`;
    const rsi=line('rsi14',ry);
    if(rsi)svg+=`<path data-indicator="rsi14" d="${rsi}" fill="none" stroke="${colors.rsi}" stroke-width="1.7"/>`;
    else svg+=`<text x="${L+12}" y="511">连续有效日 K 不足15根，暂不绘制</text>`;
    svg+=`<text class="indicator-title" x="${L}" y="609">MACD(12,26,9) · 动量变化</text>`;
    for(const [index,[key,label,bar]] of [['dif','DIF',false],['dea','DEA',false],['positive','正柱',true],['negative','负柱',true]].entries()){
      const xx=L+index*70;
      svg+=(bar?`<rect x="${xx+4}" y="622" width="6" height="10" fill="${colors[key]}"/>`:`<line x1="${xx}" y1="627" x2="${xx+16}" y2="627" stroke="${colors[key]}" stroke-width="1.5"/>`)+`<text x="${xx+21}" y="631">${label}</text>`;
    }
    const values=points.flatMap(p=>[p.macd_dif,p.macd_dea,p.macd_hist]).filter(v=>v!==null);
    const extent=macdExtent(points),my=value=>650+(extent-value)/(extent*2)*110;
    for(const value of [extent,0,-extent])svg+=`<line x1="${L}" y1="${my(value)}" x2="${W-R}" y2="${my(value)}" class="grid"/><text x="${L-8}" y="${my(value)+4}" text-anchor="end">${value.toFixed(extent<.1?4:2)}</text>`;
    for(const p of points)if(p.macd_hist!==null){const yy=my(p.macd_hist),zero=my(0);svg+=`<rect data-indicator="macd_hist" data-sign="${p.macd_hist>=0?'positive':'negative'}" x="${x(p)-Math.min(7,step*.6)/2}" y="${Math.min(yy,zero)}" width="${Math.min(7,step*.6)}" height="${Math.abs(zero-yy)}" fill="${p.macd_hist>=0?colors.positive:colors.negative}"/>`;}
    for(const key of ['dif','dea']){const path=line('macd_'+key,my);if(path)svg+=`<path data-indicator="macd_${key}" d="${path}" fill="none" stroke="${colors[key]}" stroke-width="1.5"/>`;}
    if(!values.length)svg+=`<text x="${L+12}" y="712">连续有效日 K 不足60根，暂不绘制</text>`;
    const every=Math.max(1,Math.ceil(items.length/6));
    items.forEach((b,i)=>{if(i===items.length-1||(i%every===0&&items.length-1-i>=every))svg+=`<text x="${L+(i+.5)*step}" y="784" text-anchor="middle">${escape(b.date.slice(5).replace('-','/'))}</text>`;});
    return svg+'</g>';
  }
  window.PriceTechnical={compute,visible,glyph,description,overlay,panels,macdExtent,cursorAt};
})();
