"""Pinned chan.py adapter. Daily, local, deterministic; no trading or model calls."""
import datetime as dt
import math
from pathlib import Path
import sys

from market import DataError, today

# Upstream uses absolute imports between its modules; keep its source unmodified.
sys.path.insert(0, str(Path(__file__).parent / 'vendor' / 'chanpy'))
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE, DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_List import CKLine_List
from KLine.KLine_Unit import CKLine_Unit

REVISION = '429d6ed3043e27c93a003ba2b10e70a05575e1f5'
RULES = {'bi_strict': True, 'seg_algo': 'chan', 'zs_algo': 'normal', 'zs_combine': True}


def engine(step=True):
    return CKLine_List(KL_TYPE.K_DAY, CChanConfig({**RULES, 'trigger_step': step}))


def unit(row, index, previous=None):
    d = dt.date.fromisoformat(row['date'])
    u = CKLine_Unit({DATA_FIELD.FIELD_TIME: CTime(d.year, d.month, d.day, 0, 0),
                    DATA_FIELD.FIELD_OPEN: row['open_price'], DATA_FIELD.FIELD_HIGH: row['high_price'],
                    DATA_FIELD.FIELD_LOW: row['low_price'], DATA_FIELD.FIELD_CLOSE: row['close_price']})
    u.set_idx(index)
    u.kl_type = KL_TYPE.K_DAY
    if previous is not None:
        u.set_pre_klu(previous)
    return u


def snapshot(core):
    result = {}
    for kind, lines in [('bi', core.bi_list), ('seg', core.seg_list)]:
        result[kind] = [dict(start=x.get_begin_klu().time.toDateStr('-'), end=x.get_end_klu().time.toDateStr('-'),
                             a=x.get_begin_val(), b=x.get_end_val(), sure=bool(x.is_sure)) for x in lines]
    result['zs'] = [dict(start=x.begin.time.toDateStr('-'), end=x.end.time.toDateStr('-'),
                         low=x.low, high=x.high, sure=bool(x.is_sure)) for x in core.zs_list.zs_lst]
    return result


def identity(kind, item):
    return (kind, item['start'], item['end'], item.get('a'), item.get('b'), item.get('low'), item.get('high'))


def valid(row):
    fields = [row.get(k) for k in ('open_price','high_price','low_price','close_price')]
    if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) and v > 0 for v in fields):
        return False
    o, h, l, c = fields
    return l <= min(o,c) <= max(o,c) <= h


def calculate(rows, cutoff, closed_before=None, include_candidates=False):
    dt.date.fromisoformat(cutoff)
    closed_before = closed_before or today()
    # Never use future or still-current daily bars. Do not bridge missing prices.
    selected = [r for r in rows if r['date'] <= cutoff and r['date'] < closed_before]
    dates = [r['date'] for r in selected]
    if dates != sorted(set(dates)):
        raise DataError('缠论日 K 日期必须严格递增且不重复。')
    for date in dates:
        dt.date.fromisoformat(date)
    last_gap = max((i for i,r in enumerate(selected) if not valid(r)), default=-1)
    usable = selected[last_gap+1:]
    core = engine()
    frames, previous, confirmations = [], None, {}
    collector = None
    candidate_meta = {"status": "ok", "confirmation": "unknown", "types": ["1", "1p", "2", "2s", "3a", "3b"],
                      "policy": "validated-default-types-2"}
    if include_candidates:
        try:
            from chan_candidates import Collector
            collector = Collector(usable)
        except Exception:
            candidate_meta["status"] = "failed"
    for i, row in enumerate(usable):
        u = unit(row, i, previous); core.add_single_klu(u); previous = u
        frame = snapshot(core)
        active = {}
        for kind, elements in frame.items():
            for item in elements:
                key = identity(kind, item)
                item['confirmed_at'] = confirmations.get(key, row['date']) if item['sure'] else None
                if item['sure']:
                    active[key] = item['confirmed_at']
        confirmations = active
        if include_candidates:
            try:
                if collector is None:
                    raise RuntimeError("candidate observer unavailable")
                frame.update(collector.observe(core, row["date"]))
            except Exception:
                collector = None
                candidate_meta["status"] = "failed"
                frame.update(candidates=None, candidate_events=None)
        frames.append({'date':row['date'], **frame})
    notes = ['只使用观察日及以前的历史日 K；当日 K 线暂不参与。',
             '严格笔、特征序列划段、段内中枢；固定规则与版本。',
             '确认日是本次样本逐根输入后，该端点和价格组合连续被标记为已确认的起始日，不是拐点日期。',
             '上游的已确认标志不保证以后绝不修订；虚线结构仍可能延伸或消失。',
             '历史前复权数据可能被上游重算；本次回放不等于还原历史当天的数据版本。']
    if last_gap >= 0:
        notes.append('行情存在缺失或无效 K 线，仅计算最后缺口之后的连续有效区间，未跨缺口连线。')
    if not frames or not any(x['sure'] for x in frames[-1]['seg']):
        notes.append('当前样本尚无已确认线段，不据此生成买卖信号。')
    result = {'engine':'chan.py', 'revision':REVISION, 'rules':RULES, 'date':cutoff,
            'sample':len(usable), 'start':usable[0]['date'] if usable else None,
            'asof':usable[-1]['date'] if usable else None, 'frames':frames, 'notes':notes}
    if include_candidates:
        result["candidate_meta"] = candidate_meta
    return result


def for_market(market, code, day, include_candidates=False):
    prices = market.prices(code, day, 250)
    try:
        return calculate(prices['items'], day, include_candidates=include_candidates)
    except DataError:
        raise
    except Exception as exc:
        raise DataError('缠论计算未完成，请检查行情完整性；原始 K 线仍可查看。') from exc
