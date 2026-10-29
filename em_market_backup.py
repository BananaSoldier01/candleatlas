"""东方财富涨停/炸板/跌停池与涨跌分布对照。默认不联网。

来源名：东方财富行情门户推送接口 push2ex.eastmoney.com（非交易所官方文件）。
用途：给「连板跟踪 / 短线温度 / 涨跌分布」做代码集合或家数对照。
许可：待审。本文件不授予再分发权；程序 MIT 许可不包含该门户的行情、名单或家数。
维护者复核条款、可用性和字段口径之前，不得当作默认数据源，不得写入发行包，
不得在同花顺失败时自动改走这里。

默认 allow_network=False。只有调用方显式打开，或自行传入已取得的响应字节，才会读数据。
真实请求只打本文件常量里的那一条路径；失败写明缺口和试过的路径，不改试其他主机，
也不和同花顺 special-data 拼成一条序列。

涨跌分布只认 getTopicZDFenBu 的当日快照，请求里没有历史日参数，不认历史日。
字段形状依据公开页面常见返回，本仓库没有做真实联网核对。

客户端自我限速 MIN_INTERVAL_SECONDS（不少于 1 秒）。这不表示门户允许采集。
页面查询参数 ut 是门户网页自带的公开参数，不是发给本项目的密钥；缺口文本里省略它。
"""
import datetime as dt
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = 'push2ex.eastmoney.com'
POOL_PATHS = {
    'up': '/getTopicZTPool',
    'break': '/getTopicZBPool',
    'down': '/getTopicDTPool',
}
BREADTH_PATH = '/getTopicZDFenBu'
# 门户网页公开查询参数，不是本项目申请的接口密钥。
PAGE_QUERY_UT = '7eea3edcaed734bea9cbfc24409ed989'
PAGE_SIZE = 10000
MIN_INTERVAL_SECONDS = 1.0
USER_AGENT = 'CandleAtlas-Guanshi/em-backup (teaching; rate-limited)'
MAX_BYTES = 4_000_000

LICENSE_NOTE = (
    '东方财富推送接口（push2ex.eastmoney.com）来自行情门户页面，不是交易所或指数公司的官方文件，'
    '也不是本项目获授权的数据接口。许可待审。程序的 MIT 许可不包含其涨停、炸板、跌停名单或涨跌分布的再分发权。'
    '维护者复核条款与可用性之前，不得作为默认数据源，不得放进发行包，不得再分发取回的内容。'
)
RATE_LIMIT_NOTE = (
    f'同一进程对 {HOST} 的真实请求最少间隔 {MIN_INTERVAL_SECONDS:g} 秒。'
    '这只是客户端自我限速，不代表门户允许采集。请勿缩短间隔，勿用于批量扫描。'
)
STATUS_NOTE = '涨停、炸板、跌停和涨跌家数只记录上游给出的状态，不是买卖建议，也不保证次日涨跌。'
SEPARATE_NOTE = '与同花顺 special-data 或全市场快照并列。失败不改走同花顺，成功也不写入研究摘要或炸板率。'
SNAPSHOT_NOTE = '涨跌分布上游是当日快照，不认历史日。不能把某一天的快照填进其他观察日。'

_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = None

_CODE = re.compile(r'\d{6}')
_THS = re.compile(r'\d{6}\.(SH|SZ|BJ)')


def reset_rate_gate():
    """测试或进程内手工重置限速时钟。不会因此发出请求。"""
    global _LAST_REQUEST_AT
    with _RATE_LOCK:
        _LAST_REQUEST_AT = None


def _check_hooks(allow_network, fetch_bytes, fetch, clock, sleeper):
    if type(allow_network) is not bool:
        raise ValueError('allow_network 必须是布尔值。')
    if fetch_bytes is not None and not isinstance(fetch_bytes, bytes):
        raise ValueError('fetch_bytes 必须是字节或省略。')
    if fetch is not None and not callable(fetch):
        raise ValueError('fetch 必须是可调用对象或省略。')
    if clock is not None and not callable(clock):
        raise ValueError('clock 必须是可调用对象或省略。')
    if sleeper is not None and not callable(sleeper):
        raise ValueError('sleeper 必须是可调用对象或省略。')


def _day_compact(day):
    if not isinstance(day, str):
        raise ValueError('日期须是 YYYY-MM-DD 文本。')
    try:
        parsed = dt.date.fromisoformat(day)
    except ValueError:
        raise ValueError('日期须是 YYYY-MM-DD。') from None
    if parsed.isoformat() != day:
        raise ValueError('日期须是 YYYY-MM-DD。')
    return parsed.isoformat(), parsed.strftime('%Y%m%d')


def _envelope(kind, day, items, gaps, notes):
    return {
        'source': 'eastmoney',
        'kind': kind,
        'day': day,
        'items': items,
        'gaps': list(gaps),
        'notes': [STATUS_NOTE, SEPARATE_NOTE, *notes],
        'license_note': LICENSE_NOTE,
        'rate_limit_note': RATE_LIMIT_NOTE,
    }


def _acquire(clock, sleeper):
    global _LAST_REQUEST_AT
    now = clock()
    if isinstance(now, bool) or not isinstance(now, (int, float)):
        raise ValueError('clock 必须返回数值时间。')
    with _RATE_LOCK:
        last = _LAST_REQUEST_AT
        if last is not None:
            wait = MIN_INTERVAL_SECONDS - (now - last)
            if wait > 0:
                sleeper(wait)
                now = clock()
                if isinstance(now, bool) or not isinstance(now, (int, float)) or now < last + MIN_INTERVAL_SECONDS:
                    now = last + MIN_INTERVAL_SECONDS
        _LAST_REQUEST_AT = now


def _public_query(extra):
    pairs = [('ut', PAGE_QUERY_UT), ('dpt', 'wz.ztzt'), *extra]
    return urllib.parse.urlencode(pairs)


def _pool_urls(kind, compact):
    path = POOL_PATHS[kind]
    request = f'https://{HOST}{path}?{_public_query([("Pageindex", "0"), ("pagesize", str(PAGE_SIZE)), ("sort", "fbt:asc"), ("date", compact)])}'
    shown = f'https://{HOST}{path}?date={compact}&Pageindex=0&pagesize={PAGE_SIZE}'
    return request, shown


def _breadth_urls():
    path = BREADTH_PATH
    request = f'https://{HOST}{path}?{_public_query(())}'
    shown = f'https://{HOST}{path}'
    return request, shown


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = urllib.parse.urlsplit(newurl)
        old = urllib.parse.urlsplit(req.full_url)
        if new.scheme != 'https' or new.hostname != old.hostname or new.hostname != HOST:
            raise urllib.error.HTTPError(req.full_url, code, f'重定向离开 {HOST}，已停止', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != HOST or parts.username or parts.password:
        raise OSError(f'地址不在 {HOST}，已拒绝。未改试其他来源。')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SameHostRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with opener.open(request, timeout=10) as response:
        status = getattr(response, 'status', None)
        if status is not None and status != 200:
            raise urllib.error.HTTPError(url, status, '门户返回非 200', response.headers, response)
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise OSError('响应超过读取上限，已停止。未改试其他来源。')
    return body


def _load_body(body, shown):
    if not isinstance(body, bytes):
        return None, [f'响应不是字节。试过的路径：{shown}。未改试其他来源。']
    try:
        text = body.decode('utf-8-sig')
    except UnicodeError:
        return None, [f'响应不是 UTF-8。试过的路径：{shown}。未改用其他编码或其他来源。']
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, [f'响应不是 JSON。试过的路径：{shown}。未改试其他来源。']
    return payload, []


class _Gap:
    """已写成缺口的结果。用类型区分，避免和门户 JSON 里碰巧同名的字段混在一起。"""

    def __init__(self, envelope):
        self.envelope = envelope


def _failure(kind, day, shown, exc):
    detail = str(exc).replace('\n', ' ')[:200]
    gap = f'拉取失败（{type(exc).__name__}：{detail}）。试过的路径：{shown}。未改试其他来源。'
    return _Gap(_envelope(kind, day, [], [gap], []))


def _read_remote(kind, day, request_url, shown, fetch, clock, sleeper):
    _acquire(clock or time.monotonic, sleeper or time.sleep)
    try:
        body = fetch(request_url) if fetch is not None else _http_get(request_url)
    except Exception as exc:
        return _failure(kind, day, shown, exc)
    payload, gaps = _load_body(body, shown)
    if payload is None:
        return _Gap(_envelope(kind, day, [], gaps, []))
    return payload


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _suffix(code):
    if code.startswith('92') or code.startswith(('4', '8')):
        return 'BJ'
    if code.startswith('6'):
        return 'SH'
    if code.startswith(('0', '3')):
        return 'SZ'
    return None


def _market_ok(suffix, market):
    if market is None:
        return True
    if suffix == 'BJ':
        return market in (0, '0')
    if suffix == 'SH':
        return market in (1, '1')
    if suffix == 'SZ':
        return market in (0, '0')
    return False


def _clock_text(value):
    if isinstance(value, str) and re.fullmatch(r'\d{1,6}', value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    if value == 0:
        return None
    if value < 0 or value > 235959:
        return False
    text = f'{value:06d}'
    hour, minute, second = int(text[:2]), int(text[2:4]), int(text[4:])
    if hour > 23 or minute > 59 or second > 59:
        return False
    return f'{hour:02d}:{minute:02d}:{second:02d}'


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not _finite(value) or value <= 0:
        return None
    if isinstance(value, int):
        return value / 1000
    return value


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_time(row, key, label, title, gaps):
    if key not in row:
        return None
    parsed = _clock_text(row.get(key))
    if parsed is False:
        gaps.append(f'{label} 的{title}无法读取，留空。')
        return None
    if parsed is None:
        gaps.append(f'{label} 的{title}为 0，视为未给出，不写成 00:00:00。')
        return None
    return parsed


def _row(row, kind, index, gaps):
    raw = row.get('c')
    if not isinstance(raw, str) or not _CODE.fullmatch(raw):
        gaps.append(f'第 {index} 条缺少 6 位代码，已跳过。')
        return None
    suffix = _suffix(raw)
    if suffix is None:
        gaps.append(f'第 {index} 条代码 {raw} 不能对应沪深京后缀，已跳过。')
        return None
    market = row.get('m')
    if not _market_ok(suffix, market):
        gaps.append(f'{raw} 的市场标记与代码前缀不一致，仍按代码前缀记为 {raw}.{suffix}。')
    name = row.get('n')
    if not isinstance(name, str) or not name.strip():
        name = None
    else:
        name = name.strip()
    industry = row.get('hybk')
    if not isinstance(industry, str) or not industry.strip():
        industry = None
    else:
        industry = industry.strip()
    label = f'{raw}.{suffix}'
    if 'lbc' in row:
        continue_count = _positive_int(row.get('lbc'))
        if continue_count is None:
            gaps.append(f'{label} 的连板数不是正整数，留空，未记为 0。')
    elif kind == 'down' and 'days' in row:
        continue_count = _positive_int(row.get('days'))
        if continue_count is None:
            gaps.append(f'{label} 的连续跌停数不是正整数，留空，未记为 0。')
    else:
        continue_count = None
    if 'zbc' in row:
        open_count = _count(row.get('zbc'))
        if open_count is None:
            gaps.append(f'{label} 的开板或炸板次数无法读取，留空，未记为 0。')
    elif kind == 'down' and 'ocnt' in row:
        open_count = _count(row.get('ocnt'))
        if open_count is None:
            gaps.append(f'{label} 的开板或炸板次数无法读取，留空，未记为 0。')
    else:
        open_count = None
    limit_up_time = _optional_time(row, 'fbt', label, '首次封板时间', gaps) if kind in ('up', 'break') else None
    last_limit_time = _optional_time(row, 'lbt', label, '最后封板时间', gaps)
    change = row.get('zdp') if 'zdp' in row else None
    if change is not None and not _finite(change):
        gaps.append(f'{label} 的涨跌幅无法读取，留空，未记为 0。')
        change = None
    if 'p' not in row:
        price = None
    else:
        price = _price(row.get('p'))
        if price is None:
            gaps.append(f'{label} 的最新价无法读取，留空，未记为 0。')
    return {
        'thscode': f'{raw}.{suffix}',
        'code': raw,
        'name': name,
        'continue_day_cnt': continue_count,
        'limit_up_time': limit_up_time,
        'last_limit_time': last_limit_time,
        'open_count': open_count,
        'industry': industry,
        'change_pct': change,
        'latest_price': price,
    }


def _parse_pool(payload, kind, day, shown):
    gaps = []
    notes = ['整数最新价按门户常见口径除以 1000；缺失或 0 留空，不补成 0。名单口径未经本仓库真实联网核对。']
    if not isinstance(payload, dict):
        return _envelope(kind, day, [], [f'响应不是 JSON 对象。试过的路径：{shown}。未改试其他来源。'], notes)
    rc = payload.get('rc', 0)
    if rc not in (0, '0', None):
        return _envelope(kind, day, [], [f'上游 rc={rc!r}，未采用名单。试过的路径：{shown}。未改试其他来源。'], notes)
    data = payload.get('data')
    if data is None:
        notes.append('上游 data 为空，按空池记录。未改试其他来源。')
        return _envelope(kind, day, [], gaps, notes)
    if not isinstance(data, dict) or not isinstance(data.get('pool'), list):
        return _envelope(kind, day, [], [f'上游缺少 pool 列表。试过的路径：{shown}。未改试其他来源。'], notes)
    pool = data['pool']
    total = data.get('tc')
    if isinstance(total, bool) or (total is not None and not isinstance(total, int)):
        gaps.append('上游 tc 不是整数，无法核对是否取全。未自动翻页。')
    elif isinstance(total, int) and total != len(pool):
        gaps.append(f'上游 tc={total} 与本页 {len(pool)} 条不一致。未自动翻页，也未改试其他来源。')
    if len(pool) >= PAGE_SIZE:
        gaps.append(f'本页条数达到 pagesize={PAGE_SIZE} 上限，未自动翻页，名单可能不完整。')
    items, seen = [], set()
    for index, row in enumerate(pool, 1):
        if not isinstance(row, dict):
            gaps.append(f'第 {index} 条不是对象，已跳过。')
            continue
        parsed = _row(row, kind, index, gaps)
        if parsed is None:
            continue
        if parsed['thscode'] in seen:
            gaps.append(f'{parsed["thscode"]} 重复出现，保留先出现的一条。')
            continue
        seen.add(parsed['thscode'])
        items.append(parsed)
    return _envelope(kind, day, items, gaps, notes)


def _iso_from_snapshot(value):
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    if re.fullmatch(r'\d{8}', value):
        value = f'{value[0:4]}-{value[4:6]}-{value[6:8]}'
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _parse_breadth(payload, shown):
    notes = [SNAPSHOT_NOTE, '涨跌分布的分桶沿用上游字段，与同花顺七组涨跌分布不是同一口径，禁止合并或互相补零。']
    if not isinstance(payload, dict):
        return _envelope('breadth', None, [], [f'响应不是 JSON 对象。试过的路径：{shown}。未改读其他接口。'], notes)
    rc = payload.get('rc', 0)
    if rc not in (0, '0', None):
        return _envelope('breadth', None, [], [f'上游 rc={rc!r}，未采用涨跌分布。试过的路径：{shown}。未改读其他接口。'], notes)
    data = payload.get('data')
    if not isinstance(data, dict):
        return _envelope('breadth', None, [], [f'未找到涨跌分布 data。试过的路径：{shown}。未改读其他接口。'], notes)
    day = _iso_from_snapshot(data.get('qdate', data.get('date')))
    if ('qdate' in data or 'date' in data) and day is None:
        notes.append('快照里的日期无法解析，day 留空。不把本机今天填进去。')
    fenbu = data.get('fenbu')
    gaps = []
    if isinstance(fenbu, list):
        if len(fenbu) > 1:
            gaps.append('涨跌分布返回多段，只读取第一段，未拼接。')
        fenbu = fenbu[0] if fenbu else None
    if not isinstance(fenbu, dict):
        gaps.append(f'未找到 fenbu 对象。试过的路径：{shown}。未改读其他接口。')
        return _envelope('breadth', day, [], gaps, notes)
    bins = {}
    for key, value in fenbu.items():
        if isinstance(key, str) and re.fullmatch(r'-?\d+', key) and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            bins[key] = value
        else:
            gaps.append(f'涨跌分布字段 {key!r} 不能当作家数，已跳过，未补 0。')
    if not bins:
        gaps.append(f'fenbu 里没有可用家数。试过的路径：{shown}。未改读其他接口。')
        return _envelope('breadth', day, [], gaps, notes)
    up = sum(value for key, value in bins.items() if int(key) > 0)
    down = sum(value for key, value in bins.items() if int(key) < 0)
    flat = bins.get('0')
    sample = up + down + flat if flat is not None else None
    item = {'bins': bins, 'up': up, 'down': down, 'flat': flat, 'sample': sample}
    return _envelope('breadth', day, [item], gaps, notes)


def fetch_limit_pool(day, kind='up', *, allow_network=False, fetch_bytes=None, fetch=None, clock=None, sleeper=None):
    """读取某一日涨停、炸板或跌停池。kind 为 up、break 或 down。

    默认不联网。fetch_bytes 优先于联网。fetch 只在 allow_network 为 true 且没有 fetch_bytes 时调用。
    """
    _check_hooks(allow_network, fetch_bytes, fetch, clock, sleeper)
    if kind not in POOL_PATHS:
        raise ValueError('kind 只能是 up、break 或 down。')
    iso, compact = _day_compact(day)
    _, shown = _pool_urls(kind, compact)
    if fetch_bytes is not None:
        payload, gaps = _load_body(fetch_bytes, shown)
        if payload is None:
            return _envelope(kind, iso, [], gaps, [])
        return _parse_pool(payload, kind, iso, shown)
    if not allow_network:
        return _envelope(kind, iso, [], [
            f'未联网：allow_network 为 false，且没有提供响应字节。未请求 {shown}。'
        ], [])
    request_url, shown = _pool_urls(kind, compact)
    loaded = _read_remote(kind, iso, request_url, shown, fetch, clock, sleeper)
    if isinstance(loaded, _Gap):
        return loaded.envelope
    return _parse_pool(loaded, kind, iso, shown)


def fetch_market_breadth(*, allow_network=False, fetch_bytes=None, fetch=None, clock=None, sleeper=None):
    """读取涨跌分布当日快照。没有历史日参数，不认历史日。

    默认不联网。fetch_bytes 优先于联网。fetch 只在 allow_network 为 true 且没有 fetch_bytes 时调用。
    """
    _check_hooks(allow_network, fetch_bytes, fetch, clock, sleeper)
    _, shown = _breadth_urls()
    if fetch_bytes is not None:
        payload, gaps = _load_body(fetch_bytes, shown)
        if payload is None:
            return _envelope('breadth', None, [], gaps, [SNAPSHOT_NOTE])
        return _parse_breadth(payload, shown)
    if not allow_network:
        return _envelope('breadth', None, [], [
            f'未联网：allow_network 为 false，且没有提供响应字节。未请求 {shown}。不认历史日。'
        ], [SNAPSHOT_NOTE])
    request_url, shown = _breadth_urls()
    loaded = _read_remote('breadth', None, request_url, shown, fetch, clock, sleeper)
    if isinstance(loaded, _Gap):
        if SNAPSHOT_NOTE not in loaded.envelope['notes']:
            loaded.envelope['notes'] = [*loaded.envelope['notes'], SNAPSHOT_NOTE]
        return loaded.envelope
    return _parse_breadth(loaded, shown)


def _identity(item):
    if not isinstance(item, dict):
        return None
    thscode = item.get('thscode')
    if isinstance(thscode, str) and _THS.fullmatch(thscode):
        return thscode
    raw = item.get('code')
    if isinstance(raw, str) and _CODE.fullmatch(raw):
        suffix = _suffix(raw)
        if suffix is None:
            return None
        return f'{raw}.{suffix}'
    return None


def compare_pools(primary_items, backup_items):
    """只对照两份名单的代码集合，不合并、不评分、不给出买卖。"""
    if not isinstance(primary_items, list) or not isinstance(backup_items, list):
        raise ValueError('对照两边都须是列表；缺失不能当成空池。')
    notes = [
        '只对照代码集合，不合并成一条涨停、炸板或跌停序列。',
        '名单不同只说明口径或时点可能不同，本对照不评价来源优劣。',
        '不是买卖建议。',
    ]

    def collect(items, side):
        found = set()
        for item in items:
            identity = _identity(item)
            if identity is None:
                notes.append(f'{side}有一条缺少可对照代码，未计入集合。')
                continue
            if identity in found:
                notes.append(f'{side}的 {identity} 重复，集合里只计一次。')
                continue
            found.add(identity)
        return found

    primary = collect(primary_items, '主源')
    backup = collect(backup_items, '备源')
    return {
        'only_primary': sorted(primary - backup),
        'only_backup': sorted(backup - primary),
        'both': sorted(primary & backup),
        'notes': notes,
    }


def synthetic_demo(kind, day=None):
    """演示用合成对照表。不请求东方财富，也不读取同花顺。"""
    if kind not in ('up', 'break', 'down', 'breadth'):
        raise ValueError('kind 只能是 up、break、down 或 breadth。')
    if kind != 'breadth':
        if day is None:
            raise ValueError('请提供 date=YYYY-MM-DD。')
        iso, _compact = _day_compact(day)
    else:
        iso = None
        if day not in (None, ''):
            iso = None
    notice = '合成对照表，不是东方财富实时数据，也不是同花顺涨停池。'
    base = {
        'source': 'synthetic-demo',
        'illustrates': 'eastmoney',
        'synthetic': True,
        'kind': kind,
        'day': iso if kind != 'breadth' else None,
        'license_note': LICENSE_NOTE,
        'rate_limit_note': RATE_LIMIT_NOTE,
    }
    if kind == 'breadth':
        notes = [notice, SNAPSHOT_NOTE, '合成家数只有三只示例股票的示意，不能填进同花顺涨跌分布。']
        if day not in (None, ''):
            notes.append('请求中的 date 已忽略：涨跌分布不认历史日。')
        return {
            **base,
            'items': [{'bins': {'-1': 1, '0': 1, '1': 1}, 'up': 1, 'down': 1, 'flat': 1, 'sample': 3}],
            'gaps': [],
            'notes': [STATUS_NOTE, SEPARATE_NOTE, *notes],
        }
    primary = [
        {'thscode': '600000.SH', 'name': '合成示例甲'},
        {'thscode': '000001.SZ', 'name': '合成示例乙'},
    ]
    backup = [
        {
            'thscode': '000001.SZ', 'code': '000001', 'name': '合成示例乙',
            'continue_day_cnt': 1, 'limit_up_time': '09:31:00', 'last_limit_time': '09:31:00',
            'open_count': 0, 'industry': '合成行业', 'change_pct': None, 'latest_price': None,
        },
        {
            'thscode': '920001.BJ', 'code': '920001', 'name': '合成示例丙',
            'continue_day_cnt': 2, 'limit_up_time': '10:01:00', 'last_limit_time': '10:01:00',
            'open_count': 1, 'industry': '合成行业', 'change_pct': None, 'latest_price': None,
        },
    ]
    compared = compare_pools(primary, backup)
    return {
        **base,
        'day': iso,
        'items': backup,
        'gaps': [],
        'notes': [STATUS_NOTE, SEPARATE_NOTE, notice, '合成主源只含 600000.SH 与 000001.SZ；合成备源只含 000001.SZ 与 920001.BJ。'],
        'compare': compared,
    }
