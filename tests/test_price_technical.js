const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync('web/price-technical.js','utf8'),sandbox);
const {compute,visible,glyph,description,overlay,panels,cursorAt,macdExtent}=sandbox.window.PriceTechnical;
const plain=value=>JSON.parse(JSON.stringify(value));
const bars=(closes,volumes=[])=>closes.map((close,i)=>({date:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10),open_price:close,close_price:close,high_price:close===null?null:close+1,low_price:close===null?null:close-1,volume:volumes[i]??100}));

test('moving averages require complete contiguous windows',()=>{
  const p=compute(bars(Array.from({length:20},(_,i)=>i+2)));
  assert.equal(p[3].ma5,null);assert.equal(p[4].ma5,4);
  assert.equal(p[8].ma10,null);assert.equal(p[9].ma10,6.5);
  assert.equal(p[18].ma20,null);assert.equal(p[19].ma20,11.5);
});
test('crossings compare each close to its own daily MA20',()=>{
  const p=compute(bars([...Array(19).fill(10),12,8,12]));
  assert.equal(p[19].events.length,0);
  assert.equal(p[20].events[0].kind,'down');
  assert.equal(p[21].events[0].kind,'up');
});
test('touching the average is not itself a crossing',()=>{
  const p=compute(bars([...Array(21).fill(10),12]));
  assert.equal(p[20].events.length,0);assert.equal(p[21].events[0].kind,'up');
  assert.equal(compute(bars([...Array(20).fill(10),8])).at(-1).events[0].kind,'down');
});
test('volume uses the prior five days and includes the exact 1.5 threshold',()=>{
  const p=compute(bars(Array(6).fill(10),[100,100,100,100,100,150]));
  assert.equal(p[4].volume_ratio5,null);assert.equal(p[5].volume_ratio5,1.5);
  assert.equal(p[5].events[0].kind,'volume');
  assert.equal(compute(bars(Array(6).fill(10),[100,100,100,100,100,149])).at(-1).events.length,0);
});
test('zero denominator and zero current volume do not invent a surge',()=>{
  assert.equal(compute(bars(Array(6).fill(10),[0,0,0,0,0,100])).at(-1).volume_ratio5,null);
  const p=compute(bars(Array(6).fill(10),[100,100,100,100,100,0])).at(-1);
  assert.equal(p.volume_ratio5,0);assert.equal(p.events.length,0);
});
test('missing or invalid volume suppresses only the volume comparison',()=>{
  for(const bad of [null,-1,NaN,Infinity,'100']){
    const data=bars(Array(20).fill(10));data[18].volume=bad;
    const p=compute(data).at(-1);assert.equal(p.volume_ratio5,null);assert.equal(p.ma20,10);
  }
});
test('a missing candle resets average and crossing context',()=>{
  const p=compute(bars([...Array(20).fill(10),null,...Array(20).fill(20)]));
  assert.equal(p[20].close,null);assert.equal(p[39].ma20,null);
  assert.equal(p[40].ma20,20);assert.equal(p[40].events.length,0);
});
test('impossible OHLC and nonpositive prices cannot acquire marks',()=>{
  for(const patch of [{high_price:9},{low_price:11},{open_price:0},{close_price:Infinity},{close_price:'10'}]){
    const data=bars(Array(21).fill(10));Object.assign(data[20],patch);
    const p=compute(data).at(-1);assert.equal(p.close,null);assert.equal(p.events.length,0);
  }
});
test('each historical prefix equals the corresponding full result',()=>{
  const data=bars(Array.from({length:80},(_,i)=>15+Math.sin(i)*4),Array.from({length:80},(_,i)=>i%9?100:230));
  data[27].close_price=null;
  const full=plain(compute(data));
  for(let n=1;n<=data.length;n++)assert.deepEqual(plain(compute(data.slice(0,n))),full.slice(0,n));
});
test('future changes cannot alter earlier marks',()=>{
  const data=bars([...Array(20).fill(10),12,8,12]);
  const before=plain(compute(data).slice(0,21));data[22].close_price=99;data[22].high_price=100;
  assert.deepEqual(plain(compute(data).slice(0,21)),before);
});
test('inputs remain unchanged',()=>{
  const data=bars(Array(30).fill(10));data.forEach(Object.freeze);Object.freeze(data);
  const before=JSON.stringify(data);compute(data);assert.equal(JSON.stringify(data),before);
});
test('SVG averages break at gaps',()=>{
  const data=bars([...Array(7).fill(10),null,...Array(7).fill(10)]);
  const svg=overlay(compute(data),{items:data,L:40,R:10,W:600,T:20,PH:250,VT:300,VH:60,step:30,y:v=>100-v,vmax:100});
  const path=svg.match(/data-ma="5" d="([^"]+)"/)[1];
  assert.equal((path.match(/M/g)||[]).length,2);assert.equal(svg.includes('NaN'),false);
});
test('marker dates are escaped in SVG labels and tooltips',()=>{
  const data=bars([...Array(20).fill(10),12]);data[20].date='<img src=x onerror="bad()">';
  const svg=overlay(compute(data),{items:data,L:40,R:10,W:600,T:20,PH:250,VT:300,VH:60,step:20,y:v=>100-v,vmax:100});
  assert.equal(svg.includes('<img'),false);assert.ok(svg.includes('&lt;img'));
  assert.ok(svg.includes('data-technical-marker="up"'));
});
test('detail describes the measurable event without a trading instruction',()=>{
  const p=compute(bars([...Array(20).fill(10),12])).at(-1);
  const text=description(p);assert.ok(text.includes('MA20'));assert.ok(text.includes('上穿20日线'));
  assert.equal(/买入|卖出|必涨|必跌/.test(text),false);
});

test('RSI requires fourteen changes and handles rising falling and flat prices',()=>{
  const up=compute(bars(Array.from({length:20},(_,i)=>10+i)));
  assert.equal(up[13].rsi14,null);assert.equal(up[14].rsi14,100);
  assert.equal(compute(bars(Array.from({length:20},(_,i)=>100-i))).at(-1).rsi14,0);
  assert.equal(compute(bars(Array(20).fill(10))).at(-1).rsi14,50);
});
test('MACD follows the existing sixty-sample policy',()=>{
  const p=compute(bars(Array(60).fill(10)));
  assert.equal(p[58].macd_dif,null);assert.equal(p[59].macd_dif,0);
  assert.equal(p[59].macd_dea,0);assert.equal(p[59].macd_hist,0);
});
test('all prefixes agree with the formal Python technical calculation',()=>{
  const data=bars(Array.from({length:190},(_,i)=>50+Math.sin(i*.3)*8+i*.04));
  data[74].close_price=null;
  const script='import json,sys\nfrom analysis import technical\nrows=json.load(sys.stdin)\nprint(json.dumps([technical(rows[:n]) for n in range(1,len(rows)+1)]))';
  const expected=JSON.parse(require('node:child_process').execFileSync('python3',['-c',script],{input:JSON.stringify(data),encoding:'utf8'}));
  compute(data).forEach((p,i)=>{
    for(const key of ['rsi14','macd_dif','macd_dea','macd_hist']){
      if(expected[i][key]===null)assert.equal(p[key],null,key+' '+i);
      else assert.ok(Math.abs(p[key]-expected[i][key])<=(key==='rsi14'?.005:.00005)+1e-9,key+' '+i);
    }
  });
});
test('background history supplies warmup without exposing future records',()=>{
  const data=bars(Array.from({length:150},(_,i)=>50+Math.sin(i)*3));
  const short=visible(data.slice(130,140),data);
  const wide=visible(data.slice(100,140),data);
  assert.equal(short.length,10);assert.equal(short[0].index,0);
  assert.ok(short[0].macd_dif!==null);
  assert.deepEqual(plain(short.at(-1)),{...plain(wide.at(-1)),index:9});
  const before=plain(short);data[145].close_price=1000;
  assert.deepEqual(plain(visible(data.slice(130,140),data)),before);
});
test('visible data gaps override context and reset both indicators',()=>{
  const data=bars(Array.from({length:100},(_,i)=>30+Math.sin(i)));
  const shown=data.slice(-30).map(b=>({...b}));shown[10].close_price=null;
  const p=visible(shown,data);
  assert.equal(p[24].rsi14,null);assert.ok(p[25].rsi14!==null);
  assert.equal(p.at(-1).macd_dif,null);
});
test('indicator plots have gaps, correct bar signs, and finite flat axes',()=>{
  const data=bars([...Array.from({length:90},(_,i)=>50+Math.sin(i)),null,...Array.from({length:90},(_,i)=>60+Math.sin(i))]);
  const svg=panels(compute(data),{items:data,L:56,R:14,W:900,step:4});
  for(const key of ['rsi14','macd_dif','macd_dea'])assert.equal((svg.match(new RegExp('data-indicator="'+key+'" d="([^"]+)"'))[1].match(/M/g)||[]).length,2);
  assert.ok(svg.includes('data-sign="positive"')&&svg.includes('data-sign="negative"'));
  const flat=bars(Array(70).fill(10));
  const flatSvg=panels(compute(flat),{items:flat,L:56,R:14,W:900,step:10});
  assert.equal(/NaN|Infinity/.test(flatSvg),false);
  assert.ok(flatSvg.match(/<rect data-indicator="macd_hist"[^>]+>/g).every(rect=>rect.includes('height="0"')));
});
test('short samples show explicit empty indicator charts',()=>{
  const data=bars(Array(10).fill(10));const svg=panels(compute(data),{items:data,L:56,R:14,W:420,step:30});
  assert.equal(svg.includes('data-indicator='),false);
  assert.ok(svg.includes('不足15根')&&svg.includes('不足60根'));
});
test('legend glyphs show the same color and shape as their chart objects',()=>{
  assert.ok(glyph('line','ma5').includes('stroke="#ad792c"'));
  assert.ok(glyph('line','bi').includes('stroke="#647db4"'));
  assert.ok(glyph('line','seg').includes('stroke-width="2.4"'));
  assert.ok(glyph('box','zs').includes('<rect')&&glyph('box','zs').includes('stroke="#b98436"'));
  assert.ok(glyph('dashed','reference').includes('stroke-dasharray="6 4"'));
  assert.ok(glyph('circle','candidate').includes('<circle'));
  assert.ok(glyph('bar','positive').includes('fill="#c65148"'));
  assert.ok(glyph('bar','negative').includes('fill="#257555"'));
});

const geometry=()=>({items:bars([20,25,null,30]),L:56,R:14,W:470,step:100,T:24,PH:250,min:10,max:50,VT:310,VH:65,vmax:10000,subplots:true,macdExtent:2});
test('cursor inverts the actual price scale and snaps only its date to a candle',()=>{
  const g=geometry();
  for(const [y,value]of [[24,50],[149,30],[274,10]])assert.equal(cursorAt(g,60,y).value,value);
  const first=cursorAt(g,56,149),last=cursorAt(g,456,149);
  assert.equal(first.index,0);assert.equal(first.x,106);
  assert.equal(last.index,3);assert.equal(last.x,406);assert.equal(last.date,g.items[3].date);
  assert.equal(first.value,30);assert.equal(g.items[0].close_price,20);
});
test('volume RSI and MACD use their own vertical scales',()=>{
  const g=geometry();
  for(const [kind,pairs]of [['volume',[[310,10000],[342.5,5000],[375,0]]],['rsi',[[450,100],[505,50],[560,0]]],['macd',[[650,2],[705,0],[760,-2]]]]){
    for(const [y,value]of pairs){const hit=cursorAt(g,100,y);assert.equal(hit.kind,kind);assert.equal(hit.value,value);}
  }
});
test('cursor preserves a missing candle date instead of borrowing nearby data',()=>{
  const g=geometry(),hit=cursorAt(g,300,149);
  assert.equal(hit.index,2);assert.equal(hit.date,g.items[2].date);assert.equal(g.items[2].close_price,null);
  for(const y of [400,600]){const gap=cursorAt(g,300,y);assert.equal(gap.kind,null);assert.equal(gap.value,null);}
});
test('cursor rejects margins invalid coordinates empty data and hidden subplots',()=>{
  const g=geometry();
  for(const [x,y]of [[55,149],[457,149],[100,23],[100,761],[NaN,100],[100,Infinity]])assert.equal(cursorAt(g,x,y),null);
  assert.equal(cursorAt(null,100,100),null);assert.equal(cursorAt({...g,items:[]},100,100),null);
  assert.equal(cursorAt({...g,subplots:false},100,450),null);
  assert.equal(cursorAt({...g,subplots:false},100,375).kind,'volume');
});
test('cursor MACD extent equals the panel scale and remains finite for blank or flat data',()=>{
  assert.equal(macdExtent([]),.011000000000000001);
  assert.ok(Number.isFinite(macdExtent(compute(bars(Array(70).fill(10))))));
  const points=[{macd_dif:2,macd_dea:-3,macd_hist:null},{macd_dif:NaN,macd_dea:Infinity,macd_hist:1}];
  assert.equal(macdExtent(points),3.3000000000000003);
  const g=geometry();g.macdExtent=macdExtent(points);
  assert.equal(cursorAt(g,100,650).value,3.3000000000000003);
});
