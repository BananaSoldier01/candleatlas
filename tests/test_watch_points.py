"""Watch-point validation, expiry review, and old observation compatibility."""
import datetime as dt
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from analysis import Analysis, technical
from market import DataError, TZ
from server import Handler
from tracking import Tracking, followup
from watch_points import describe_point, review_points, validate_points
from workbench import summary


@contextmanager
def connect(path):
    db=sqlite3.connect(path)
    try:
        yield db
        db.commit()
    finally:
        db.close()


def metric(**extra):
    point={'kind':'metric','metric':'close','op':'>=','value':70}
    point.update(extra)
    return point


def bar(day, close, volume=1000):
    return {'date':day,'open_price':close,'high_price':close,'low_price':close,'close_price':close,'volume':volume}


def weekdays():
    return ['2026-09-01','2026-09-02','2026-09-03','2026-09-04','2026-09-07','2026-09-08','2026-09-09']


def closes(mapping):
    return [bar(day, price) for day, price in mapping.items()]


class ValidateTests(unittest.TestCase):
    def test_defaults_ref_and_exact_label(self):
        points=validate_points([{'kind':'metric','metric':'rsi14','op':'>=','value':70}, metric(metric='close', op='>=', ref_metric='ma20', value=None), {'kind':'text','subject':'下一份财报预约披露日','source':'巨潮公告索引/自行核对'}])
        self.assertEqual(points[0]['subject'],'RSI14')
        self.assertEqual(points[0]['days'],1)
        self.assertEqual(points[0]['source'],'观市日K程序计算（前复权）')
        self.assertIsNone(points[0]['next_public_date'])
        self.assertEqual(points[0]['value'],70)
        self.assertEqual(describe_point(points[0]),'RSI14 ≥ 70（连续 1 日）· 来源：观市日K程序计算（前复权） · 下一公开时点：—')
        self.assertIsNone(points[1]['value'])
        self.assertEqual(points[1]['ref_metric'],'ma20')
        self.assertIn('收盘价 ≥ MA20（连续 1 日）', describe_point(points[1]))
        self.assertIsNone(points[2]['metric'])
        self.assertEqual(describe_point(points[2]),'下一份财报预约披露日 · 来源：巨潮公告索引/自行核对 · 下一公开时点：—')
        self.assertEqual(validate_points(None),[])
        kept=validate_points([metric(value=0, id='zero', extra='drop-me')])
        self.assertEqual(kept[0]['value'],0)
        self.assertNotIn('extra', kept[0])

    def test_rejects_advice_limits_and_bad_fields(self):
        for word in ('应买','应卖','买入','卖出','加仓','减仓','目标价','看多','看空','胜率','上涨概率'):
            with self.subTest(word=word):
                with self.assertRaises(DataError) as caught:
                    validate_points([{'kind':'text','subject':'下一披露','note':'请'+word}])
                self.assertEqual(str(caught.exception),'只记录观察条件，不写买卖建议。')
        with self.assertRaises(DataError) as caught:
            validate_points([metric(id=f'p{i}') for i in range(9)])
        self.assertEqual(str(caught.exception),'观察点最多 8 条。')
        self.assertEqual(len(validate_points([metric(id=f'p{i}') for i in range(8)])),8)
        for field, value in (('subject','对象'*41),('note','说明'*101),('source','来源'*41)):
            with self.subTest(field=field):
                with self.assertRaises(DataError) as caught:
                    validate_points([metric(**{field:value})])
                self.assertEqual(str(caught.exception),'观察点文字超出长度上限。')
        cases=[
            (metric(value=1, ref_metric='ma20'),'阈值和对照指标只能填一项。'),
            ({'kind':'metric','metric':'close','op':'>='},'请填写阈值或对照指标。'),
            (metric(days=True),'观察点连续天数无效。'),
            (metric(days=0),'观察点连续天数无效。'),
            (metric(days=61),'观察点连续天数无效。'),
            (metric(days=1.5),'观察点连续天数无效。'),
            (metric(next_public_date='2026-02-31'),'下一公开时点无效。'),
            (metric(next_public_date='20260901'),'下一公开时点无效。'),
            (metric(id='bad id'),'观察点编号无效。'),
            (metric(id='a'*65),'观察点编号无效。'),
            ({'kind':'text','subject':''},'请填写观察对象。'),
            ({'kind':'other','subject':'x'},'观察点类型无效。'),
            (metric(metric='pe'),'观察指标无效。'),
            (metric(op='>'),'观察条件方向无效。'),
            (metric(value=float('nan')),'观察点阈值无效。'),
            (metric(value=True),'观察点阈值无效。'),
            (metric(ref_metric='close'),'对照指标不能与观察指标相同。'),
            (metric(ref_metric='pe', value=None),'对照指标无效。'),
            ('bad','观察点格式无效。'),
        ]
        for raw, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(DataError) as caught:
                    validate_points([raw] if not isinstance(raw, str) else raw)
                self.assertEqual(str(caught.exception), message)
        with self.assertRaises(DataError) as caught:
            validate_points([metric(id='same'), metric(id='same')])
        self.assertEqual(str(caught.exception),'观察点编号重复。')


class StoreTests(unittest.TestCase):
    def test_migration_bad_json_and_old_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'records.sqlite3'
            with connect(path) as db:
                db.execute('CREATE TABLE observations (id TEXT PRIMARY KEY,thscode TEXT,name TEXT,date TEXT,note TEXT,createdAt TEXT,active INTEGER)')
                db.execute("INSERT INTO observations VALUES ('old','600487.SH','旧记录','2026-09-17','保留理由','2026-09-17T10:00:00+08:00',1)")
            store=Tracking(path)
            with connect(path) as db:
                columns=[row[1] for row in db.execute('PRAGMA table_info(observations)')]
            self.assertIn('watch_points', columns)
            self.assertEqual(store.list()['items'][0]['note'],'保留理由')
            self.assertEqual(store.list()['items'][0]['report_id'],'')
            self.assertEqual(store.list()['items'][0]['watch_points'],[])
            with connect(path) as db:
                db.execute("UPDATE observations SET watch_points=? WHERE id='old'", ('{',))
            listed=store.list()['items'][0]
            self.assertEqual(listed['watch_points'],[])
            self.assertEqual(listed['note'],'保留理由')
            with connect(path) as db:
                self.assertEqual(db.execute("SELECT watch_points FROM observations WHERE id='old'").fetchone()[0],'{')
            for raw in ('{"a":1}','null',''):
                with connect(path) as db:
                    db.execute('UPDATE observations SET watch_points=? WHERE id=?', (raw,'old'))
                self.assertEqual(store.list()['items'][0]['watch_points'],[])
            legacy={'id':'legacy-file','thscode':'600487.SH','name':'旧文件','date':'2026-09-18','note':'纯文本理由','createdAt':'2026-09-18T10:00:00+08:00','active':1}
            store.save({'action':'import','items':[legacy, {**legacy,'id':'legacy-null','watch_points':None}]})
            imported={item['id']:item for item in store.list()['items']}
            self.assertEqual(imported['legacy-file']['watch_points'],[])
            self.assertEqual(imported['legacy-null']['watch_points'],[])
            self.assertEqual(imported['legacy-file']['note'],'纯文本理由')
            points=validate_points([metric(id='rsi', metric='rsi14', value=70, note='只核对指标')])
            fresh={'id':'with-points','thscode':'000001.SZ','name':'带观察点','date':'2026-09-18','note':'关注理由原样保留','createdAt':'2026-09-18T11:00:00+08:00','active':1,'watch_points':points}
            store.save({'action':'import','items':[fresh]})
            before=len(store.list()['items'])
            with self.assertRaises(DataError):
                store.save({'action':'import','items':[{**fresh,'id':'rolled'}, {**fresh,'id':'bad-points','watch_points':[{'kind':'metric'}]}]})
            self.assertEqual(len(store.list()['items']), before)
            exported=next(item for item in store.list()['items'] if item['id']=='with-points')
            self.assertEqual(exported['note'],'关注理由原样保留')
            self.assertEqual(exported['watch_points'][0]['label'], describe_point(points[0]))
            other=Tracking(Path(tmp)/'roundtrip.sqlite3')
            other.save({'action':'import','items':[exported]})
            again=other.list()['items'][0]
            self.assertEqual(again['watch_points'], exported['watch_points'])
            self.assertEqual(again['note'], exported['note'])


class ReviewTests(unittest.TestCase):
    def review(self, rows, points, end='2026-09-09', observed='2026-09-01', calendar=None, as_of='2026-09-09'):
        return review_points(rows, observed, end, validate_points(points), calendar or weekdays(), as_of=as_of)

    def test_each_status_and_no_lookahead(self):
        mapping={'2026-09-01':10,'2026-09-02':10,'2026-09-03':80,'2026-09-04':90}
        appeared=self.review(closes(mapping), [metric()], end='2026-09-04', as_of='2026-09-04')[0]
        self.assertEqual(appeared['status'],'appeared')
        self.assertEqual(appeared['first_seen_date'],'2026-09-03')
        self.assertEqual(appeared['value_at_first_seen'],80)
        self.assertEqual(appeared['phrase'],'已出现（首次 2026-09-03，当日取值 80）')
        quiet=self.review(closes({day:10 for day in weekdays()}), [metric()], end='2026-09-04', as_of='2026-09-04')[0]
        self.assertEqual(quiet['status'],'not_appeared')
        self.assertEqual(quiet['checked_days'],3)
        self.assertEqual(quiet['phrase'],'未出现（已核对 3 个交易日）')
        pending=self.review(closes(mapping), [metric()], end='2026-09-01', as_of='2026-09-09')[0]
        self.assertEqual(pending['status'],'pending')
        self.assertEqual(pending['phrase'],'尚未到期')
        manual=self.review(closes(mapping), [{'kind':'text','subject':'下一份财报预约披露日'}], end='2026-09-04')[0]
        self.assertEqual(manual['status'],'manual')
        self.assertEqual(manual['phrase'],'需自行核对')
        self.assertEqual(manual['checked_days'],0)
        gapped=self.review([bar('2026-09-01',10), bar('2026-09-02',10), bar('2026-09-04',10)], [metric(value=100)], end='2026-09-04', as_of='2026-09-04')[0]
        self.assertEqual(gapped['status'],'data_missing')
        self.assertEqual(gapped['phrase'],'数据缺失')
        self.assertNotEqual(gapped['status'],'not_appeared')
        short=self.review([bar(weekdays()[i], 10+i) for i in range(5)], [metric(metric='rsi14', value=30)], end='2026-09-08', as_of='2026-09-08')[0]
        self.assertEqual(short['status'],'data_missing')
        self.assertEqual(short['checked_days'],0)
        later=self.review([bar('2026-09-01',10), bar('2026-09-02',80), bar('2026-09-04',10)], [metric()], end='2026-09-04', as_of='2026-09-04')[0]
        self.assertEqual(later['status'],'appeared')
        self.assertEqual(later['first_seen_date'],'2026-09-02')
        self.assertEqual(later['value_at_first_seen'],80)

    def test_streak_halt_and_no_future_bars(self):
        streak_rows=closes({'2026-09-01':10,'2026-09-02':10,'2026-09-03':80,'2026-09-04':10,'2026-09-07':80,'2026-09-08':81,'2026-09-09':82})
        hit=self.review(streak_rows, [metric(days=3)])[0]
        self.assertEqual(hit['status'],'appeared')
        self.assertEqual(hit['first_seen_date'],'2026-09-09')
        self.assertEqual(hit['value_at_first_seen'],82)
        isolated=self.review(closes({'2026-09-01':10,'2026-09-02':80,'2026-09-03':10}), [metric(days=2)], end='2026-09-03', as_of='2026-09-03')[0]
        self.assertEqual(isolated['status'],'not_appeared')
        broken=self.review([bar('2026-09-02',80), bar('2026-09-04',80)], [metric(days=2)], end='2026-09-04', as_of='2026-09-04')[0]
        self.assertEqual(broken['status'],'data_missing')
        self.assertIsNone(broken['first_seen_date'])
        pair=[bar('2026-09-02',80), bar('2026-09-03',80)]
        joined=self.review([bar('2026-09-01',10), *pair], [metric(days=2)], end='2026-09-03', as_of='2026-09-03')[0]
        self.assertEqual(joined['status'],'appeared')
        self.assertEqual(joined['first_seen_date'],'2026-09-03')
        halt_rows=[bar('2026-09-01',10), bar('2026-09-03',30)]
        self.assertEqual(technical(halt_rows)['change1'],200)
        halt=review_points(halt_rows,'2026-09-01','2026-09-03', validate_points([metric(metric='change1', value=100), metric(value=15)]), ['2026-09-01','2026-09-02','2026-09-03'], as_of='2026-09-03')
        self.assertEqual(halt[0]['status'],'data_missing')
        self.assertEqual(halt[1]['status'],'appeared')
        self.assertEqual(halt[1]['first_seen_date'],'2026-09-03')
        self.assertEqual(halt[1]['value_at_first_seen'],30)
        calendar=['2026-09-01','2026-09-02','2026-09-03','2026-09-04']
        rows=closes({'2026-09-01':10,'2026-09-02':10,'2026-09-03':10,'2026-09-04':100})
        seen=[]
        real=technical
        def spy(window):
            seen.append([row.get('date') for row in window])
            self.assertTrue(all(row.get('date','')<='2026-09-03' for row in window))
            return real(window)
        with patch('watch_points.technical', spy):
            leaked=review_points(rows,'2026-09-01','2026-09-03', validate_points([metric(value=50)]), calendar, as_of='2026-09-03')[0]
        self.assertEqual(leaked['status'],'not_appeared')
        self.assertTrue(seen)
        self.assertTrue(all('2026-09-04' not in days for days in seen))
        clipped=self.review(closes({'2026-09-01':10,'2026-09-02':10,'2026-09-03':10,'2026-09-04':80}), [metric()], end='2026-09-09', as_of='2026-09-03')[0]
        self.assertEqual(clipped['status'],'not_appeared')
        self.assertIsNone(clipped['first_seen_date'])


class FollowupRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Tracking(Path(self.tmp.name)/'records.sqlite3')
        self.market=Mock()
        self.market.calendar.return_value=['2026-09-17','2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25']
        def quote(day, price):
            return {'date_ms':int(dt.datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()*1000),'close_price':price,'open_price':price,'high_price':price,'low_price':price,'volume':1000}
        self.market.get.return_value={'item':[quote('2026-09-17',10), quote('2026-09-18',11), quote('2026-09-21',20), quote('2026-09-24',9)]}
        saved=self.store.save({'thscode':'600487.SH','name':'测试','date':'2026-09-17','note':'核对条件','watch_points':[metric(value=15)]})
        self.oid=saved['items'][0]['id']
        self.http=ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.http.demo=None
        self.http.market=self.market
        self.http.tracking=self.store
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.shutdown)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.tmp.cleanup)

    def request(self, path):
        connection=HTTPConnection('127.0.0.1', self.http.server_port, timeout=10)
        connection.request('GET', path)
        response=connection.getresponse()
        body=json.loads(response.read())
        status=response.status
        connection.close()
        return status, body

    def test_without_id_matches_previous_shape(self):
        direct=followup(self.market,'600487.SH','2026-09-17','2026-09-24')
        self.assertEqual(set(direct), {'items','baseline','observed','end'})
        self.assertNotIn('watch_review', direct)
        status, body=self.request('/api/followup?code=600487.SH&observed=2026-09-17&date=2026-09-24')
        self.assertEqual(status, 200)
        self.assertEqual(body, direct)
        status, empty=self.request('/api/followup?code=600487.SH&observed=2026-09-17&date=2026-09-24&id=')
        self.assertEqual(status, 200)
        self.assertEqual(empty, direct)
        class Boom:
            def list(self):
                raise AssertionError('不带 id 时不应读取观察记录')
        again=followup(self.market,'600487.SH','2026-09-17','2026-09-24', observation_id=None, tracking=Boom())
        self.assertEqual(set(again), {'items','baseline','observed','end'})
        self.market.get.reset_mock()
        followup(self.market,'600487.SH','2026-09-17','2026-09-17', observation_id=self.oid, tracking=self.store)
        self.market.get.assert_not_called()

    def test_with_id_adds_review_and_keeps_price_grid(self):
        plain=followup(self.market,'600487.SH','2026-09-17','2026-09-24')
        self.market.get.reset_mock()
        status, body=self.request(f'/api/followup?code=600487.SH&observed=2026-09-17&date=2026-09-24&id={self.oid}')
        self.assertEqual(status, 200)
        self.assertEqual(body['items'], plain['items'])
        self.assertEqual(body['baseline'], plain['baseline'])
        self.assertEqual(body['observed'],'2026-09-17')
        self.assertEqual(body['end'],'2026-09-24')
        review=body['watch_review']['items'][0]
        self.assertEqual(review['status'],'appeared')
        self.assertEqual(review['first_seen_date'],'2026-09-21')
        self.assertEqual(review['value_at_first_seen'],20)
        self.assertIn('历史日不等于当时快照', body['watch_review']['note'])
        self.assertIn('历史补记不视为事前判断', body['watch_review']['note'])
        for call in self.market.get.call_args_list:
            self.assertEqual(call.args[0],'prices/historical')
            self.assertEqual(call.args[1]['adjust'],'forward')
            self.assertEqual(call.args[1]['interval'],'1d')
        self.assertGreaterEqual(len(self.market.get.call_args_list), 2)
        status, mismatch=self.request(f'/api/followup?code=000001.SZ&observed=2026-09-17&date=2026-09-24&id={self.oid}')
        self.assertEqual(status, 502)
        self.assertEqual(mismatch['error'],'观察记录与股票不一致。')
        with self.assertRaises(DataError) as missing:
            followup(self.market,'600487.SH','2026-09-17','2026-09-24', observation_id='missing', tracking=self.store)
        self.assertEqual(str(missing.exception),'观察记录不存在。')
        with self.assertRaises(DataError) as lost:
            followup(self.market,'600487.SH','2026-09-17','2026-09-24', observation_id=self.oid, tracking=None)
        self.assertEqual(str(lost.exception),'未找到观察记录。')


class WorkbenchWatchTests(unittest.TestCase):
    def test_summary_carries_watch_points_and_old_rows_stay_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=Tracking(root/'records.sqlite3')
            analysis=Analysis(root/'reports.sqlite3', None, None, None, None)
            store.save({'thscode':'600487.SH','name':'测试股票','date':'2026-09-22','note':'旧的纯文本'})
            item=summary(store, analysis, '2026-09-23')['items'][0]
            self.assertEqual(item['watch_points'],[])
            self.assertEqual(item['note'],'旧的纯文本')
            older=validate_points([metric(id='older', value=1)])
            newer=validate_points([metric(id='newer', metric='rsi14', value=70)])
            store.save({'thscode':'600487.SH','name':'测试股票','date':'2026-09-22','note':'较早','watch_points':older})
            store.save({'thscode':'600487.SH','name':'测试股票','date':'2026-09-23','note':'较近','watch_points':newer})
            latest=summary(store, analysis, '2026-09-23')['items'][0]
            self.assertEqual(latest['watch_points'][0]['id'],'newer')
            self.assertEqual(latest['note'],'较近')
            self.assertEqual(len(latest['watch_points']),1)
