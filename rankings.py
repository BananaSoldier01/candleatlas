"""Source rankings and complete-market sorting, with dated local snapshots."""
import datetime as dt
import json
import math
import threading
import time
from market import DataError, TZ


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def timestamp_day(value):
    if not finite(value): return None
    try: return dt.datetime.fromtimestamp(value/1000, TZ).date().isoformat()
    except (ValueError, OverflowError, OSError): return None


def sort_quotes(rows, kind):
    key = 'turnover' if kind == 'turnover' else 'price_change_ratio_pct'
    valid = [r for r in rows if finite(r.get(key)) and finite(r.get('last_price')) and r['last_price'] > 0
             and finite(r.get('volume')) and r['volume'] > 0]
    if kind == 'gainers': valid = [r for r in valid if r[key] > 0]
    if kind == 'losers': valid = [r for r in valid if r[key] < 0]
    valid.sort(key=lambda r: ((r[key] if kind == 'losers' else -r[key]), r['thscode']))
    return [{**r, 'rank': i+1} for i, r in enumerate(valid)]


class Rankings:
    def __init__(self, market):
        self.market = market
        self.directory = market.cache_dir / 'rankings'
        self.directory.mkdir(exist_ok=True)
        self.lock = threading.RLock()

    def read(self, name):
        try: return json.loads((self.directory / name).read_text())
        except (OSError, ValueError): return None

    def save(self, name, data):
        path = self.directory / name
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.chmod(0o600); tmp.replace(path)

    @staticmethod
    def validate_snapshot(data, day, source):
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            raise DataError(source+'行情快照格式无效，未用于所选观察日。', reason='invalid_snapshot')
        actual, stamp = data.get('source_date'), timestamp_day(data.get('timestamp'))
        first = timestamp_day(data['first_timestamp']) if 'first_timestamp' in data else stamp
        if actual != day or stamp != day or first != day:
            raise DataError(f'日期不符：观察日 {day}；{source}快照日期 {actual or "缺失"}，起止数据时间对应 {first or "缺失"}～{stamp or "缺失"}。未混入所选日期。', reason='date_mismatch')
        if not data['items']:
            raise DataError(source+'行情快照为空，无法判断所选日涨跌。', reason='upstream_empty' if source=='上游' else 'invalid_snapshot')
        return data

    def snapshot_for_day(self, day):
        dates = self.market.calendar()
        if day not in dates: raise DataError('请选择可用交易日。')
        with self.lock:
            saved = self.read(day+'-market.json')
            if saved is not None:
                data = self.validate_snapshot(saved, day, '本地')
                return {**data, 'snapshot_source':'local'}
            if day != dates[-1]:
                raise DataError(f'历史未采集：{day} 没有本地全市场行情快照；不使用其他日期替代。', reason='not_collected')
            data = self.validate_snapshot(self.market_snapshot(), day, '上游')
            return {**data, 'snapshot_source':'upstream'}

    def names(self):
        result = {}
        for offset in range(0, 100000, 1000):
            data = self.market.get('meta/tickers/list', {'asset_type':'a-share','limit':1000,'offset':offset}, ttl=86400)
            for row in data['item']: result[row['thscode']] = row.get('name') or row['thscode']
            if len(data['item']) < 1000: return result
        raise DataError('股票名称目录未读取完整。')

    def market_snapshot(self):
        cached = self.read('latest-market.json')
        if cached and time.time()-cached['fetched_at'] < 300: return cached
        rows, seen, stamps = [], set(), []
        expected = None
        for offset in range(0, 100000, 500):
            data = self.market.get('prices/snapshot', {'limit':500,'offset':offset}, ttl=0)
            if offset==0 and not data['item']:
                raise DataError('上游为空：未返回全市场行情，无法据此判断所选日涨跌。', reason='upstream_empty')
            total = data.get('total')
            if not isinstance(total, int) or total <= 0 or (expected is not None and total != expected):
                raise DataError('全市场分页数量异常，暂不生成行情榜。')
            expected = total
            for row in data['item']:
                code = row.get('thscode')
                if not code or code in seen: raise DataError('行情分页重复或代码缺失，暂不生成排行榜。')
                seen.add(code);rows.append(row)
            if finite(data.get('timestamp')): stamps.append(data['timestamp'])
            if offset+500 >= total: break
        else: raise DataError('行情分页未完成，未更新榜单。')
        if not rows: raise DataError('上游为空：未返回全市场行情，无法据此判断所选日涨跌。', reason='upstream_empty')
        if not stamps: raise DataError('全市场行情缺少有效数据时间，未归档。', reason='invalid_snapshot')
        dates = {dt.datetime.fromtimestamp(t/1000,TZ).date().isoformat() for t in stamps}
        if len(dates)!=1: raise DataError('行情分页跨越不同日期，暂不归档。')
        names = self.names()
        rows = [{**r, 'name':names.get(r['thscode'],r['thscode'])} for r in rows]
        result={'items':rows,'timestamp':max(stamps),'first_timestamp':min(stamps),'source_date':dates.pop(),
                'fetched_at':time.time(),'universe':expected,'received':len(rows)}
        self.save('latest-market.json',result)
        self.save(result['source_date']+'-market.json',result)
        return result

    def get(self, day, kind, period='day', offset=0, limit=10):
        if kind not in ('hot','rising','gainers','losers','turnover') or period not in ('day','hour'):
            raise DataError('榜单或周期无效。')
        if offset < 0 or limit not in (10,30,50): raise DataError('榜单分页参数无效。')
        calendar = self.market.calendar()
        if day not in calendar: raise DataError('请选择可用交易日。')
        current = day == calendar[-1]
        note=''
        with self.lock:
            if kind in ('hot','rising'):
                if not current and kind=='hot' and period=='day':
                    data={'items':self.market.hot(day)['items'],'source_date':day,'timestamp':None}
                    note='历史日榜；此接口不提供当时涨跌幅和热度变化。'
                elif not current:
                    data=self.read(f'{day}-{kind}-{period}.json')
                    if not data: raise DataError('该日期没有本地榜单记录，不能使用最新榜单替代历史。')
                    note='本地最近一次采集记录，不代表最终收盘榜。'
                else:
                    endpoint='hot-stock-list' if kind=='hot' else 'skyrocket-list'
                    data=self.market.get('special-data/'+endpoint, {'period':period}, ttl=60)
                    stamp=data.get('timestamp')
                    if not finite(stamp) or not data['item']: raise DataError('榜单时间或内容缺失。')
                    codes=[r.get('thscode') for r in data['item']]
                    if any(not c for c in codes) or len(set(codes))!=len(codes) or any(not isinstance(r.get('rank'),int) for r in data['item']):
                        raise DataError('榜单记录不完整。')
                    data={**data,'items':data['item'],'source_date':dt.datetime.fromtimestamp(stamp/1000,TZ).date().isoformat()}
                    self.save(f"{data['source_date']}-{kind}-{period}.json",data)
                    # Optional quote enrichment must not invalidate an otherwise valid source ranking.
                    try:
                        quote=self.market.get('prices/snapshot',{'thscodes':','.join(codes)},ttl=60)
                        quote_day=dt.datetime.fromtimestamp(quote['timestamp']/1000,TZ).date().isoformat() if finite(quote.get('timestamp')) else None
                        if quote_day==data['source_date']:
                            by_code={r['thscode']:r for r in quote['item']}
                            data={**data,'items':[{**by_code.get(r['thscode'],{}),**r} for r in data['item']], 'quote_timestamp':quote['timestamp']}
                        else: note='行情与热榜日期不同，未混入涨跌幅。'
                    except DataError: note='涨跌幅暂不可用，热度排名正常显示。'
                rows=sorted(data['items'],key=lambda r:r['rank'])
            else:
                data=self.snapshot_for_day(day)
                rows=sort_quotes(data['items'],kind)
                note=f"完整遍历 {data['universe']} 个代码，返回 {data['received']} 条行情；仅排序有效且有成交的股票。含 ST、新股及沪深京。分批快照，并非同一瞬间。"
                if data['snapshot_source']=='local': note='优先使用观察日 '+day+' 的本地快照。'+note
                if not current:note+=' 本地采集快照，不代表最终收盘榜。'
            if data['source_date']!=day: note=f"观察日 {day}；上游实际数据日期 {data['source_date']}。"+note
            return {'kind':kind,'period':period,'items':rows[offset:offset+limit],'total':len(rows),
                    'offset':offset,'limit':limit,'source':'同花顺','source_date':data['source_date'],
                    'timestamp':data.get('timestamp'),'quote_timestamp':data.get('quote_timestamp'),
                    'historical':not current,'note':note}

    def movers(self, day, direction='up', threshold=5, offset=0):
        if direction not in ('up','down') or not finite(threshold) or not 1 <= threshold <= 30 or offset < 0:
            raise DataError('异动筛选参数无效。')
        calendar=self.market.calendar()
        if day not in calendar:raise DataError('请选择可用交易日。')
        with self.lock:
            data=self.snapshot_for_day(day)
            rows=sort_quotes(data['items'],'gainers' if direction=='up' else 'losers')
            rows=[r for r in rows if abs(r['price_change_ratio_pct'])>=threshold]
            return {'items':rows[offset:offset+50],'total':len(rows),'offset':offset,'limit':50,'date':day,
                    'timestamp':data['timestamp'],'universe':data['universe'],'received':data['received'],
                    'snapshot_source':data['snapshot_source'],
                    'note':('优先使用观察日 '+day+' 的本地快照。' if data['snapshot_source']=='local' else '读取与观察日匹配的上游快照。')+'覆盖有效且有成交的沪深京股票，含 ST、新股；分批行情快照，不代表同时成交价格或最终收盘数据。'}

    def overview(self, day):
        dates = self.market.calendar()
        if day not in dates: raise DataError('请选择可用交易日。')
        data = self.snapshot_for_day(day)
        rows = [r for r in data['items'] if finite(r.get('last_price')) and r['last_price'] > 0 and finite(r.get('volume')) and r['volume'] > 0]
        values = [r['price_change_ratio_pct'] for r in rows if finite(r.get('price_change_ratio_pct'))]
        if not values: raise DataError('该快照没有有效涨跌样本，暂不展示市场广度。')
        # Use non-overlapping intervals, with ±5 included in the outside buckets.
        bins = [sum(v<=-5 for v in values),sum(-5<v<=-3 for v in values),sum(-3<v<0 for v in values),sum(v==0 for v in values),sum(0<v<3 for v in values),sum(3<=v<5 for v in values),sum(v>=5 for v in values)]
        turnovers = [r['turnover'] for r in rows if finite(r.get('turnover')) and r['turnover'] >= 0]
        leaders = sort_quotes(rows,'turnover')[:5]
        return {'date':day,'timestamp':data['timestamp'],'received':data['received'],'universe':data['universe'],
                'valid':len(values),'excluded':len(data['items'])-len(values),'up':sum(v>0 for v in values),'down':sum(v<0 for v in values),'flat':sum(v==0 for v in values),
                'turnover':sum(turnovers) if turnovers else None,'turnover_sample':len(turnovers),'traded':len(rows),'bins':bins,'leaders':leaders,
                'snapshot_source':data['snapshot_source'],
                'note':('优先使用观察日 '+day+' 的本地快照。' if data['snapshot_source']=='local' else '')+'同花顺沪深京分批行情快照，含 ST、新股；涨跌统计仅含有成交且价格、涨跌幅有效的股票。非同时行情或收盘定稿；成交额为有效样本合计。'}
