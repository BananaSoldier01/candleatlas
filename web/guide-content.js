'use strict';
// Original teaching content and synthetic examples; no third-party runtime or copied assets.
(() => {
  const checked='2026-10-24';
  const sources={
    app:{title:'观市本版计算与展示口径',note:'按本应用的日 K、技术画像、报告对比与披露版本规则核对。'},
    basic:{title:'深交所投教 · K 线基础',url:'https://investor.szse.cn/index/update/t20190613_567791.html',note:'基础定义参考；旧文中的交易规则不作为本版依据。'},
    sse:{title:'上交所 · 交易规则（2026 年修订）',url:'https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml',note:'2026-07-06 施行；需连同暂缓实施条文阅读，范围为上交所。'},
    szse:{title:'深交所 · 交易规则（2026 年修订）',url:'https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf',note:'范围为深交所；交易前再核对所属板块与当日公告。'},
    finance:{title:'上交所投教 · 财务与估值基础',url:'https://edu.sse.com.cn/attention/c/10607961/files/e6cc8a42c360489ab441306b48028843.pdf',note:'只参考定义；低估值倍数不等于便宜或值得买入。'},
    statistics:{title:'上交所 · 市值与换手率统计口径',url:'https://www.sse.com.cn/aboutus/publication/monthly/explain/',note:'市值、股数和换手率分母须分别核对；交易所统计的总股本口径不等于流通股换手率。'},
    stock:{title:'Stock Lab · 股票与公司基础',url:'https://github.com/artinte/stock-lab/blob/c3c0f6d0db841a3c1ace73413cf0c9ae800bede5/docs/document/stock_basic/stock_company.html',note:'MIT；已核对基础定义，本页使用独立撰写的说明和算例。'},
    valuation:{title:'FinanceToolkit · 估值公式参考',url:'https://github.com/JerBouma/FinanceToolkit/blob/fd2e313e8c287ac907900ff20af586330ccd9564/financetoolkit/ratios/valuation_model.py',note:'MIT；已核对公式。算例在本应用内独立重算，未引入代码。'},
    rsi:{title:'Stock Indicators · RSI 定义与预热说明',url:'https://python.stockindicators.dev/indicators/Rsi/',note:'Apache-2.0；仅作概念参考，预热长度与零涨跌处理以观市为准。'},
    macd:{title:'Stock Indicators · MACD 定义与预热说明',url:'https://python.stockindicators.dev/indicators/Macd/',note:'Apache-2.0；外部柱值口径不同，观市柱值为 2 × (DIF − DEA)。'},
    returns:{title:'Datawhale · 日收益率交互教学参考',url:'https://github.com/datawhalechina/quant-for-beginners/blob/db779f5cdcea7ccaeb2185676f858d89436e79d0/assets/interactive/daily-return-demo.html',note:'MIT；借鉴单步代入的教学方式，文字、数据、图形与代码独立编写。'},
    ma:{title:'TradingView · 移动平均线示例参考',url:'https://github.com/tradingview/lightweight-charts/blob/c9ec1cec25583a0200f3c85ad9019d19c1d65f97/website/tutorials/demos/moving-average.js',note:'Apache-2.0；只参考交互思路，未使用库、代码或素材；起算位置按观市重算。'},
    chan:{title:'chan.py · 结构算法说明',url:'https://github.com/Vespa314/chan.py/tree/429d6ed3043e27c93a003ba2b10e70a05575e1f5',note:'固定为观市所用提交，MIT；具体结构与候选状态以当前配置及回放结果为准。'}
  };
  const groups=[['first','第一次看股票'],['chart','看懂图表'],['indicator','常用指标'],['chan','缠论观察'],['company','公司与公告'],['trade','交易与规则']];
  const bars=closes=>closes.map((c,i)=>({date:'示例第'+(i+1)+'日',open_price:c,close_price:c,high_price:c===null?null:c+.5,low_price:c===null?null:c-.5,volume:100+i*2}));
  const sampleCloses=Array.from({length:80},(_,i)=>Number((20+i*.055+Math.sin(i*.57)*1.2).toFixed(2)));
  const sample=()=>window.PriceTechnical.compute(bars(sampleCloses));
  const valid=n=>Number.isFinite(n)&&n>0;
  function priceReturn(previous,current){return valid(previous)&&valid(current)?(current/previous-1)*100:null;}
  function candle(values){
    const {open,high,low,close,previous}=values;
    if(![open,high,low,close].every(valid)||high<Math.max(open,close)||low>Math.min(open,close)||high<low)return {valid:false};
    return {valid:true,open,high,low,close,kind:close===open?'十字 K':close>open?'阳线':'阴线',color:close>=open?'#c65148':'#257555',change:priceReturn(previous,close),body:Math.abs(close-open),upper:high-Math.max(open,close),lower:Math.min(open,close)-low};
  }
  function movingFrame(closes,period,index){
    if(![5,10,20].includes(period)||!Number.isInteger(index)||index<0||index>=closes.length)return null;
    const points=window.PriceTechnical.compute(bars(closes));
    const value=points[index]['ma'+period],start=index-period+1;
    const windowIndices=value===null?[]:Array.from({length:period},(_,i)=>start+i);
    return {points,value,index,period,windowIndices,sum:value===null?null:windowIndices.reduce((s,i)=>s+closes[i],0),leaving:index>=period&&points[index-1]['ma'+period]!==null?index-period:null,entering:index};
  }
  function calendarDate(value){
    return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  }
  function prepareMarket(payload,code,end){
    if(!calendarDate(end)||payload?.thscode!==code||payload?.end!==end||payload?.adjust!=='forward'||payload?.cycle!=='day')throw Error('行情股票、截止日或复权口径不匹配，请重新读取。');
    const normalize=rows=>{
      if(!Array.isArray(rows))throw Error('行情数据格式不完整。');
      const seen=new Set();
      return rows.map(row=>{
        if(!row||!calendarDate(row.date)||seen.has(row.date))throw Error('行情日期无效或重复，请重新读取。');
        seen.add(row.date);return {...row};
      }).filter(row=>row.date<=end).sort((a,b)=>a.date.localeCompare(b.date));
    };
    const items=normalize(payload.items);
    if(!items.length)throw Error('截至所选日期没有可用行情区间。');
    const history=normalize(payload.context_items||[]).filter(row=>row.date<items[0].date);
    const all=[...history,...items],points=window.PriceTechnical.compute(all);
    return {items,all,points,offset:history.length,previousClose:valid(payload.previous_close)?payload.previous_close:null};
  }
  function marketFrame(series,index,period=5){
    if(!Number.isInteger(index)||index<0||index>=series.items.length||![5,10,20].includes(period))return null;
    const position=series.offset+index,item=series.items[index],point=series.points[position];
    const previous=position>0?series.points[position-1].close:series.previousClose;
    const current=point.close,baseline=series.points[series.offset].close;
    const window=point['ma'+period]===null?[]:series.all.slice(position-period+1,position+1);
    return {index,item,point,previous,previousDate:position>0?series.all[position-1].date:null,
      candle:candle({open:item.open_price,high:item.high_price,low:item.low_price,close:current,previous}),
      current,change:priceReturn(previous,current),total:priceReturn(baseline,current),baseline,baselineDate:series.items[0].date,
      missingCount:series.points.slice(series.offset,position+1).filter(p=>p.close===null).length,
      window,ma:point['ma'+period],sum:window.length?window.reduce((sum,b)=>sum+b.close_price,0):null,
      leaving:position>=period&&series.points[position-1]['ma'+period]!==null?series.all[position-period]:null};
  }
  function indicatorReading(type,point,previous=null){
    if(type==='rsi'){
      const value=point?.rsi14;
      if(!Number.isFinite(value))return {available:false,message:'连续有效日 K 不足 15 根，RSI14 暂不可计算；缺失不补零。'};
      const delta=Number.isFinite(previous?.rsi14)?value-previous.rsi14:null;
      const zone=value>=70?'较高参考区（≥70）':value<=30?'较低参考区（≤30）':'中间参考区（30～70）';
      return {available:true,value,delta,zone,message:'RSI 比较近段上涨与下跌的平均力度；高低参考区不表示下一日的涨跌方向。'};
    }
    if(type!=='macd'||!['macd_dif','macd_dea','macd_hist'].every(k=>Number.isFinite(point?.[k])))return {available:false,message:'连续有效日 K 不足 60 根，MACD 暂不可计算；缺失后重新累计。'};
    const value=point.macd_hist,old=previous?.macd_hist;
    const sign=value>0?'正柱（红色）':value<0?'负柱（绿色）':'零柱';
    let movement='缺少前一交易日的有效柱值，暂不比较变化。';
    if(Number.isFinite(old)){
      if(value===0)movement='当前 DIF 与 DEA 重合，柱值为 0。';
      else if(old===0)movement='柱值从零变为'+(value>0?'正':'负')+'。';
      else if(value*old<0)movement=value>0?'柱值由负转正：DIF 从 DEA 下方转到上方。':'柱值由正转负：DIF 从 DEA 上方转到下方。';
      else movement=sign+'较前一交易日'+(Math.abs(value)>Math.abs(old)?'变长':Math.abs(value)<Math.abs(old)?'缩短':'长度不变')+'，表示两线距离'+(Math.abs(value)>Math.abs(old)?'扩大':Math.abs(value)<Math.abs(old)?'缩小':'不变')+'。';
    }
    return {available:true,value,dif:point.macd_dif,dea:point.macd_dea,sign,movement,message:'柱值不是涨跌幅。红绿表示 DIF 与 DEA 的相对位置，不能当作当天股价涨跌或买卖指令。'};
  }
  const fixed=(n,d=2)=>Number.isFinite(n)?n.toFixed(d):'—';
  const terms=[
    {id:'stock',group:'first',title:'股票与指数',aliases:'股份 上证 深成 北证 指数',intro:'股票代表一家公司的股份，指数把一组证券的变化汇成一个数。',body:['买股票意味着承担这家公司的经营与价格风险。指数按编制规则选样、加权，方便观察一组证券的整体表现。','指数上涨时，也可能有很多成分股下跌；上证指数与某一只股票的价格不是同一种单位。'],example:'示例：两家公司分别涨 2%、跌 2%，只有在权重相同且忽略其他因素时，这组价格变化才近似相抵。',mistake:'指数涨了，不代表自选股都该涨；不同指数的点数不能直接比较贵便宜。',where:'市场总览看整体，个股研究看一家公司。',target:'market',sources:['stock','statistics']},
    {id:'code',group:'first',title:'股票代码与市场',aliases:'代码 SH SZ BJ 沪 深 京 板块 A股',intro:'代码和市场后缀一起，才是本应用识别一只股票的完整身份。',body:['观市使用六位代码加 .SH、.SZ 或 .BJ，分别标识上海、深圳和北京市场。所属板块、风险警示和上市阶段也会影响交易规则。','名称可能变更或相近，查资料时优先核对完整代码，不凭简称合并公司。'],example:'示例：600584.SH 是一个完整标识；截图清单去重按代码，不按价格或简称。',mistake:'同是 A 股，不代表申报数量、涨跌幅限制与盘后安排完全相同。',where:'我的工作台与个股研究均显示名称和完整代码。',target:'stocks',sources:['app','sse','szse']},
    {id:'return',group:'first',title:'价格与涨跌幅',aliases:'收益率 涨幅 跌幅 change1 百分比 前收',intro:'涨跌幅回答“比前一个有效收盘价变化了百分之几”。',body:['计算式是（本次收盘 ÷ 前次收盘 − 1）× 100%。观市技术报告的 change1 使用连续有效尾部的两根日收盘。','先核对复权口径和日期；除权日的行情参考价可能有调整，页面不同来源的涨跌幅不一定与技术报告完全相同。'],example:'示例：10 元到 11 元是 +10%；随后回到 9.90 元是 −10%，相对最初 10 元仍为 −1%。',mistake:'上涨和下跌的百分比不能直接相加；缺少前值时不能写成 0%。',where:'个股研究的行情摘要；已保存报告的技术指标。',target:'stocks',lab:'return',sources:['app','returns'],selfCheck:'写明涨跌幅的两个价格各是哪一个交易日的收盘、是否前复权，以及行情来源与年份。前值缺失或两个页面口径不同，就写「未查到」，不要把缺失算成 0%，也不要把几天的百分比直接相加。这里只核对变化怎么计算。'},
    {id:'cap',group:'first',title:'市值',aliases:'总市值 流通市值 股本',intro:'市值把每股价格与相应股数相乘，描述市场给这部分股份的总价。',body:['总市值与流通市值的股数范围不同。比较时还要注意币种、股本时点，以及不同类别股份的定价口径。','观市的日 K 价格本身不能推算完整市值；缺少股本及口径时，不用价格高低替代公司规模。'],example:'示例：每股 10 元、同口径股数 1 亿股，市值为 10 亿元。它不是公司账上现金。',mistake:'每股 5 元的公司，不一定比每股 50 元的公司小或便宜。',where:'个股行情与资料中核对字段；缺少股本时不自行补算。',target:'stocks',sources:['statistics']},
    {id:'cycle',group:'chart',title:'分时、日 K 与周月 K',aliases:'周期 分钟 周线 月线',intro:'周期决定一根线或一根蜡烛汇总多长时间的行情。',body:['分时是日内采样价格；日 K 汇总一天。观市周 K、月 K 由同一批前复权日 K 汇总：首个开盘、期间最高最低、最后收盘，成交量相加。','本周或本月可能还没结束，查询窗口首尾也可能不完整；缺失日不会被补成有成交。新浪分钟行情与日 K 来源及复权不同，不混拼成一条价格序列。'],example:'示例：一周的日内最高价出现在周二，周 K 的上影线就由这个高点决定，不是把每日最高取平均。',mistake:'正在形成的周 K 不是已经定稿的完整一周。',where:'个股研究上方的周期与范围工具条。',target:'stocks',sources:['app','basic']},
    {id:'ohlc',group:'chart',title:'开、高、低、收（OHLC）',aliases:'开盘 收盘 最高 最低 K线 蜡烛',intro:'一根 K 线用四个价格，浓缩这一段时间的成交范围。',body:['O 是开盘，H 是最高，L 是最低，C 是收盘。实体连接开盘和收盘，影线伸向最高和最低。','最高不能低于开盘、收盘；最低不能高于开盘、收盘。错误行情应显示缺失，不画成正常蜡烛。'],example:'示例：开 10、高 12、低 9、收 11；实体在 10～11，上影到 12，下影到 9。',mistake:'只靠这四个数，无法知道日内先到最高还是先到最低。',where:'个股研究的 K 线；悬停或聚焦单根读取四价。',target:'stocks',lab:'candle',sources:['basic','app']},
    {id:'wick',group:'chart',title:'实体与影线',aliases:'上影 下影 长影线',intro:'实体表示开收差，影线表示价格曾走到、但没停在的范围。',body:['上影长度 = 最高 − max(开盘, 收盘)；下影长度 = min(开盘, 收盘) − 最低。两者都不能为负数。','长影线说明区间内出现过偏离，不单独说明下一根会反转。需要结合量、位置和后续数据观察。'],example:'示例：开 10、高 12、低 9、收 11，实体、上影、下影各长 1 元。',mistake:'长下影不保证止跌，长上影也不保证继续下跌。',where:'K 线图每根蜡烛；本指南 OHLC 图解可调整四价。',target:'stocks',lab:'candle',sources:['basic','app']},
    {id:'candle-color',group:'chart',title:'阳线、阴线与十字 K',aliases:'红 绿 颜色 涨跌 十字星',intro:'K 线颜色比较开盘与收盘；当天涨跌幅比较前收与本次收盘。',body:['观市收盘高于开盘画红色阳线，低于开盘画绿色阴线；开收相等是十字 K，当前绘图也用红色，同时保留文字和数值。','颜色只编码这一种比较。MACD 柱红绿比较柱值与零轴，不是同一个判断。'],example:'示例：前收 10、今日开 12 收 11，画绿色阴线，但相对前收仍涨 10%。试试下方“阴线但上涨”。',mistake:'一根绿色 K 线不一定表示相对昨日下跌。',where:'个股研究的 K 线和图例。',target:'stocks',lab:'candle',sources:['basic','app']},
    {id:'volume',group:'chart',title:'成交量与成交额',aliases:'量柱 股 手 元 放量',intro:'成交量数交易了多少股，成交额数这些成交花了多少金额。',body:['股与手是不同计量单位，金额也要核对元、万元、亿元。观市日 K 的原始成交量口径为股，图表会换算显示；其他来源以各自标注为准。','同一次买卖撮合不是把买方和卖方重复算两笔。量大只能说明活跃，不能单独说明净流入或后续方向。'],example:'示例：100 股以 10 元成交，成交量 100 股，成交额 1,000 元；分多种价格成交时按各笔金额相加。',mistake:'放量上涨和放量下跌含义不同；量柱不是资金净流入。',where:'K 线下方量柱，配合当天收盘和“放量”菱形看。',target:'stocks',sources:['app','sse']},
    {id:'adjust',group:'chart',title:'前复权与除权',aliases:'分红 送股 拆股 复权价',intro:'复权把分红送转等造成的价格断点调整到可比较的尺度。',body:['观市日 K、MA、RSI 和 MACD 使用同一查询窗口的前复权价格。它适合观察连续变化，不是历史上真正下单的成交价。','新的权益事件或数据修订可能改变历史复权值。跨来源、跨取数时点比较要重新核对，不能把不复权分钟价接进前复权日 K。'],example:'示例：发生送转后股数增加、每股价格相应调整，价格变低不能直接当成公司价值同幅蒸发。',mistake:'前复权涨跌幅不是已计入所有分红、费用的真实账户收益。',where:'个股研究的来源与复权说明；报告的计算口径。',target:'stocks',sources:['app','basic'],selfCheck:'自查复权时，记下代码、复权类型（前复权或其他）和取数日期，并写明权益事件的来源与年份。只比较同一复权口径下的价格。查不到该年的分红送转或复权说明，就写「未查到」，不要凭记忆补事件，也不要把不复权价格接进前复权序列。这里只核对口径。'},
    {id:'cursor',group:'chart',title:'坐标与十字线',aliases:'鼠标 横轴 纵轴 悬停 数值',intro:'横轴告诉你是哪一天，纵轴告诉你鼠标所在的价格或指标刻度。',body:['观市十字线把鼠标横坐标对齐到对应 K 线，并显示纵轴刻度；下方文字另列当天实际开高低收与指标值。','鼠标放在某个高度，不代表当天成交过这个精确价格。移到 RSI 或 MACD 子图，纵轴单位也随之改变。'],example:'示例：鼠标纵轴指向 11.20 元，但当天收盘是 11.00 元，这两个数描述的是不同对象。',mistake:'光标刻度不是收盘价，也不是委托成交回报。',where:'个股研究的日 K、量柱和 RSI / MACD 子图。',target:'stocks',sources:['app']},
    {id:'missing',group:'chart',title:'缺失行情与样本不足',aliases:'空值 断点 连续 预热 停牌',intro:'没有数据和数值等于零，是两回事。',body:['观市不把缺失价格补为零，也不跨无效日 K 接均线。图上 OHLC 无效会重置指标；技术报告只从末尾取连续有效收盘，两个入口校验范围不同。','MA20 要 20 根连续收盘；RSI14 首值要 15 根；MACD 显示至少要 60 根。满足最小长度也不表示初始化影响已消失。缺日原因需另查，不能直接认定停牌。'],example:'示例：4 根有效日 K 后有断点，下一根仍不能给出 MA5；必须从断点后重新凑满 5 根。',mistake:'空白不是 0，也不是“没有风险”；不同窗口下 RSI / MACD 可能有差别。',where:'图注、技术报告 sample / 覆盖度与报告对比。',target:'stocks',sources:['app'],selfCheck:'先写明缺失的是哪一个代码、哪一个交易日、哪一个字段。再到行情源或交易所公告核对这一天是否停牌，并记下来源与年份。空白只表示没有记录。原因查不到就写「未查到」，不要把空写成 0，也不要用前后收盘填历史日。'},
    {id:'ma',group:'indicator',title:'MA · 移动平均线',aliases:'均线 MA5 MA10 MA20 均价 滚动',intro:'把最近几根收盘价取平均，观察价格变化的大方向。',body:['观市 MA5 / MA10 / MA20 分别用最近 5 / 10 / 20 根连续有效日收盘，包含当天这一根。它是收盘价的算术平均，不是日内成交均价。','窗口每天向前滚动：最早的一根退出，新的一根进入。上穿20日线比较前收与前日 MA20、当收与当日 MA20；仅触及均线不算穿越。'],example:'示例：10、11、12、13、14 的 MA5 = 12；下一天收 20，窗口变成 11、12、13、14、20，MA5 = 14。',mistake:'均线会滞后；上穿不是买入指令。第 5 根就能出现 MA5，不要多等一根。',where:'个股研究日 K 上的金色 MA5、蓝色 MA10、紫色 MA20。',target:'stocks',lab:'ma',sources:['app','ma'],glyphs:[['line','ma5','MA5'],['line','ma10','MA10'],['line','ma20','MA20']]},
    {id:'rsi',group:'indicator',title:'RSI · 涨跌力度',aliases:'RSI14 超买 超卖 Wilder',intro:'RSI 把最近上涨和下跌的力度，压缩到 0～100 的范围。',body:['观市采用 RSI14：先用 14 次收盘变动的涨、跌幅均值初始化，再用 Wilder 平滑；至少 15 根连续收盘。全平时为 50，只有涨、没有跌时为 100。','图上的 30 / 70 是阅读参考线，不是必买必卖界限。改变历史窗口会改变平滑初值，因此报告对比会提示窗口敏感。'],example:()=>`合成示例：80 根收盘由 20 + 0.055×i + 1.2×sin(0.57×i) 四舍五入到分生成（i 从 0 起）；第80根收盘 ${fixed(sampleCloses.at(-1))}，观市重算 RSI14 = ${fixed(sample().at(-1).rsi14)}。`,mistake:'RSI 高不代表下一刻必跌；RSI 50 也不是上涨概率 50%。',where:'个股研究日 K 下方的紫色 RSI14 子图。',target:'stocks',lab:'rsi',sources:['app','rsi'],glyphs:[['line','rsi','RSI14'],['dashed','reference','30 / 70 参考线']]},
    {id:'macd',group:'indicator',title:'MACD · 动量变化',aliases:'DIF DEA EMA 金叉 死叉 柱值',intro:'两条平滑线及它们的差，帮助观察价格变化的快慢。',body:['观市参数是 12 / 26 / 9；DIF = EMA12 − EMA26，DEA 平滑 DIF，柱值 = 2 × (DIF − DEA)。至少 60 根连续有效收盘才显示；EMA 从窗口首价初始化，DEA 从 0 起算。','金色线是 DIF，蓝色线是 DEA；红柱为正、绿柱为负。柱变短表示两条线距离缩小，不等于当天股价一定下跌。'],example:()=>{const p=sample().at(-1);return `合成示例：与 RSI 词条相同的 80 根收盘，DIF ${fixed(p.macd_dif,4)}，DEA ${fixed(p.macd_dea,4)}，柱值 ${fixed(p.macd_hist,4)}；按未舍入值先计算再展示。`;},mistake:'外部软件可能用 1 倍柱值或不同初始化；不要直接比较未经核对的数值。',where:'个股研究日 K 下方 MACD 子图与已保存技术报告。',target:'stocks',lab:'macd',sources:['app','macd'],glyphs:[['line','dif','DIF'],['line','dea','DEA'],['bar','positive','正柱'],['bar','negative','负柱']]},
    {id:'volume-ratio',group:'indicator',title:'成交量 / 前5日均量',aliases:'量比 volume_ratio5 放量 缩量',intro:'把本日成交量与前五个有效日的平均量相比。',body:['观市先算前 5 日成交量的平均数，再用本日量去除；需要含本日在内的 6 根连续有效行情，量非负且均量大于零。','达到 1.5 倍显示“放量”菱形。这个数不按日内经过时间修正，盘中与收盘不能无条件类比，也不是常见盘口“量比”。'],example:'示例：前五日各 100 万股，今日 150 万股，结果 1.50 倍；今日量不参与分母。',mistake:'量放大不自动加分；技术画像会结合当天涨跌方向。',where:'K 线的菱形标记、技术报告的量能协同分项。',target:'stocks',sources:['app'],glyphs:[['diamond','volume','放量 ≥ 1.5 倍']]},
    {id:'turnover',group:'indicator',title:'换手率',aliases:'流通股 换手 活跃度',intro:'换手率把成交量与相应可交易股数相比，衡量交易活跃程度。',body:['通常按成交股数 ÷ 对应流通股数 × 100%，但自由流通、流通 A 股等口径可能不同，须看上游字段定义和股本日期；交易所统计另有总股本等口径。','同一股份可以被不同投资者反复交易，因此换手率不是“有多少独立股东买过”，更不代表价格方向。观市缺少同口径股本时不从量柱反推。'],example:'示例：一天成交 200 万股，对应流通股数 1 亿股，按这个口径换手率为 2%。',mistake:'高换手不保证上涨；不同流通股本口径的数值不宜直接比较。',where:'行情快照若提供换手率，先读字段与时间说明；不等同于量比。',target:'stocks',sources:['app','statistics']},
    {id:'assessment',group:'indicator',title:'技术画像与覆盖度',aliases:'评分 趋势 动量 量能 过热 assessment coverage',intro:'技术画像把几类价格现象分开描述，并说明有多少依据可用。',body:['观市区分趋势、动量、量能协同与过热。过热描述偏离程度，不是把所有上涨都加成好分；分数来自固定规则，不能当作收益率或胜率。','缺项会保留 missing / partial 与覆盖度，不能把部分依据的分数和完整分数直接排名。规则覆盖按可用权重计算，不是简单数规则条数；总分也不替代逐项解释。'],example:'假设示例：某项规则计划权重合计 100，可用规则权重只有 50，则规则覆盖为 50%；这说的是材料完整度，不是看涨概率。',mistake:'评分高不保证赚钱；旧报告没有画像时不应凭空补一个完整分数。',where:'个股分析 → 已保存报告 → 技术画像。',target:'stocks',sources:['app'],selfCheck:'打开技术画像时，逐项抄下指标名称、连续有效样本数、规则版本和观察日，并注明这些数字的来源是本机哪一份报告（含生成日期或年份）。某项没有样本就保持缺失，写「未查到」，不要补成完整分数。分项描述的是已算出的形态，不是上涨概率。'},
    {id:'compare',group:'indicator',title:'报告对比与可比性',aliases:'delta 同日版本 limited incomparable 基线',intro:'先判断两份报告是否同口径，再解释指标差异。',body:['首次分析没有旧基线；同日可比较上一版本；历史基线不从未来取。不同计算方法等情况标不可比，不能强行给出增强或减弱方向。','窗口不同会标有限可比；RSI / MACD 等受初始化影响的指标抑制方向颜色。即使同一天，修订数据和窗口也可能带来差异。'],example:'示例：80 根与 250 根窗口的 MACD 数值不同，先看“窗口敏感”，不能直接当作动量刚刚增强。',mistake:'数值变了不一定是行情变了；首次分析不是“指标全部没有变化”。',where:'个股分析 → 报告中的“与上一份对比”。',target:'stocks',sources:['app'],selfCheck:'并排写下两份报告的观察日、窗口长度、复权方式和计算方法，注明每份口径的来源与年份（或生成日）。窗口或方法不一致就标不可比，不要把差值说成方向变化。某一侧窗口或生成日查不到，写「未查到」，不要借用另一份的数字。'},
    {id:'fractal',group:'chan',title:'缠论 · 分型',aliases:'顶分型 底分型 包含关系',intro:'分型用一小组相邻 K 线，描述局部高低转折的候选形状。',body:['算法会先按配置处理包含关系，再判断顶、底形态。它不是简单取肉眼看到的三根原始 K 线最高或最低。','右侧行情尚未出现时，左边的转折可能还无法确认；回看图上的转折日不等于当时就能识别。'],example:'示意：处理后的三根 K 线，中间高低范围都高于两侧，可形成顶分型；实际仍取决于配置和后续结构。',mistake:'局部顶底不是未来最高最低，更不是价格必反转。',where:'个股研究 → 开启缠论结构；先读“图中的线和方框”。',target:'stocks',sources:['app','chan']},
    {id:'bi',group:'chan',title:'缠论 · 笔',aliases:'蓝线 笔连接 顶底',intro:'笔把满足规则的相邻顶、底结构连接起来。',body:['观市用蓝色线段表示笔，端点来自结构算法。它是价格结构的连线，和按收盘平均得到的 MA 均线不是一回事。','实线表示算法当前已确认的结构；虚线是尚在形成的尾部。确认是结构状态，不是交易执行建议。'],example:'示意：一个已确认底到后续满足条件的顶可以连成向上笔；不是每两根涨跌 K 线都能成笔。',mistake:'不要把笔的斜率理解为平均收益率或预测路径。',where:'日 K 上蓝色笔线，默认需手动开启缠论结构。',target:'stocks',sources:['app','chan'],glyphs:[['line','bi','笔 · 已确认'],['dashed','bi','笔 · 形成中']]},
    {id:'segment',group:'chan',title:'缠论 · 线段',aliases:'紫线 段 级别',intro:'线段把若干笔组织成更高一层的价格结构。',body:['观市用紫色、稍粗的线表示线段。划分取决于笔和线段规则，不能按屏幕上任意三个小拐点拼接。','随着新笔出现，尾部未确认线段可能延伸或重组；看历史回放时要区分最后确认与当前临时状态。'],example:'示意：蓝色笔多次摆动后，紫色线概括一段较大方向；层级不同，所以端点不必一一对应。',mistake:'线段不是更长周期的 MA，也不等于每固定天数划一段。',where:'日 K 上的紫色线；图例区分笔与线段。',target:'stocks',sources:['app','chan'],glyphs:[['line','seg','线段'],['dashed','seg','形成中']]},
    {id:'center',group:'chan',title:'缠论 · 中枢方框',aliases:'中枢 重叠 区域 橙色 方框',intro:'浅橙色方框标出算法识别的结构价格重叠区。',body:['上下边对应价格区间，左右边对应该结构的起止时间；方框的宽和高表示不同单位。需要按当前算法层级及规则理解。','它不等同于市场认可的支撑阻力承诺，价格可以穿过、离开或形成新的重叠区域。'],example:'示意：若相关摆动的共同价格重叠在 10～12 元，框的下边是 10、上边是 12；左右边由结构时间决定。',mistake:'方框不是推荐买入区，也不是保证跌不破的底线。',where:'日 K 的浅橙色中枢框；“图中的线和方框”有完整示意。',target:'stocks',sources:['app','chan'],glyphs:[['box','zs','中枢 · 价格重叠区']]},
    {id:'confirmation',group:'chan',title:'结构确认与候选首次可见',aliases:'1类 1p 2 2s 3a 3b 买卖点 未确认 first_seen 回放',intro:'转折发生的日期，与算法最早看得到它的日期，可能相隔很多天。',body:['观市默认关闭候选观察，开启后仍标“未确认”。当前固定默认参数观察 1 / 1p / 2 / 2s / 3a / 3b；六类已有合成样本与逐日前缀一致性核验，这不代表实盘有效性或交易确认。','首次可见日来自逐日前缀回放，不能拿完整未来行情倒填。confirmation=unknown 保留未知性质；结构实线也不等于候选已经成为交易信号。'],example:'示意：转折在第 10 日，直到第 15 日才首次识别，那么在第 12 日的历史观察中不能显示为已知。',mistake:'回看时画在转折处的标记，不表示可以在那天事前成交。',where:'个股研究 → 缠论候选观察（默认关闭）；标识保持“未确认”。',target:'stocks',sources:['app'],glyphs:[['circle','candidate','候选 · 未确认'],['dashed','seg','形成中结构']]},
    {id:'statements',group:'company',title:'财报：收入、利润与现金流',aliases:'营收 净利润 经营现金流 年报 季报',intro:'收入看做了多少生意，利润看会计结果，现金流看钱何时进出。',body:['赊销可能先确认收入、稍后收款；折旧等项目也使利润不等于现金。结合资产负债表、利润表、现金流量表和附注阅读，关注同口径可比期间。','年报、半年报、季报覆盖区间不同，合并口径与归属于母公司股东口径也不同。观市披露面板提供材料与版本核验，不自动把 PDF 全文抽成已核实财务指标。'],example:'示例：本期销售 100 万元、只收回 60 万元，收入和回款就可能不同；不能仅据这两个数推算净利润。',mistake:'营收增长不保证利润增长；净利润为正不保证经营现金流为正。',where:'个股分析 → 披露资料，核对报告期、原文和版本。',target:'stocks',sources:['finance','app']},
    {id:'valuation',group:'company',title:'PE / PB · 估值倍数',aliases:'市盈率 市净率 TTM EPS 净资产',intro:'PE 比价格与盈利，PB 比价格与净资产，先看分母属于哪一期。',body:['PE = 每股价格 ÷ 同口径每股收益；PB = 每股价格 ÷ 同口径每股净资产。静态、TTM、预测盈利不同，不能混为一列；还要注意币种、股本变化及归属口径。','每股盈利或净资产非正时，倍数可能失去常见解释意义，应单独标注。观市没有从资料全文自动生成完整估值筛选器。'],example:'示例：价格 20 元、每股收益 2 元，则 PE 为 10 倍；每股净资产 5 元，则 PB 为 4 倍。均假设日期与股本口径一致。',mistake:'倍数低不自动说明便宜；一次性收益和行业差异都会影响比较。',where:'阅读公司原文或上游估值字段时核对；本版指南只演示公式。',target:'stocks',sources:['finance','valuation','app'],selfCheck:'本页只演示 PE 与 PB 的公式，观市不做估值筛选。自己验算时，分别写下价格、每股收益或每股净资产的来源、年份和报告期，并注明是静态、滚动还是预测口径。任一输入查不到就写「未查到」，不要用别处的盈利或净资产填分母。'},
    {id:'disclosure',group:'company',title:'披露时间与更正版本',aliases:'公告 available_at notice_date 报告期 asof 修订 更正 PIT',intro:'报告属于哪一期，与那天是否已经公开，是两条时间线。',body:['报告期末是业绩归属时间，公告日是披露日期，抓取时间是本机何时拿到材料。观市对只有公告日的资料，保守设为次日 00:00（北京时间）可见，不推定公告日盘前已公开。','筛选按股票＋报告期匹配，只用观察时点已可见且校验通过的版本；更正不能提前覆盖旧版。SHA256 能核对文件是否一致，不能证明财务内容真实。'],example:'示例：3 月 31 日结束的报告，4 月 20 日公告，保守到 4 月 21 日才纳入；5 月 10 日公告的更正不能出现在 4 月回看里。',mistake:'资料下载成功不等于历史时点可用；没有覆盖某股票时应显示缺失。',where:'个股分析 → 披露资料，查看原文、可用时间、哈希与版本。',target:'stocks',sources:['app'],selfCheck:'把报告期、公告日期和本机可见时间分成三列，写明材料来源与年份。回看某个观察日时，只用那时已经可见的版本。当时的原文或更正版本查不到，写「未查到」，不要用日后修订或记忆中的摘要顶上。'},
    {id:'order',group:'trade',title:'委托、成交与交易时段',aliases:'限价 市价 集合竞价 连续竞价 撤单 交易日',intro:'委托是向券商表达交易条件，成交还需要撮合及交易回报。',body:['限价买入限定最高接受价，限价卖出限定最低接受价；市价委托也受所属市场的可用类型及保护机制约束。集合竞价集中撮合，连续竞价持续匹配。','交易日、各阶段是否接受申报和撤单、是否有盘后安排，要按所属市场、板块与当日公告核对；不是打开软件就能成交。这里链接 2026 年修订的沪深规则，不用旧教材的统一时间表覆盖所有证券。'],example:'示例：愿以不高于 10 元买入，不代表一定有人卖，也不代表提交后已经成交；以成交回报为准。',mistake:'挂单成功不是成交成功；K 线价格不是保证可交易的报价。',where:'本应用用于观察和研究，不提供下单；真实交易请看券商与交易所回报。',target:'stocks',sources:['sse','szse']},
    {id:'fees',group:'trade',title:'费用与实际收益',aliases:'佣金 印花税 过户费 滑点 手续费',intro:'价格涨幅减去交易成本后，才接近账户的实际结果。',body:['成本可能包括佣金、相关税费、过户费及买卖价差；费率、收取方向和最低收费受市场、品种、政策及券商约定影响。请按成交日交割单核对，本页不写一套永久适用的费率。','实际执行还可能偏离看到的价格。观市后续表现是同口径价格变化，不包含真实成交、仓位、现金分红再投资和税费。'],example:'假设示例：10 元买 100 股，11 元全部卖出，价差盈利 100 元；若两端成本合计 8 元，则净额 92 元。8 元仅是演算假设。',mistake:'历史价格收益不等于扣费后的策略收益。',where:'我的工作台的后续表现；实际费用以你的券商交割单为准。',target:'watch',sources:['app','sse']},
    {id:'limits',group:'trade',title:'价格限制与停复牌',aliases:'涨停 跌停 新股 ST 风险警示 申报 价格笼子',intro:'价格约束与是否可交易，取决于市场、板块和当时状态。',body:['涨跌幅限制、有效申报范围和盘中临时停牌是不同机制。板块、新上市阶段、风险警示等可能适用不同安排，不能把常见比例套到所有股票。','停牌期间没有正常连续成交，不意味着价格变为零；历史数据缺失也不自动证明停牌。复牌、价格范围及撤单条件应核对交易所与公司公告。'],example:'示例：如果某证券当日有价格上限，挂在上限也可能因卖盘不足而买不到；“涨停”不是成交承诺。',mistake:'没有涨跌幅限制不表示可以随便申报任何价格；涨停也不保证次日上涨。',where:'连板跟踪与行情页只记录状态，交易条件看所属市场当日规则。',target:'boards',sources:['sse','szse'],selfCheck:'写明代码、交易日和板块，以及价格限制或停复牌状态的来源与年份（交易所规则或公司公告）。当日安排查不到就写「未查到」，不要套用其他板块的比例，也不要把停牌日价格写成 0。这里只记录约束和是否连续交易。'}
  ];
  function selfCheckHTML(term,escapeHTML){
    const raw=term&&term.selfCheck;
    const lines=Array.isArray(raw)?raw:(typeof raw==='string'?[raw]:[]);
    const escFn=typeof escapeHTML==='function'?escapeHTML:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const parts=lines.filter(line=>typeof line==='string'&&line.trim());
    if(!parts.length)return '';
    return `<div class="guide-self-check"><h4>如何自查</h4>${parts.map(line=>`<p>${escFn(line)}</p>`).join('')}</div>`;
  }
  function search(query,group='all'){
    const keys=String(query).trim().toLowerCase().split(/\s+/).filter(Boolean);
    return terms.filter(t=>(group==='all'||t.group===group)&&keys.every(q=>(t.title+' '+t.aliases+' '+t.intro).toLowerCase().includes(q)));
  }
  window.GuideContent={checked,sources,groups,terms,bars,sampleCloses,sample,priceReturn,candle,movingFrame,calendarDate,prepareMarket,marketFrame,indicatorReading,search,fixed,selfCheckHTML};
})();
