"""Local user research records and date-aligned follow-up. No credentials stored."""
import datetime as dt
import re
import sqlite3
import uuid
from contextlib import contextmanager
from market import DataError, TZ, today
from rankings import finite


class Tracking:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, thscode TEXT NOT NULL, name TEXT NOT NULL, date TEXT NOT NULL, note TEXT NOT NULL, createdAt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)')
            if 'report_id' not in [r[1] for r in db.execute('PRAGMA table_info(observations)')]:
                db.execute("ALTER TABLE observations ADD COLUMN report_id TEXT NOT NULL DEFAULT ''")
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connect() as db:
            return {'items': [dict(r) for r in db.execute('SELECT * FROM observations ORDER BY createdAt DESC, id')]}

    def save(self, body):
        if not isinstance(body, dict): raise DataError('记录格式无效。')
        action = body.get('action', 'add')
        if action not in ('add','archive','import'): raise DataError('记录操作无效。')
        if action == 'archive':
            with self.connect() as db:
                db.execute('UPDATE observations SET active=? WHERE id=?', (0 if body.get('archived', True) else 1, str(body.get('id', ''))))
            return self.list()
        rows = body.get('items') if action == 'import' else [body]
        if not isinstance(rows, list) or len(rows) > 1000: raise DataError('一次最多导入 1000 条记录。')
        validated = []
        for r in rows:
            if not isinstance(r, dict): raise DataError('记录格式无效。')
            code, name, day, note = (r.get(k, '') for k in ('thscode', 'name', 'date', 'note'))
            if not all(isinstance(x, str) for x in (code,name,day,note)): raise DataError('记录字段必须为文本。')
            if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code) or not 1 <= len(name) <= 100 or not 1 <= len(note.strip()) <= 2000: raise DataError('请填写有效股票和关注理由（最多 2000 字）。')
            try: dt.date.fromisoformat(day)
            except ValueError: raise DataError('观察日期无效。')
            identifier = r.get('id', str(uuid.uuid4())) if action == 'import' else str(uuid.uuid4())
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier): raise DataError('记录编号无效。')
            created = r.get('createdAt') if action == 'import' else dt.datetime.now(TZ).isoformat()
            try:
                parsed = dt.datetime.fromisoformat(created.replace('Z', '+00:00'))
                if parsed.tzinfo is None: raise ValueError()
            except (AttributeError, ValueError): raise DataError('记录时间无效。')
            report_id=r.get('report_id','')
            if not isinstance(report_id,str) or (report_id and not re.fullmatch(r'[a-f0-9]{32}',report_id)):raise DataError('关联报告编号无效。')
            validated.append((identifier,code,name,day,note.strip(),created,0 if r.get('active') == 0 else 1,report_id))
        with self.connect() as db:
            db.executemany('INSERT OR IGNORE INTO observations (id,thscode,name,date,note,createdAt,active,report_id) VALUES (?,?,?,?,?,?,?,?)', validated)
        return self.list()


def followup(market, code, observed, end):
    if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code): raise DataError('股票代码无效。')
    dates = market.calendar()
    if observed not in dates or end not in dates: raise DataError('观察日或回看日不是可用交易日。')
    base = dates.index(observed)
    horizons = [(n, dates[base+n] if base+n < len(dates) else None) for n in (1,3,5,10)]
    ready = [d for _,d in horizons if d and d <= end]
    prices = {}
    if ready:
        start = dt.datetime.combine(dt.date.fromisoformat(observed),dt.time(),TZ)
        stop = dt.datetime.combine(dt.date.fromisoformat(max(ready)),dt.time(23,59,59),TZ)
        data = market.get('prices/historical', {'thscode':code,'interval':'1d','adjust':'forward','start':int(start.timestamp()*1000),'end':int(stop.timestamp()*1000)}, ttl=60 if max(ready)==today() else 21600)
        prices = {dt.datetime.fromtimestamp(r['date_ms']/1000,TZ).date().isoformat():r.get('close_price') for r in data['item']}
    baseline = prices.get(observed)
    items = []
    for n, day in horizons:
        close = prices.get(day)
        valid = finite(baseline) and baseline > 0 and finite(close) and close > 0
        provisional = day == today() and dt.datetime.now(TZ).hour < 16
        status = '尚未到期' if not day or day > end else '盘中未定稿' if valid and provisional else '有数据' if valid else '日 K 缺失'
        items.append({'days':n,'date':day,'change':round((close/baseline-1)*100,2) if valid else None,'status':status})
    return {'items':items,'baseline':baseline,'observed':observed,'end':end}
