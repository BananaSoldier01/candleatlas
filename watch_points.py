"""Structured observation checks. Conditions only; no trade advice."""
import datetime as dt
import re
import uuid

from analysis import technical
from market import DataError, today
from rankings import finite

METRICS=('close','ma5','ma10','ma20','ma60','rsi14','volume_ratio5','change1','change20','bias20','macd_hist')
OPS=('>=','<=')
DEFAULT_SOURCE='观市日K程序计算（前复权）'
MAX_POINTS=8
SUBJECT_MAX=80
SOURCE_MAX=80
NOTE_MAX=200
BANNED=('应买','应卖','买入','卖出','加仓','减仓','目标价','看多','看空','胜率','上涨概率')
METRIC_LABEL={
    'close':'收盘价','ma5':'MA5','ma10':'MA10','ma20':'MA20','ma60':'MA60','rsi14':'RSI14',
    'volume_ratio5':'较前5日均量','change1':'当日涨跌','change20':'近20日涨跌','bias20':'偏离MA20','macd_hist':'MACD柱',
}
_PRICE_KEYS=('open_price','high_price','low_price','close_price','volume')


def _banned(text):
    if any(word in text for word in BANNED):
        raise DataError('只记录观察条件，不写买卖建议。')


def _text(value, limit, required):
    if value is None:
        value=''
    if not isinstance(value, str):
        raise DataError('观察点文字格式无效。')
    value=value.strip()
    if len(value)>limit:
        raise DataError('观察点文字超出长度上限。')
    if required and not value:
        raise DataError('请填写观察对象。')
    _banned(value)
    return value


def _num_text(value):
    if not finite(value):
        return '—'
    text=f'{float(value):.4f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0','') else text


def describe_point(point):
    """Neutral condition line. Does not judge whether the condition is desirable."""
    if not isinstance(point, dict):
        return '观察点'
    source=point.get('source') or DEFAULT_SOURCE
    nxt=point.get('next_public_date') or '—'
    tail=f'来源：{source} · 下一公开时点：{nxt}'
    if point.get('kind')=='text':
        return f"{point.get('subject') or '文字观察'} · {tail}"
    name=METRIC_LABEL.get(point.get('metric'), point.get('metric') or '指标')
    op='≥' if point.get('op')=='>=' else '≤' if point.get('op')=='<=' else '?'
    if point.get('ref_metric'):
        right=METRIC_LABEL.get(point['ref_metric'], point['ref_metric'])
    else:
        right=_num_text(point.get('value'))
    days=point.get('days') if isinstance(point.get('days'), int) and not isinstance(point.get('days'), bool) else 1
    return f'{name} {op} {right}（连续 {days} 日）· {tail}'


def review_phrase(item):
    status=item.get('status') if isinstance(item, dict) else None
    if status=='appeared':
        day=item.get('first_seen_date') or '—'
        return f"已出现（首次 {day}，当日取值 {_num_text(item.get('value_at_first_seen'))}）"
    if status=='not_appeared':
        return f"未出现（已核对 {int(item.get('checked_days') or 0)} 个交易日）"
    if status=='pending':
        return '尚未到期'
    if status=='manual':
        return '需自行核对'
    return '数据缺失'


def validate_points(raw):
    if raw is None:
        raw=[]
    if not isinstance(raw, list):
        raise DataError('观察点格式无效。')
    if len(raw)>MAX_POINTS:
        raise DataError('观察点最多 8 条。')
    points=[]
    seen=set()
    for item in raw:
        if not isinstance(item, dict):
            raise DataError('观察点格式无效。')
        kind=item.get('kind')
        if kind not in ('metric','text'):
            raise DataError('观察点类型无效。')
        identifier=item.get('id')
        if identifier is None or identifier=='':
            identifier=uuid.uuid4().hex
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier):
            raise DataError('观察点编号无效。')
        if identifier in seen:
            raise DataError('观察点编号重复。')
        seen.add(identifier)
        subject=_text(item.get('subject',''), SUBJECT_MAX, kind=='text')
        note=_text(item.get('note',''), NOTE_MAX, False)
        source=_text(item.get('source','') or DEFAULT_SOURCE, SOURCE_MAX, False) or DEFAULT_SOURCE
        nxt=item.get('next_public_date')
        if nxt in (None,''):
            nxt=None
        elif not isinstance(nxt, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', nxt):
            raise DataError('下一公开时点无效。')
        else:
            try:
                dt.date.fromisoformat(nxt)
            except ValueError:
                raise DataError('下一公开时点无效。')
        days=item.get('days', 1)
        if days is None:
            days=1
        if isinstance(days, bool) or type(days) is not int or not 1<=days<=60:
            raise DataError('观察点连续天数无效。')
        metric=op=value=ref=None
        if kind=='metric':
            metric=item.get('metric')
            if metric not in METRICS:
                raise DataError('观察指标无效。')
            op=item.get('op')
            if op not in OPS:
                raise DataError('观察条件方向无效。')
            ref=item.get('ref_metric') or None
            if ref is not None and ref not in METRICS:
                raise DataError('对照指标无效。')
            if ref==metric:
                raise DataError('对照指标不能与观察指标相同。')
            has_value='value' in item and item.get('value') not in (None,'')
            if ref and has_value:
                raise DataError('阈值和对照指标只能填一项。')
            if not ref and not has_value:
                raise DataError('请填写阈值或对照指标。')
            if has_value:
                value=item.get('value')
                if not finite(value):
                    raise DataError('观察点阈值无效。')
                value=float(value) if isinstance(value, float) else int(value)
            if not subject:
                subject=METRIC_LABEL[metric]
        points.append({
            'id':identifier,'subject':subject,'kind':kind,'metric':metric,'op':op,'value':value,
            'ref_metric':ref,'days':days,'source':source,'next_public_date':nxt,'note':note,
        })
    return points


def _condition(tech, point):
    left=tech.get(point.get('metric'))
    if not finite(left):
        return None, None
    if point.get('ref_metric'):
        right=tech.get(point['ref_metric'])
    else:
        right=point.get('value')
    if not finite(right):
        return None, None
    if point.get('op')=='>=':
        return left>=right, left
    if point.get('op')=='<=':
        return left<=right, left
    return None, None


def _finish(point, status, checked, first, value):
    item={
        'id':point.get('id') if isinstance(point, dict) else None,
        'kind':point.get('kind') if isinstance(point, dict) else None,
        'label':describe_point(point) if isinstance(point, dict) else '观察点',
        'status':status,'checked_days':checked,'first_seen_date':first,'value_at_first_seen':value,
    }
    item['phrase']=review_phrase(item)
    return item


def review_points(prices_rows, observed, end, points, calendar, as_of=None):
    """Whether each condition showed up after the observation day.

    For day d, only bars on or before d are used. Calendar days without a bar stay
    empty; they are not filled from a neighbouring close. Missing data is not
    treated as the condition failing.
    """
    if not isinstance(points, list):
        raise DataError('观察点格式无效。')
    if not isinstance(calendar, (list, tuple)):
        raise DataError('交易日历无效。')
    if as_of is None:
        as_of=today()
    if not isinstance(observed, str) or not isinstance(end, str) or not isinstance(as_of, str):
        raise DataError('观察日期无效。')
    cap=end if end<=as_of else as_of
    days=[]
    for day in sorted(d for d in calendar if isinstance(d, str)):
        if day<=cap and day not in days:
            days.append(day)
    by_date={}
    if isinstance(prices_rows, list):
        for row in prices_rows:
            if isinstance(row, dict) and isinstance(row.get('date'), str) and row['date']<=cap:
                by_date[row['date']]=row
    aligned=[]
    for day in days:
        src=by_date.get(day)
        blank={'date':day}
        if src is None:
            aligned.append(blank)
        else:
            blank.update({key:src.get(key) for key in _PRICE_KEYS})
            aligned.append(blank)
    index={row['date']:i for i, row in enumerate(aligned)}
    horizon=[day for day in days if observed<day<=cap]
    cache={}

    def tech_on(day):
        if day not in cache:
            cache[day]=technical(aligned[:index[day]+1])
        return cache[day]

    results=[]
    for point in points:
        if not isinstance(point, dict) or point.get('kind') not in ('metric','text'):
            results.append(_finish(point if isinstance(point, dict) else {}, 'data_missing', 0, None, None))
            continue
        if point.get('kind')=='text':
            results.append(_finish(point, 'manual', 0, None, None))
            continue
        need=point.get('days') if isinstance(point.get('days'), int) and not isinstance(point.get('days'), bool) else 1
        if need<1:
            need=1
        streak=checked=0
        missing=False
        first=value=None
        for day in horizon:
            if day not in index:
                missing=True
                streak=0
                continue
            met, reading=_condition(tech_on(day), point)
            if met is None:
                missing=True
                streak=0
                continue
            checked+=1
            if met:
                streak+=1
                if streak>=need:
                    first, value=day, reading
                    break
            else:
                streak=0
        if first is not None:
            status='appeared'
        elif not horizon:
            status='pending'
        elif missing:
            status='data_missing'
        else:
            status='not_appeared'
        results.append(_finish(point, status, checked, first, value))
    return results
