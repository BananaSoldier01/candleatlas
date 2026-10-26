"""Deterministic research summaries; missing source data stays unknown."""
import re


def themes(stocks):
    groups = {}
    for stock in stocks:
        tags = set(filter(None, (x.strip() for x in re.split(r'[+＋、;；]', stock.get('limit_up_reason') or '原因未披露'))))
        for tag in tags:
            groups.setdefault(tag, []).append(stock)
    return sorted([{'name': name, 'count': len(items),
                    'height': max((s.get('continue_day_cnt') or 0 for s in items), default=0),
                    'stocks': items} for name, items in groups.items()],
                  key=lambda g: (-g['count'], -g['height'], g['name']))


def promotions(previous, current):
    current_map = {s['thscode']: s for s in current}
    rows = []
    for stock in previous:
        old = stock.get('continue_day_cnt')
        if not isinstance(old, int) or old < 2:
            continue
        new = current_map.get(stock['thscode'])
        count = new.get('continue_day_cnt') if new else None
        status = '晋级' if isinstance(count, int) and count == old + 1 else '计数待核对' if new else '未入当日涨停池'
        rows.append({**stock, 'previous_boards': old, 'current_boards': count, 'status': status})
    return sorted(rows, key=lambda s: (-s['previous_boards'], s['thscode']))
