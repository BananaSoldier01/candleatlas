const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync('web/price-technical.js','utf8'),sandbox);
vm.runInNewContext(fs.readFileSync('web/guide-content.js','utf8'),sandbox);
const C=sandbox.window.GuideContent;
const plain=x=>JSON.parse(JSON.stringify(x));
const near=(a,b,tolerance=1e-9)=>assert.ok(Math.abs(a-b)<tolerance,`${a} != ${b}`);

test('thirty readable terms cover all six groups without dangling sources or destinations',()=>{
  assert.equal(C.terms.length,30);assert.equal(new Set(C.terms.map(t=>t.id)).size,30);
  assert.deepEqual(plain(C.groups.map(([g])=>C.terms.filter(t=>t.group===g).length)),[4,8,7,5,3,3]);
  for(const t of C.terms){
    assert.ok(t.intro&&t.body.length>=2&&t.mistake&&t.where&&t.sources.length);
    assert.ok(['watch','stocks','market','boards'].includes(t.target));
    const example=typeof t.example==='function'?t.example():t.example;
    assert.ok(example.length>12&&!/NaN|Infinity|undefined/.test(example));
    for(const id of t.sources){assert.ok(C.sources[id]);if(C.sources[id].url)assert.match(C.sources[id].url,/^https:\/\//);}
  }
});
test('search works with Chinese, English aliases and category constraints',()=>{
  assert.ok(C.search('均线').some(t=>t.id==='ma'));
  assert.ok(C.search('rSi14').some(t=>t.id==='rsi'));
  assert.ok(C.search('oHlC').some(t=>t.id==='ohlc'));
  assert.ok(C.search('PE PB').some(t=>t.id==='valuation'));
  assert.equal(C.search('RSI','trade').length,0);
  assert.equal(C.search('不存在的术语').length,0);
});
test('a green candle can have a positive day return',()=>{
  const p=C.candle({open:12,high:12.5,low:10.5,close:11,previous:10});
  assert.equal(p.kind,'阴线');assert.equal(p.color,'#257555');near(p.change,10);
  near(p.body,1);near(p.upper,.5);near(p.lower,.5);
});
test('equal open and close is called a cross even though app uses red',()=>{
  const p=C.candle({open:10,high:12,low:9,close:10,previous:10});
  assert.equal(p.kind,'十字 K');assert.equal(p.color,'#c65148');assert.equal(p.body,0);
});
test('invalid OHLC is rejected instead of silently repaired',()=>{
  const base={open:10,high:12,low:9,close:11,previous:10};
  for(const delta of [{high:10},{low:11},{close:0},{open:-1},{high:Infinity},{low:NaN},{close:null}])assert.equal(C.candle({...base,...delta}).valid,false);
  assert.equal(C.candle({...base,previous:NaN}).valid,true);
  assert.equal(C.candle({...base,previous:NaN}).change,null);
});
test('price returns require valid prices, not invented zero denominators',()=>{
  for(const bad of [null,undefined,NaN,0,-1,'10',Infinity]){
    assert.equal(C.priceReturn(bad,11),null);assert.equal(C.priceReturn(10,bad),null);
  }
  near(C.priceReturn(10,11),10);near(C.priceReturn(11,9.9),-10);near(C.priceReturn(10,9.9),-1);
  assert.equal(C.priceReturn(10,10),0);
});
test('MA5 first appears at the fifth candle and includes the current close',()=>{
  const data=[10,11,12,13,14,20];
  assert.equal(C.movingFrame(data,5,3).value,null);
  const fifth=C.movingFrame(data,5,4);assert.equal(fifth.value,12);assert.equal(fifth.leaving,null);
  assert.deepEqual(plain(fifth.windowIndices),[0,1,2,3,4]);
  const sixth=C.movingFrame(data,5,5);assert.equal(sixth.value,14);assert.equal(sixth.leaving,0);assert.equal(sixth.entering,5);
});
test('MA10 and MA20 have no extra warm-up bar',()=>{
  for(const period of [10,20]){
    const data=Array.from({length:period},(_,i)=>10+i);
    assert.equal(C.movingFrame(data,period,period-2).value,null);
    assert.equal(C.movingFrame(data,period,period-1).value,(data[0]+data.at(-1))/2);
  }
});
test('a gap resets the moving window without being averaged as zero',()=>{
  const data=[10,11,12,13,14,null,20,20,20,20,20];
  assert.equal(C.movingFrame(data,5,9).value,null);
  const recovered=C.movingFrame(data,5,10);assert.equal(recovered.value,20);assert.equal(recovered.leaving,null);
  assert.deepEqual(plain(recovered.windowIndices),[6,7,8,9,10]);
});
test('moving example never depends on future values and does not mutate data',()=>{
  const data=[10,11,12,13,14,20],before=data.slice();
  const f=C.movingFrame(data,5,4);data[5]=99;
  assert.equal(C.movingFrame(data,5,4).value,f.value);assert.deepEqual(data.slice(0,5),before.slice(0,5));
  assert.equal(C.movingFrame(data,7,4),null);assert.equal(C.movingFrame(data,5,99),null);
});
test('teaching RSI and MACD match the actual Python report over all 80 prefixes',()=>{
  const rows=C.bars(C.sampleCloses);
  const expected=JSON.parse(execFileSync('python3',['-c','import json,sys;from analysis import technical;rows=json.load(sys.stdin);print(json.dumps([technical(rows[:n]) for n in range(1,len(rows)+1)]))'],{input:JSON.stringify(rows),encoding:'utf8'}));
  const points=C.sample();
  for(let i=0;i<points.length;i++)for(const [key,digits] of [['ma5',4],['ma10',4],['ma20',4],['rsi14',2],['macd_dif',4],['macd_dea',4],['macd_hist',4],['volume_ratio5',2]]){
    const actual=points[i][key],want=expected[i][key];
    if(want===null)assert.equal(actual,null,`${i}:${key}`);else near(actual,want,10**(-digits)/2+1e-9);
  }
});
test('guide shows the actual sample RSI and doubled MACD histogram',()=>{
  const p=C.sample().at(-1);near(p.macd_hist,2*(p.macd_dif-p.macd_dea));
  assert.ok(C.terms.find(t=>t.id==='rsi').example().includes(p.rsi14.toFixed(2)));
  assert.ok(C.terms.find(t=>t.id==='macd').example().includes(p.macd_hist.toFixed(4)));
});
test('guide preserves app flat-RSI and minimum sample conventions',()=>{
  const p=sandbox.window.PriceTechnical.compute(C.bars(Array(60).fill(20)));
  assert.equal(p[13].rsi14,null);assert.equal(p[14].rsi14,50);
  assert.equal(p[58].macd_hist,null);assert.equal(p[59].macd_hist,0);
});

const datedBars=closes=>C.bars(closes).map((b,i)=>({...b,date:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10)}));
const payload=(rows,extra={})=>({thscode:'000811.SZ',end:rows.at(-1).date,cycle:'day',adjust:'forward',items:rows,previous_close:9,...extra});
test('real candles and daily returns use actual OHLC and adjacent dates',()=>{
  const rows=datedBars([10,11,9.9]),s=C.prepareMarket(payload(rows),'000811.SZ',rows.at(-1).date);
  const frame=C.marketFrame(s,2);
  assert.equal(frame.item.date,'2026-01-03');assert.equal(frame.previousDate,'2026-01-02');
  assert.equal(frame.candle.close,9.9);near(frame.change,-10);near(frame.total,-1);
});
test('real MA uses matching history context and reports hidden window members',()=>{
  const rows=datedBars(Array.from({length:30},(_,i)=>10+i));
  const s=C.prepareMarket(payload(rows.slice(20),{context_items:rows}),'000811.SZ',rows.at(-1).date);
  const f=C.marketFrame(s,0,20);assert.equal(f.window.length,20);assert.equal(f.window[0].date,rows[1].date);
  assert.equal(f.ma,20.5);assert.equal(f.previousDate,rows[19].date);assert.equal(f.previous,29);
});
test('visible missing candle overrides a good context candle; never bridges a gap',()=>{
  const rows=datedBars(Array(30).fill(20)),items=rows.slice(20).map(b=>({...b}));items[2].close_price=null;
  const s=C.prepareMarket(payload(items,{context_items:rows}),'000811.SZ',rows.at(-1).date);
  assert.equal(C.marketFrame(s,2).candle.valid,false);assert.equal(C.marketFrame(s,3).change,null);
  assert.equal(C.marketFrame(s,6,5).ma,null);assert.equal(C.marketFrame(s,7,5).ma,20);
  assert.equal(C.marketFrame(s,3).missingCount,1);assert.equal(C.marketFrame(s,3).total,0);
});
test('first visible day with missing prior context cannot use a stale scalar previous close',()=>{
  const rows=datedBars(Array(10).fill(20));rows[4].close_price=null;
  const s=C.prepareMarket(payload(rows.slice(5),{context_items:rows,previous_close:18}),'000811.SZ',rows.at(-1).date);
  assert.equal(C.marketFrame(s,0).previous,null);assert.equal(C.marketFrame(s,0).change,null);
});
test('when no history is supplied, only explicit upstream previous_close may seed first-day change',()=>{
  const rows=datedBars([10]);
  const s=C.prepareMarket(payload(rows,{previous_close:8}),'000811.SZ',rows[0].date);near(C.marketFrame(s,0).change,25);
  const absent=C.prepareMarket(payload(rows,{previous_close:null}),'000811.SZ',rows[0].date);assert.equal(C.marketFrame(absent,0).change,null);
});
test('invalid or mismatched real data fails closed instead of silently becoming a synthetic demo',()=>{
  const rows=datedBars([10,11]),p=payload(rows);
  for(const patch of [{thscode:'600487.SH'},{end:'2026-01-01'},{adjust:'none'},{cycle:'week'},{items:[]},{items:[rows[0],rows[0]]},{items:[{...rows[0],date:'2026-02-30'}]}])assert.throws(()=>C.prepareMarket({...p,...patch},'000811.SZ',p.end));
  assert.throws(()=>C.prepareMarket(p,'000811.SZ','bad'));
});
test('real data is sorted, bounded by cutoff and does not mutate upstream responses',()=>{
  const rows=datedBars([10,11,12]),p=payload([rows[2],rows[0],rows[1]],{end:rows[1].date}),before=plain(p);
  const s=C.prepareMarket(p,'000811.SZ',rows[1].date);
  assert.deepEqual(plain(s.items.map(b=>b.date)),['2026-01-01','2026-01-02']);assert.deepEqual(plain(p),before);
});
test('future price edits cannot affect a real historical frame',()=>{
  const rows=datedBars(Array.from({length:60},(_,i)=>20+i*.1)),p=payload(rows);
  const before=plain(C.marketFrame(C.prepareMarket(p,'000811.SZ',p.end),25,20));
  rows[50]={...rows[50],open_price:500,close_price:500,high_price:501,low_price:499};
  const after=plain(C.marketFrame(C.prepareMarket(payload(rows),'000811.SZ',p.end),25,20));
  assert.deepEqual(after,before);
});
test('zero prices, absent baseline and index boundaries remain unavailable',()=>{
  const rows=datedBars([null,10,11]),s=C.prepareMarket(payload(rows),'000811.SZ',rows.at(-1).date);
  assert.equal(C.marketFrame(s,1).change,null);assert.equal(C.marketFrame(s,2).total,null);
  assert.equal(C.marketFrame(s,-1),null);assert.equal(C.marketFrame(s,3),null);assert.equal(C.marketFrame(s,1,7),null);
});
test('RSI reading uses point changes and reference zones without treating them as probabilities',()=>{
  assert.equal(C.indicatorReading('rsi',{rsi14:70},{rsi14:60}).delta,10);
  assert.match(C.indicatorReading('rsi',{rsi14:70}).zone,/较高/);
  assert.match(C.indicatorReading('rsi',{rsi14:30}).zone,/较低/);
  assert.match(C.indicatorReading('rsi',{rsi14:50}).zone,/中间/);
  assert.equal(C.indicatorReading('rsi',{rsi14:0}).available,true);
  assert.equal(C.indicatorReading('rsi',{rsi14:100}).available,true);
  assert.equal(C.indicatorReading('rsi',{rsi14:50},null).delta,null);
});
test('MACD distinguishes sign, length and zero crossings rather than daily price direction',()=>{
  const p=hist=>({macd_dif:hist/2,macd_dea:0,macd_hist:hist});
  assert.match(C.indicatorReading('macd',p(.2),p(.4)).movement,/正柱.*缩短/);
  assert.match(C.indicatorReading('macd',p(-.2),p(-.4)).movement,/负柱.*缩短/);
  assert.match(C.indicatorReading('macd',p(-.4),p(-.2)).movement,/变长/);
  assert.match(C.indicatorReading('macd',p(.2),p(-.1)).movement,/由负转正/);
  assert.match(C.indicatorReading('macd',p(-.2),p(.1)).movement,/由正转负/);
  assert.match(C.indicatorReading('macd',p(0),p(.1)).movement,/重合/);
  assert.match(C.indicatorReading('macd',p(.1),p(0)).movement,/从零/);
  assert.match(C.indicatorReading('macd',p(.1)).movement,/缺少前一交易日/);
  assert.match(C.indicatorReading('macd',p(.1)).message,/不是涨跌幅/);
});
test('indicator readings keep absent or invalid samples unavailable instead of inventing zeros',()=>{
  for(const v of [null,undefined,NaN,Infinity,'20'])assert.equal(C.indicatorReading('rsi',{rsi14:v}).available,false);
  for(const key of ['macd_dif','macd_dea','macd_hist'])for(const value of [null,NaN,Infinity])assert.equal(C.indicatorReading('macd',{macd_dif:0,macd_dea:0,macd_hist:0,[key]:value}).available,false);
  assert.equal(C.indicatorReading('macd',{macd_dif:0,macd_dea:0,macd_hist:0}).available,true);
});
test('real 250-bar context produces RSI and MACD matching Python at every visible date',()=>{
  const rows=datedBars(Array.from({length:250},(_,i)=>Number((15+i*.025+Math.sin(i*.43)*2).toFixed(2))));
  const p=payload(rows.slice(-60),{context_items:rows}),series=C.prepareMarket(p,'000811.SZ',p.end);
  const want=JSON.parse(execFileSync('python3',['-c','import json,sys;from analysis import technical;rows=json.load(sys.stdin);print(json.dumps([technical(rows[:i+1]) for i in range(len(rows)-60,len(rows))]))'],{input:JSON.stringify(rows),encoding:'utf8'}));
  for(let i=0;i<60;i++){
    const f=C.marketFrame(series,i);
    for(const [key,digits] of [['rsi14',2],['macd_dif',4],['macd_dea',4],['macd_hist',4]])near(f.point[key],want[i][key],10**(-digits)/2+1e-9);
    near(C.indicatorReading('rsi',f.point).value,f.point.rsi14);
    near(C.indicatorReading('macd',f.point).value,2*(f.point.macd_dif-f.point.macd_dea));
  }
});
test('RSI and MACD reset at a visible gap even when context contains a valid copy',()=>{
  const rows=datedBars(Array.from({length:250},(_,i)=>20+i*.01)),items=rows.slice(-100).map(b=>({...b}));items[10].close_price=null;
  const p=payload(items,{context_items:rows}),series=C.prepareMarket(p,'000811.SZ',p.end);
  assert.equal(C.indicatorReading('rsi',C.marketFrame(series,24).point).available,false);
  assert.equal(C.indicatorReading('rsi',C.marketFrame(series,25).point).available,true);
  assert.equal(C.indicatorReading('macd',C.marketFrame(series,69).point).available,false);
  assert.equal(C.indicatorReading('macd',C.marketFrame(series,70).point).available,true);
});
