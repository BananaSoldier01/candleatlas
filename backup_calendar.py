"""可选 baostock 交易日历。不替换 Market.calendar()，也不是它的自动回退。

默认 allow_network=False。未注入查询回调时不登录、不请求。
未安装可选包时返回缺口「未安装可选依赖 baostock」，不改用工作日规则冒充交易所日历。
数据来自 baostock.query_trade_dates（calendar_date, is_trading_day）。
零 Key。包与数据许可待审（cn-public / 许可待审），不包含再分发权，需维护者复核。
失败只记录所试路径，不改走同花顺、腾讯或其他日历。
"""
import datetime as dt
import urllib.error

from backup_kline import (
    PHRASE_NO_NET_BAOSTOCK, PHRASE_NO_PACKAGE, PHRASE_UNKNOWN, load_baostock, parse_day,
)
from market import DataError

TRIED_CALENDAR = 'baostock.login + query_trade_dates'
_NOTES = (
    'baostock 交易日历，不替换 Market.calendar()。',
    '只收录 is_trading_day=1 的日期。失败不改用周末规则，也不改走其他源。',
    '默认不联网。许可待审，需维护者复核，不包含再分发权。',
)


def fetch_calendar(start, end, *, allow_network=False, baostock_query=None, baostock_loader=None):
    """返回 {'source':'baostock','dates':[...],'gaps':[...],'notes':[...]}。"""
    start = parse_day(start, '开始日期')
    end = parse_day(end, '结束日期')
    if start > end:
        raise DataError('开始日期不能晚于结束日期。')
    if (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days > 3660:
        raise DataError('交易日历区间最长 3660 天。')
    notes = list(_NOTES)
    if baostock_query is None and not allow_network:
        return _pack([], [{'date': None, 'reason': PHRASE_NO_NET_BAOSTOCK}], notes)
    if baostock_query is None:
        module = load_baostock(baostock_loader)
        if module is None:
            return _pack([], [{'date': None, 'reason': f'{PHRASE_NO_PACKAGE}。可选：pip install baostock。未登录、未请求。'}], notes)
        try:
            rows = _pull_calendar(module, start, end)
        except (OSError, TimeoutError, urllib.error.URLError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            return _pack([], [{'date': None, 'reason': _fail(exc)}], notes)
    else:
        try:
            rows = baostock_query(start, end)
        except (OSError, TimeoutError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            return _pack([], [{'date': None, 'reason': _fail(exc)}], notes)
    if not isinstance(rows, list):
        return _pack([], [{'date': None, 'reason': f'baostock 交易日历结构异常。试过路径：{TRIED_CALENDAR}。未改走其他源。'}], notes)
    return _rows(rows, start, end, notes)


def _logout(module):
    try:
        module.logout()
    except (OSError, AttributeError, TypeError, RuntimeError, ValueError):
        return None


def _pack(dates, gaps, notes):
    return {'source': 'baostock', 'dates': dates, 'gaps': gaps, 'notes': list(notes)}


def _fail(exc):
    text = ' '.join(str(exc).split())
    if len(text) > 80 or '://' in text or '/Users/' in text or '/home/' in text or '\\' in text:
        text = '（细节已省略）'
    return f'baostock 交易日历请求失败。试过路径：{TRIED_CALENDAR}。未改走其他源。{text}'


def _pull_calendar(module, start, end):
    login = module.login()
    if str(getattr(login, 'error_code', '1')) != '0':
        raise RuntimeError('login 未成功')
    try:
        result = module.query_trade_dates(start_date=start, end_date=end)
        rows = []
        while str(getattr(result, 'error_code', '1')) == '0' and result.next():
            values = result.get_row_data()
            fields = list(getattr(result, 'fields', []))
            if len(fields) != len(values):
                raise ValueError('fields')
            rows.append(dict(zip(fields, values)))
        if str(getattr(result, 'error_code', '1')) != '0':
            raise RuntimeError('query_trade_dates 未成功')
        return rows
    finally:
        _logout(module)


def _rows(rows, start, end, notes):
    """只承认上游逐日给出的 is_trading_day。缺日不按周一至周五补。"""
    flags, gaps = {}, []
    for row in rows:
        if not isinstance(row, dict):
            gaps.append({'date': None, 'reason': f'不合格行已剔除。{PHRASE_UNKNOWN}。'})
            continue
        day = row.get('calendar_date', row.get('date'))
        if not isinstance(day, str) or parse_safe(day) is None:
            gaps.append({'date': None, 'reason': f'不合格行已剔除。日期无效。{PHRASE_UNKNOWN}。'})
            continue
        flag = row.get('is_trading_day')
        flag_text = '' if flag is None else str(flag).strip()
        if day in flags:
            gaps.append({'date': day, 'reason': '重复日期已剔除，未合并。'})
            continue
        if flag_text not in ('0', '1'):
            flags[day] = ''
            gaps.append({'date': day, 'reason': f'is_trading_day 无效，未计入交易日。{PHRASE_UNKNOWN}。'})
            continue
        flags[day] = flag_text
    dates = []
    cursor = dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end)
    while cursor <= last:
        iso = cursor.isoformat()
        flag_text = flags.get(iso)
        if flag_text == '1':
            dates.append(iso)
        elif flag_text is None:
            gaps.append({'date': iso, 'reason': f'该日不在 baostock 返回中，未按周末或工作日规则补入。试过路径：{TRIED_CALENDAR}。{PHRASE_UNKNOWN}。'})
        cursor += dt.timedelta(days=1)
    return _pack(dates, gaps, notes)


def parse_safe(value):
    try:
        return parse_day(value)
    except DataError:
        return None
