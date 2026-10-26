"""Read-only HiThink client and dashboard calculations (Python standard library)."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from research import themes, promotions

ROOT = Path(__file__).resolve().parent
TZ = dt.timezone(dt.timedelta(hours=8))
BASE = 'https://fuyao.aicubes.cn/api/a-share/'


class DataError(Exception):
    def __init__(self, message, *, reason=None):
        super().__init__(message)
        self.reason = reason


def today():
    return dt.datetime.now(TZ).date().isoformat()


def load_key():
    key = os.environ.get('HITHINK_FINANCE_API_KEY', '').strip()
    path = ROOT / '.env.local'
    if not key and path.exists():
        for line in path.read_text().splitlines():
            if line.strip().startswith('HITHINK_FINANCE_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('\"\'')
    if not key:
        raise DataError('请先打开左侧「设置」，填写同花顺 API Key。')
    return key


def board_counts(items):
    counts = [0] * 5
    unknown = 0
    for item in items:
        value = item.get('continue_day_cnt')
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            counts[min(value, 5) - 1] += 1
        else:
            unknown += 1
    return counts, unknown


def align_ranks(days, items):
    ranks = {i.get('date'): i.get('rank') for i in items}
    return [{'date': day, 'rank': ranks.get(day) if isinstance(ranks.get(day), int)
             and not isinstance(ranks.get(day), bool) and ranks[day] > 0 else None}
            for day in days]


class Market:
    def __init__(self, cache_dir=None):
        self.cache_dir = Path(cache_dir or ROOT / 'data' / 'cache')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.archive_lock = threading.RLock()
        self.archive_dir = self.cache_dir / "daily"
        self.archive_dir.mkdir(exist_ok=True)

    def get(self, endpoint, params=None, ttl=60):
        params = params or {}
        root = 'https://fuyao.aicubes.cn/api/' if endpoint.startswith(('meta/', 'a-share-index/')) else BASE
        url = root + endpoint + '?' + urllib.parse.urlencode(sorted(params.items()))
        path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        with self.lock:
            if path.exists():
                try:
                    saved = json.loads(path.read_text())
                    if time.time() - saved['saved_at'] < ttl:
                        return saved['data']
                except (ValueError, KeyError, OSError):
                    pass
            req = urllib.request.Request(url, headers={'X-api-key': load_key()})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=20) as response:
                        result = json.load(response)
                    code = result.get('code')
                    if code in (4001, 5001, 5002, 5003) and attempt < 2:
                        time.sleep(0.5 * 2 ** attempt)
                        continue
                    if code != 0:
                        meanings = {2001: '未认证', 2003: 'Key 无效或无权限', 3002: '数据尚未准备', 4001: '请求受限，请稍后再试'}
                        raise DataError(f"同花顺接口：{meanings.get(code, '请求失败')}（code={code}）")
                    data = result.get('data')
                    if not isinstance(data, dict) or not isinstance(data.get('abilities' if endpoint == 'financials/indicators' else 'item'), list):
                        raise DataError('上游数据结构异常，请稍后重试。')
                    tmp = path.with_suffix('.tmp')
                    tmp.write_text(json.dumps({'saved_at': time.time(), 'data': data}, ensure_ascii=False))
                    tmp.chmod(0o600)
                    tmp.replace(path)
                    time.sleep(0.12)
                    return data
                except (urllib.error.URLError, TimeoutError, OSError):
                    if attempt == 2:
                        raise DataError('无法连接同花顺服务，请检查网络后重试。') from None
                    time.sleep(0.5 * 2 ** attempt)
                except (ValueError, AttributeError):
                    raise DataError('同花顺返回了无法解析的数据。') from None

    def calendar(self):
        data = self.get('calendar/trading-days', ttl=600)
        dates = sorted({dt.datetime.strptime(i['date'], '%Y%m%d').date().isoformat()
                        for i in data['item']})
        return [d for d in dates if d <= today()]

    def window(self, end, days):
        dates = self.calendar()
        if end not in dates:
            raise DataError('请选择交易日历中的日期。')
        return [d for d in dates if d <= end][-days:]

    def daily(self, day, kind, loader, force=False):
        parsed = dt.date.fromisoformat(day)
        if parsed.isoformat() != day or day > today():
            raise DataError('日期无效。')
        path = self.archive_dir / f'{day}-{kind}.json'
        with self.archive_lock:
            saved = None
            try:
                saved = json.loads(path.read_text())
                if saved.get('version') != 1 or not isinstance(saved['items'], list):
                    saved = None
            except (OSError, ValueError, KeyError):
                pass
            if saved and not force:
                fetched = dt.datetime.fromtimestamp(saved['saved_at'], TZ).date().isoformat()
                age = (dt.date.fromisoformat(today()) - parsed).days
                # A snapshot obtained during the trading day must be checked again later.
                ttl = 60 if age == 0 else 21600
                if (age > 7 and fetched > day) or time.time() - saved['saved_at'] < ttl:
                    return saved['items']
            # Once archived, refresh all pages from upstream as one complete snapshot.
            items = loader(force or saved is not None)
            record = {'version': 1, 'date': day, 'kind': kind,
                      'saved_at': time.time(), 'items': items}
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(record, ensure_ascii=False))
            tmp.chmod(0o600)
            tmp.replace(path)
            return items

    def pool(self, day, kind='up', force=False):
        if kind not in ('up', 'down', 'break'):
            raise DataError('股票池类型无效。')
        return self.daily(day, kind, lambda fresh: self.fetch_pool(day, kind, fresh), force)

    def fetch_pool(self, day, kind='up', fresh=False):
        if kind not in ('up', 'down', 'break'):
            raise DataError('股票池类型无效。')
        date_ms = int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), TZ).timestamp() * 1000)
        items = []
        seen = set()
        expected = None
        for page in range(1, 101):
            data = self.get(f'special-data/limit-{kind}-pool', {'date_ms': date_ms, 'page': page, 'size': 200},
                            ttl=0 if fresh else (60 if day == today() else 21600))
            pagination = data.get('pagination', {})
            total = pagination.get('total')
            if not isinstance(total, int) or total < 0:
                raise DataError('涨停池缺少有效分页信息。')
            if expected is not None and expected != total:
                raise DataError('涨停池分页期间发生变化，请稍后刷新。')
            expected = total
            for item in data['item']:
                code = item.get('thscode')
                if not code or code in seen:
                    raise DataError('涨停池出现重复或无效股票，暂不统计。')
                seen.add(code)
                items.append(item)
            if len(items) == total:
                return items
            if not data['item'] or len(items) > total:
                break
        raise DataError('涨停池分页不完整，暂不统计。')

    def counts(self, end, days):
        rows = []
        stocks = None
        for day in self.window(end, days):
            try:
                items = self.pool(day)
                counts, unknown = board_counts(items)
                if day == end:
                    stocks = items
                rows.append({'date': day, 'counts': counts, 'total': len(items), 'unknown': unknown,
                             'error': None})
            except DataError as e:
                rows.append({'date': day, 'counts': None, 'total': None, 'unknown': None, 'error': str(e)})
        return {'items': rows, 'stocks': stocks, 'as_of': dt.datetime.now(TZ).isoformat(), 'provisional': end == today() and dt.datetime.now(TZ).hour < 16}

    def hot(self, day, force=False):
        self.window(day, 1)
        def load(fresh):
            data = self.get('special-data/hot-stock-list-history', {'date': day},
                            ttl=0 if fresh else (60 if day == today() else 21600))
            if data.get('date') != day:
                raise DataError('上游热榜日期与请求日期不一致。')
            rows = data['item']
            codes = [row.get('thscode') for row in rows]
            ranks = [row.get('rank') for row in rows]
            if (not rows or any(not c for c in codes) or len(set(codes)) != len(codes)
                    or any(not isinstance(r, int) or r < 1 for r in ranks)
                    or len(set(ranks)) != len(ranks)):
                raise DataError('热榜为空或记录不完整，未归档。')
            return sorted(rows, key=lambda i: i['rank'])
        return {'date': day, 'items': self.daily(day, 'hot', load, force)}

    def sync_day(self, day):
        self.window(day, 1)
        results = {}
        for kind in ('up', 'down', 'break', 'hot'):
            try:
                rows = self.hot(day, force=True)['items'] if kind == 'hot' else self.pool(day, kind, force=True)
                results[kind] = {'ok': True, 'count': len(rows)}
            except DataError as e:
                results[kind] = {'ok': False, 'error': str(e)}
        return {'date': day, 'results': results}

    def trend(self, code, end, days):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
            raise DataError('股票代码格式无效。')
        dates = self.window(end, days)
        data = self.get('special-data/hot-stock-rank-trend',
                        {'thscode': code, 'start_date': dates[0], 'end_date': dates[-1]},
                        ttl=60 if end == today() else 21600)
        return {'thscode': code, 'items': align_ranks(dates, data['item'])}

    def prices(self, code, end, days=60, start_date=None, *, include_context=False):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
            raise DataError('股票代码格式无效。')
        if days not in (20, 60, 120, 250):
            raise DataError('日 K 区间支持 20、60、120、250 个交易日。')
        dates = self.window(end, days + 1)
        if start_date:
            dt.date.fromisoformat(start_date)
            if start_date > end:
                raise DataError('开始日期不能晚于结束日期。')
            calendar = self.calendar()
            selected = [d for d in calendar if start_date <= d <= end]
            if not selected or len(selected) > 250:
                raise DataError('自选区间须包含 1 至 250 个可用交易日。')
            previous = [d for d in calendar if d < selected[0]][-1:]
            dates = previous + selected
        else:
            selected = dates[-days:]
        context_dates = self.window(end, 250) if include_context else []
        request_start = min(dates[0], context_dates[0]) if context_dates else dates[0]
        start = dt.datetime.combine(dt.date.fromisoformat(request_start), dt.time(), TZ)
        stop = dt.datetime.combine(dt.date.fromisoformat(end), dt.time(23, 59, 59), TZ)
        data = self.get('prices/historical', {'thscode': code, 'interval': '1d',
                        'start': int(start.timestamp() * 1000), 'end': int(stop.timestamp() * 1000),
                        'adjust': 'forward'}, ttl=60 if end == today() else 21600)
        by_date = {dt.datetime.fromtimestamp(i['date_ms'] / 1000, TZ).date().isoformat(): i
                   for i in data['item']}
        def rows_for(days):
            return [{'date': d, **{k: by_date.get(d, {}).get(k) for k in
                    ('open_price', 'high_price', 'low_price', 'close_price', 'volume')}} for d in days]
        result = {'thscode': code, 'items': rows_for(selected), 'adjust': 'forward', 'end': end,
                  'previous_close': by_date.get(dates[0], {}).get('close_price') if dates[0] < selected[0] else None}
        if include_context:
            result['context_items'] = rows_for(context_dates)
        return result

    def candles(self, code, end, cycle='day', periods=60, start_date=None, *, include_context=False):
        if cycle == 'day':
            result = self.prices(code, end, periods, start_date, **({'include_context': True} if include_context else {}))
            return {**result, 'cycle': 'day'}
        allowed = {'week': (4, 12, 26, 52), 'month': (3, 6, 12)}
        if cycle not in allowed or periods not in allowed[cycle]:
            raise DataError('不支持该 K 线周期或查看范围。')
        daily = self.prices(code, end, 250)
        groups = {}
        for row in daily['items']:
            date = dt.date.fromisoformat(row['date'])
            key = (date - dt.timedelta(days=date.weekday())).isoformat() if cycle == 'week' else row['date'][:7]
            groups.setdefault(key, []).append(row)
        bars = []
        for key, rows in groups.items():
            good = [r for r in rows if all(isinstance(r.get(k), (int, float)) for k in
                    ('open_price', 'high_price', 'low_price', 'close_price'))]
            bar = {'date': rows[-1]['date'], 'start_date': rows[0]['date'], 'missing_days': len(rows)-len(good)}
            if good:
                bar.update(open_price=good[0]['open_price'], high_price=max(r['high_price'] for r in good),
                           low_price=min(r['low_price'] for r in good), close_price=good[-1]['close_price'],
                           volume=sum(r['volume'] for r in good) if all(isinstance(r.get('volume'), (int, float)) for r in good) else None)
            else:
                bar.update({k: None for k in ('open_price', 'high_price', 'low_price', 'close_price', 'volume')})
            bars.append(bar)
        previous = bars[-periods-1].get('close_price') if len(bars) > periods else None
        return {**daily, 'items': bars[-periods:], 'cycle': cycle, 'previous_close': previous,
                'aggregation': '按自然周/月汇总已有日 K；缺失日不补值，首末周期可能不完整。',
                'available_periods': min(len(bars), periods)}

    def search(self, q):
        if not q or len(q) > 40:
            raise DataError('请输入 1 至 40 个字符的股票名称或代码。')
        data = self.get('meta/tickers/search', {'q': q, 'limit': 20}, ttl=3600)
        return {'items': [s for s in data['item'] if s.get('asset_type') == 'a-share']}

    def research(self, day):
        dates = self.window(day, 2)
        previous = dates[-2] if len(dates) > 1 else None
        pools, errors = {}, {}
        for date in dates:
            for kind in ('up', 'down', 'break'):
                key = date + ':' + kind
                try:
                    pools[key] = self.pool(date, kind)
                except DataError as e:
                    pools[key] = None
                    errors[key] = str(e)
        def summary(date):
            up, down, broken = (pools.get(date + ':' + k) for k in ('up', 'down', 'break'))
            # One symbol counts only once in the touched-limit denominator.
            touched = {s['thscode'] for s in (up or []) + (broken or [])}
            return {'up': len(up) if up is not None else None,
                    'down': len(down) if down is not None else None,
                    'broken': len(broken) if broken is not None else None,
                    'break_rate': len(broken)/len(touched)*100 if up is not None and broken is not None and touched else None,
                    'height': max((s.get('continue_day_cnt') or 0 for s in up), default=0) if up is not None else None}
        up = pools[day + ':up']
        old = pools.get(str(previous) + ':up')
        today_themes = themes(up) if up is not None else None
        prior_groups = {g['name']: g['count'] for g in themes(old)} if old is not None else None
        if today_themes is not None:
            for group in today_themes:
                group['delta'] = group['count'] - prior_groups.get(group['name'], 0) if prior_groups is not None else None
        return {'date': day, 'previous_date': previous, 'summary': summary(day),
                'previous': summary(previous) if previous else None,
                'themes': today_themes, 'promotions': promotions(old, up) if old is not None and up is not None else None,
                'pools': {k: pools[day + ':' + k] for k in ('up', 'down', 'break')},
                'errors': errors, 'provisional': day == today() and dt.datetime.now(TZ).hour < 16}

    def review(self, code, observed, end):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code):
            raise DataError('股票代码格式无效。')
        dates = self.calendar()
        if observed not in dates or end not in dates:
            raise DataError('观察日或回看日不在可用交易日历内。')
        following = next((d for d in dates if d > observed), None)
        if not following or following > end:
            return {'status': '等待下一交易日', 'next_date': following}
        start = dt.datetime.combine(dt.date.fromisoformat(observed), dt.time(), TZ)
        stop = dt.datetime.combine(dt.date.fromisoformat(following), dt.time(23, 59, 59), TZ)
        data = self.get('prices/historical', {'thscode': code, 'interval': '1d', 'adjust': 'forward',
                        'start': int(start.timestamp()*1000), 'end': int(stop.timestamp()*1000)},
                        ttl=60 if following == today() else 21600)
        rows = {dt.datetime.fromtimestamp(i['date_ms']/1000, TZ).date().isoformat(): i for i in data['item']}
        baseline = rows.get(observed, {}).get('close_price')
        close = rows.get(following, {}).get('close_price')
        change = (close/baseline-1)*100 if isinstance(baseline, (float, int)) and baseline > 0 and isinstance(close, (float, int)) else None
        return {'status': '有数据' if change is not None else '缺少日 K（可能停牌或尚未就绪）',
                'next_date': following, 'baseline': baseline, 'close': close, 'change': change,
                'provisional': following == today() and dt.datetime.now(TZ).hour < 16}
