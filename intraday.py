"""Sina public minute bars. No credentials, no cross-provider price stitching."""
import datetime as dt
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from market import DataError, TZ


def parse_bars(text):
    try:
        raw = json.loads(text.split('=(', 1)[1].rsplit(');', 1)[0])
        if not isinstance(raw, list) or not raw:
            raise ValueError('empty')
        bars, seen = [], set()
        for row in raw:
            stamp = dt.datetime.strptime(row['day'], '%Y-%m-%d %H:%M:%S')
            date = stamp.strftime('%Y-%m-%d %H:%M')
            if date in seen:
                raise ValueError('duplicate')
            seen.add(date)
            values = {key: float(row[key]) for key in ('open', 'high', 'low', 'close', 'volume')}
            if not all(math.isfinite(v) for v in values.values()):
                raise ValueError('non-finite')
            if not (0 < values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']) or values['volume'] < 0:
                raise ValueError('invalid bar')
            bars.append({'time': date, **values})
        return sorted(bars, key=lambda r: r['time'])
    except (ValueError, TypeError, KeyError, IndexError) as e:
        raise DataError('新浪分钟行情为空或格式不完整，暂不显示。') from e


class Intraday:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def bars(self, code, interval):
        if not re.fullmatch(r'\d{6}\.(SH|SZ)', code):
            raise DataError('新浪分钟行情目前仅接入沪深 A 股。')
        if interval not in (1, 5, 15, 30, 60):
            raise DataError('分钟周期仅支持 1、5、15、30、60。')
        path = self.directory / f'{code}-{interval}.json'
        with self.lock:
            try:
                saved = json.loads(path.read_text())
                if time.time() - saved['fetched_at'] < 60:
                    return saved
            except (OSError, ValueError, KeyError):
                pass
            symbol = code[-2:].lower() + code[:6]
            params = urllib.parse.urlencode({'symbol': symbol, 'scale': interval, 'ma': 'no', 'datalen': 1970})
            url = 'https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData?' + params
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    rows = parse_bars(response.read().decode())
            except (OSError, TimeoutError) as e:
                raise DataError('新浪分钟行情暂时连接失败，请稍后刷新。') from e
            saved = {'fetched_at': time.time(), 'items': rows}
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(saved, ensure_ascii=False))
            tmp.chmod(0o600)
            tmp.replace(path)
            return saved

    def series(self, code, end, mode, interval, count, calendar):
        if mode not in ('intraday', 'five', 'minute') or end not in calendar:
            raise DataError('行情类型或观察日期无效。')
        if count not in (60, 120, 240):
            raise DataError('分钟 K 范围仅支持 60、120、240 根。')
        interval = interval if mode == 'minute' else 1
        saved = self.bars(code, interval)
        all_rows = saved['items']
        # Never use later data to replace a requested historical date.
        rows = [r for r in all_rows if r['time'][:10] <= end]
        dates = [d for d in calendar if d <= end][-(5 if mode == 'five' else 1):]
        selected = rows[-count:] if mode == 'minute' else [r for r in rows if r['time'][:10] in dates]
        if not selected:
            raise DataError(f"所选日期不在可用分钟历史内；当前覆盖 {all_rows[0]['time']} — {all_rows[-1]['time']}。")
        previous = [r for r in rows if r['time'][:10] < selected[0]['time'][:10] and r['time'][11:] == '15:00']
        available_dates = sorted({r['time'][:10] for r in selected})
        return {'source': '新浪财经', 'adjust': 'none', 'code': code, 'mode': mode,
                'interval': interval, 'items': selected, 'dates': dates,
                'missing_dates': [d for d in dates if d not in available_dates],
                'previous_close': previous[-1]['close'] if previous else None,
                'requested_end': end, 'last_time': selected[-1]['time'],
                'available_start': all_rows[0]['time'], 'available_end': all_rows[-1]['time'],
                'fetched_at': dt.datetime.fromtimestamp(saved['fetched_at'], TZ).isoformat()}
