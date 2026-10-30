"""可选免 Key 日 K 备源。教学对照，不是同花顺主路径的自动回退。

只在调用方显式传入 source 时取数。Market.prices 不会改走这里。
默认 allow_network=False：未注入回调时不打开套接字、不登录、不改试别的来源。
两源失败只写本次路径和缺口，不静默切换，也不拼成一条序列。

来源与条款（许可待审，需维护者复核后再决定能否对外暴露）：
- 腾讯 fqkline：https://web.ifzq.gtimg.cn/appstock/app/fqkline/get ，参数 qfq 表示前复权。
  零 Key。标记 cn-public / 许可待审。本仓库不包含这些行情的再分发权。
- baostock：可选包（pip install baostock，未写入强制依赖）。日 K 使用
  query_history_k_data_plus，adjustflag=2 表示前复权（官方口径：1 后复权，2 前复权，3 不复权）。
  包与数据的许可待审，不随发行包再分发。

复权结果字段 adjust 为 forward。成交量沿用上游原值，不换算，缺失不补零。
不可与 HiThink 的 prices/historical 序列静默混用。

请求窗口是闭区间 [start, end]。行日期必须是真实公历日；不存在的日期（例如 2024-02-30）
和窗口外的日期写入 gaps，不进入 items。有效根数少于请求根数时，保留窗口内已经取到的缺口原因
（含首根有效日 K 之前）。只有有效根数多于请求、裁掉更早的日子时，才隐藏展示窗口之前的缺口。
compare_daily 要求两侧 thscode 存在且相同；成功结果带上左右代码。adjust 不同只记差异，不改价格。

腾讯 qfqday 列顺序（本模块按此映射，不读第 7 列及以后）：
0 date，1 open，2 close，3 high，4 low，5 volume。
分别写入 date / open_price / close_price / high_price / low_price / volume。
第 6 列当作成交量，不改记为成交额。响应里的 day / hfqday 不复用。
"""
import datetime as dt
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

from market import DataError

PHRASE_SUSPEND = '缺 K 可能因停牌。可能停牌（来源 baostock tradestatus）'
PHRASE_UNKNOWN = '缺日原因未取得，不能直接认定停牌'
PHRASE_NO_PACKAGE = '未安装可选依赖 baostock'
PHRASE_NO_NET_TENCENT = '未授权联网，未请求腾讯'
PHRASE_NO_NET_BAOSTOCK = '未授权联网，未登录、未请求 baostock'

TENCENT_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
TRIED_TENCENT = 'web.ifzq.gtimg.cn/appstock/app/fqkline/get（param 含 day 与 qfq）'
TRIED_BAOSTOCK_K = 'baostock.login + query_history_k_data_plus(frequency=d, adjustflag=2)'

_CODE = re.compile(r'\d{6}\.(SH|SZ|BJ)\Z')
_DAY = re.compile(r'\d{4}-\d{2}-\d{2}\Z')
_FIELDS = ('open_price', 'high_price', 'low_price', 'close_price', 'volume')
_BASE_NOTES = (
    '备源日 K，不是同花顺主路径；不可与 HiThink 序列静默混用，也不可跨源拼成一条。',
    '复权口径为前复权。腾讯参数 qfq；baostock adjustflag=2。',
    '成交量沿用上游原值，未换算。缺失不补零。',
)


def _calendar_day(value):
    """Return YYYY-MM-DD when value is a real calendar date, else None."""
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        return None
    try:
        day = dt.date.fromisoformat(value)
    except ValueError:
        return None
    if day.isoformat() != value:
        return None
    return value


def parse_day(value, label='日期'):
    day = _calendar_day(value)
    if day is None:
        raise DataError(f'{label}无效。')
    return day


def load_baostock(loader=None):
    """Return the baostock module, or None when the optional import fails."""
    if loader is not None:
        try:
            return loader()
        except ImportError:
            return None
    try:
        import baostock
    except ImportError:
        return None
    return baostock


def fetch_daily(code, end, days=60, *, source, allow_network=False, fetch_bytes=None,
                baostock_query=None, baostock_loader=None):
    """显式日 K。source 只能是 tencent 或 baostock，不会互相回退。

    注入 fetch_bytes(url)->bytes 或 baostock_query(symbol, start, end, adjustflag)
    时，库不再自己打开套接字或登录。未注入且 allow_network 为 False 时只返回缺口。
    """
    if source not in ('tencent', 'baostock'):
        raise DataError('备源只接受 tencent 或 baostock，不会自动选择。')
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise DataError('股票代码格式无效。')
    end = parse_day(end, '结束日期')
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 250:
        raise DataError('备源日 K 区间支持 1 至 250 根。')
    if code.endswith('.BJ'):
        reason = ('baostock 不覆盖北交所代码，未登录、未请求。'
                  if source == 'baostock' else '腾讯 fqkline 备源未接入北交所，未请求。')
        return _pack(source, code, [], [{'date': None, 'reason': reason}], _notes(source))
    start = _window_start(end, days)
    if source == 'tencent':
        return _finalize(source, code, start, end, days, *_tencent(code, start, end, days, allow_network, fetch_bytes))
    return _finalize(source, code, start, end, days, *_baostock_k(
        code, start, end, allow_network, baostock_query, baostock_loader))


def compare_daily(left, right):
    """并列两份已经取回的日 K。不合并 items，不补缺，不改任何一侧的价格。

    两侧 thscode 必须存在且相同，否则拒绝。adjust 保持各侧原样，不统一口径。
    """
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise DataError('对比需要两份备源结果。')
    left_code = _require_thscode(left, '左侧')
    right_code = _require_thscode(right, '右侧')
    if left_code != right_code:
        raise DataError(f'两侧 thscode 不同（{left_code} 与 {right_code}），不能并列对比。')
    left_map = _item_map(left.get('items'))
    right_map = _item_map(right.get('items'))
    diffs = []
    for day in sorted(set(left_map) & set(right_map)):
        for field in _FIELDS:
            if left_map[day].get(field) != right_map[day].get(field):
                diffs.append({'date': day, 'field': field, 'left': left_map[day].get(field),
                              'right': right_map[day].get(field)})
    return {
        'left_source': left.get('source'), 'right_source': right.get('source'),
        'left_thscode': left_code, 'right_thscode': right_code,
        'left_adjust': left.get('adjust'), 'right_adjust': right.get('adjust'),
        'only_left': sorted(set(left_map) - set(right_map)),
        'only_right': sorted(set(right_map) - set(left_map)),
        'value_diffs': diffs, 'merged': False,
        'notes': ['并列差异，未把两源拼成一条序列。', 'adjust 与 source 保持各侧原样，不统一口径。'],
    }


def _require_thscode(result, side):
    code = result.get('thscode')
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise DataError(f'{side}缺少可核对的 thscode，不能并列对比。')
    return code


def _item_map(items):
    if not isinstance(items, list):
        raise DataError('备源结果缺少 items。')
    found = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('date'), str):
            raise DataError('备源 items 无法并列。')
        found[item['date']] = item
    return found


def _notes(source):
    extra = ('腾讯 fqkline 列顺序按 date,open,close,high,low,volume 映射；不用 day/hfqday。'
             if source == 'tencent' else
             '停牌只在 baostock tradestatus 不等于 1 时写成可能停牌；没有该信号时不能直接认定停牌。')
    return [*_BASE_NOTES, extra]


def _window_start(end, days):
    span = min(days * 2 + 20, 640)
    return (dt.date.fromisoformat(end) - dt.timedelta(days=span)).isoformat()


def _pack(source, code, items, gaps, notes):
    return {'source': source, 'adjust': 'forward', 'thscode': code, 'items': items,
            'gaps': gaps, 'notes': list(notes)}


def _range_gap(date, start, end):
    return {'date': date,
            'reason': f'日期 {date} 超出请求区间 {start} 至 {end}，已剔除，不作为有效日 K。'}


def _invalid_date_gap(value):
    shown = value if isinstance(value, str) and _DAY.fullmatch(value) else None
    return {'date': shown, 'reason': f'不合格行已剔除，不补零。日期无效。{PHRASE_UNKNOWN}。'}


def _finalize(source, code, start, end, days, items, gaps, notes):
    # 查询窗口是闭区间 [start, end]。请求根数只在有效日 K 超额时裁掉更早的日子。
    # 根数不足或刚好够时，保留窗口内已经取得的缺口，包括首根有效日 K 之前的原因。
    kept, seen = [], set()
    for item in sorted(items, key=lambda row: row['date']):
        if item['date'] < start or item['date'] > end:
            gaps.append(_range_gap(item['date'], start, end))
            continue
        if item['date'] in seen:
            gaps.append({'date': item['date'], 'reason': '重复日期已剔除，未合并。'})
            continue
        seen.add(item['date'])
        kept.append(item)
    trimmed = False
    if len(kept) > days:
        kept = kept[-days:]
        trimmed = True
    display_start = kept[0]['date'] if kept else None
    visible = []
    for gap in gaps:
        gdate = gap.get('date')
        real = _calendar_day(gdate) if isinstance(gdate, str) else None
        if real and (real < start or real > end) and '超出请求区间' not in (gap.get('reason') or ''):
            gap = _range_gap(real, start, end)
            real = gap['date']
        if trimmed and real and display_start and real < display_start:
            continue
        visible.append(gap)
    if len(kept) < days:
        if any(PHRASE_SUSPEND in gap['reason'] for gap in visible):
            reason = f'有效日 K 为 {len(kept)} 根，少于请求的 {days} 根。除已标明 tradestatus 的日期外，{PHRASE_UNKNOWN}。'
        else:
            reason = f'有效日 K 为 {len(kept)} 根，少于请求的 {days} 根。{PHRASE_UNKNOWN}。'
        visible.append({'date': None, 'reason': reason})
    if not kept:
        notes = [*notes, '未取到序列时 adjust 表示请求的前复权口径，不表示已经核对到前复权数据。']
    return _pack(source, code, kept, visible, notes)


def _num(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('empty')
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        number = float(value.strip())
    else:
        raise ValueError('empty')
    if not math.isfinite(number):
        raise ValueError('non-finite')
    if number.is_integer() and abs(number) < 2**53:
        return int(number)
    return number


def _bar_ok(open_price, high_price, low_price, close_price, volume):
    if min(open_price, high_price, low_price, close_price) <= 0 or volume < 0:
        return False
    return low_price <= min(open_price, close_price) and max(open_price, close_price) <= high_price


def _bar(date, open_price, high_price, low_price, close_price, volume):
    return {'date': date, 'open_price': open_price, 'high_price': high_price,
            'low_price': low_price, 'close_price': close_price, 'volume': volume}


def _tencent(code, start, end, days, allow_network, fetch_bytes):
    notes = _notes('tencent')
    if fetch_bytes is None and not allow_network:
        return [], [{'date': None, 'reason': PHRASE_NO_NET_TENCENT}], notes
    number, market = code.split('.')
    symbol = {'SH': 'sh', 'SZ': 'sz'}[market] + number
    count = min(640, (days * 2 + 20) + days)
    param = f'{symbol},day,{start},{end},{count},qfq'
    url = TENCENT_URL + '?' + urllib.parse.urlencode({'param': param})
    fetch = fetch_bytes or _fetch_tencent
    try:
        raw = fetch(url)
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError('not-bytes')
        payload = json.loads(bytes(raw).decode())
    except (OSError, TimeoutError, urllib.error.URLError, UnicodeError, ValueError, json.JSONDecodeError):
        return [], [{'date': None, 'reason': f'腾讯 fqkline 请求或解析失败。试过路径：{TRIED_TENCENT}。未改走其他源。{PHRASE_UNKNOWN}。'}], notes
    return _tencent_rows(payload, symbol, notes)


def _fetch_tencent(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'CandleAtlas/backup-kline'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read()


def _tencent_rows(payload, symbol, notes):
    if not isinstance(payload, dict):
        return [], [{'date': None, 'reason': f'腾讯 fqkline 结构异常。试过路径：{TRIED_TENCENT}。未改走其他源。'}], notes
    code = payload.get('code', 0)
    if code not in (0, '0', None):
        return [], [{'date': None, 'reason': f'腾讯 fqkline 返回 code={code}。试过路径：{TRIED_TENCENT}。未改走其他源。'}], notes
    data = payload.get('data')
    node = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(node, dict):
        return [], [{'date': None, 'reason': f'腾讯 fqkline 没有 {symbol} 节点。试过路径：{TRIED_TENCENT}。未改走其他源。'}], notes
    rows = node.get('qfqday')
    other = [name for name in ('day', 'hfqday') if name in node]
    if not isinstance(rows, list):
        extra = '响应里另有 day/hfqday，未改用。' if other else '未改走其他源。'
        return [], [{'date': None, 'reason': f'未取得前复权 qfqday。试过路径：{TRIED_TENCENT}。{extra}{PHRASE_UNKNOWN}。'}], notes
    if not rows:
        extra = '响应里另有 day/hfqday，未改用。' if other else '未改走其他源。'
        return [], [{'date': None, 'reason': f'腾讯前复权 qfqday 为空。试过路径：{TRIED_TENCENT}。{extra}{PHRASE_UNKNOWN}。'}], notes
    items, gaps = [], []
    for row in rows:
        item, gap = _tencent_row(row)
        if gap:
            gaps.append(gap)
        else:
            items.append(item)
    return items, gaps, notes


def _tencent_row(row):
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None, {'date': None, 'reason': f'不合格行已剔除，不补零。{PHRASE_UNKNOWN}。'}
    date = _calendar_day(row[0])
    if date is None:
        return None, _invalid_date_gap(row[0])
    try:
        open_price, close_price = _num(row[1]), _num(row[2])
        high_price, low_price, volume = _num(row[3]), _num(row[4]), _num(row[5])
    except (ValueError, TypeError):
        return None, {'date': date, 'reason': f'不合格行已剔除，不补零。{PHRASE_UNKNOWN}。'}
    if not _bar_ok(open_price, high_price, low_price, close_price, volume):
        return None, {'date': date, 'reason': f'不合格行已剔除，不补零。{PHRASE_UNKNOWN}。'}
    return _bar(date, open_price, high_price, low_price, close_price, volume), None


def _baostock_k(code, start, end, allow_network, query, loader):
    notes = _notes('baostock')
    number, market = code.split('.')
    symbol = {'SH': 'sh', 'SZ': 'sz'}[market] + '.' + number
    if query is None and not allow_network:
        return [], [{'date': None, 'reason': PHRASE_NO_NET_BAOSTOCK}], notes
    if query is None:
        module = load_baostock(loader)
        if module is None:
            return [], [{'date': None, 'reason': f'{PHRASE_NO_PACKAGE}。可选：pip install baostock。未登录、未请求。'}], notes
        try:
            rows = _pull_baostock_k(module, symbol, start, end)
        except (OSError, TimeoutError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            detail = _safe_detail(exc)
            return [], [{'date': None, 'reason': f'baostock 日 K 请求失败。试过路径：{TRIED_BAOSTOCK_K}。未改走其他源。{detail}'}], notes
    else:
        try:
            rows = query(symbol, start, end, '2')
        except (OSError, TimeoutError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            detail = _safe_detail(exc)
            return [], [{'date': None, 'reason': f'baostock 日 K 请求失败。试过路径：{TRIED_BAOSTOCK_K}。未改走其他源。{detail}'}], notes
    if not isinstance(rows, list):
        return [], [{'date': None, 'reason': f'baostock 日 K 结构异常。试过路径：{TRIED_BAOSTOCK_K}。未改走其他源。'}], notes
    items, gaps = [], []
    for row in rows:
        item, gap = _baostock_row(row)
        if gap:
            gaps.append(gap)
        else:
            items.append(item)
    return items, gaps, notes


def _pull_baostock_k(module, symbol, start, end):
    login = module.login()
    if str(getattr(login, 'error_code', '1')) != '0':
        raise RuntimeError('login 未成功')
    try:
        result = module.query_history_k_data_plus(
            symbol, 'date,open,high,low,close,volume,tradestatus',
            start_date=start, end_date=end, frequency='d', adjustflag='2')
        rows = []
        while str(getattr(result, 'error_code', '1')) == '0' and result.next():
            values = result.get_row_data()
            fields = list(getattr(result, 'fields', []))
            if len(fields) != len(values):
                raise ValueError('fields')
            rows.append(dict(zip(fields, values)))
        if str(getattr(result, 'error_code', '1')) != '0':
            raise RuntimeError('query_history_k_data_plus 未成功')
        return rows
    finally:
        _logout(module)


def _baostock_row(row):
    if not isinstance(row, dict):
        return None, {'date': None, 'reason': f'不合格行已剔除，不补零。{PHRASE_UNKNOWN}。'}
    date = _calendar_day(row.get('date'))
    if date is None:
        return None, _invalid_date_gap(row.get('date'))
    status = row.get('tradestatus')
    status_text = '' if status is None else str(status).strip()
    if status_text and status_text != '1':
        return None, {'date': date, 'reason': PHRASE_SUSPEND}
    try:
        item = _bar(date, _num(row.get('open')), _num(row.get('high')), _num(row.get('low')),
                    _num(row.get('close')), _num(row.get('volume')))
    except (ValueError, TypeError):
        if status_text == '1':
            reason = '不合格行已剔除，不补零。baostock tradestatus=1，不能把该日解释为停牌。'
        else:
            reason = f'不合格行已剔除，不补零。{PHRASE_UNKNOWN}。'
        return None, {'date': date, 'reason': reason}
    if not _bar_ok(item['open_price'], item['high_price'], item['low_price'], item['close_price'], item['volume']):
        reason = ('不合格行已剔除，不补零。baostock tradestatus=1，不能把该日解释为停牌。'
                  if status_text == '1' else f'不合格行已剔除，不补零。{PHRASE_UNKNOWN}。')
        return None, {'date': date, 'reason': reason}
    return item, None


def _logout(module):
    try:
        module.logout()
    except (OSError, AttributeError, TypeError, RuntimeError, ValueError):
        return None


def _safe_detail(exc):
    text = ' '.join(str(exc).split())
    if len(text) > 80 or '://' in text or '/Users/' in text or '/home/' in text or '\\' in text:
        return '（细节已省略）'
    return text
