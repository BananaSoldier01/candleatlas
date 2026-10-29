"""Regressions from the 2026-10-29 joint review of PR #6 / #7."""
import datetime as dt
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

from market import DataError, TZ
from server import Handler
from tracking import Tracking, followup
from watch_points import review_points, validate_points


def metric(**extra):
    point={'kind':'metric','metric':'close','op':'>=','value':20}
    point.update(extra)
    return point


def bar(day, close, volume=1000):
    return {'date':day,'open_price':close,'high_price':close,'low_price':close,'close_price':close,'volume':volume}


class IntradayConditionTests(unittest.TestCase):
    """Disk-day bars before 16:00 must not confirm appeared / not_appeared."""

    def review(self, rows, points, observed, end, as_of, now, calendar):
        return review_points(rows, observed, end, validate_points(points), calendar, as_of=as_of, now=now)

    def test_intraday_threshold_is_not_confirmed(self):
        calendar=['2026-02-25','2026-02-26','2026-02-27']
        rows=[bar('2026-02-25',10), bar('2026-02-26',15), bar('2026-02-27',25)]
        now=dt.datetime(2026,2,27,10,0,tzinfo=TZ)
        item=self.review(rows, [metric()], '2026-02-26', '2026-02-27', '2026-02-27', now, calendar)[0]
        self.assertEqual(item['status'],'intraday')
        self.assertEqual(item['phrase'],'盘中未定稿')
        self.assertIsNone(item['first_seen_date'])
        self.assertEqual(item['checked_days'],0)

    def test_intraday_non_hit_is_also_not_not_appeared(self):
        calendar=['2026-02-25','2026-02-26','2026-02-27']
        rows=[bar('2026-02-25',10), bar('2026-02-26',15), bar('2026-02-27',18)]
        now=dt.datetime(2026,2,27,10,0,tzinfo=TZ)
        item=self.review(rows, [metric()], '2026-02-26', '2026-02-27', '2026-02-27', now, calendar)[0]
        self.assertEqual(item['status'],'intraday')
        self.assertNotEqual(item['status'],'not_appeared')
        self.assertNotEqual(item['status'],'appeared')

    def test_after_close_same_bar_can_confirm(self):
        calendar=['2026-02-25','2026-02-26','2026-02-27']
        rows=[bar('2026-02-25',10), bar('2026-02-26',15), bar('2026-02-27',25)]
        now=dt.datetime(2026,2,27,16,0,tzinfo=TZ)
        item=self.review(rows, [metric()], '2026-02-26', '2026-02-27', '2026-02-27', now, calendar)[0]
        self.assertEqual(item['status'],'appeared')
        self.assertEqual(item['first_seen_date'],'2026-02-27')
        self.assertEqual(item['value_at_first_seen'],25)

    def test_prior_finalized_hit_is_kept(self):
        calendar=['2026-02-24','2026-02-25','2026-02-26','2026-02-27']
        rows=[bar('2026-02-24',10), bar('2026-02-25',22), bar('2026-02-26',15), bar('2026-02-27',30)]
        now=dt.datetime(2026,2,27,10,0,tzinfo=TZ)
        item=self.review(rows, [metric()], '2026-02-24', '2026-02-27', '2026-02-27', now, calendar)[0]
        self.assertEqual(item['status'],'appeared')
        self.assertEqual(item['first_seen_date'],'2026-02-25')
        self.assertEqual(item['value_at_first_seen'],22)

    def test_streak_does_not_complete_on_intraday_bar(self):
        calendar=['2026-02-24','2026-02-25','2026-02-26','2026-02-27']
        rows=[bar('2026-02-24',10), bar('2026-02-25',10), bar('2026-02-26',22), bar('2026-02-27',23)]
        now=dt.datetime(2026,2,27,11,0,tzinfo=TZ)
        item=self.review(rows, [metric(days=2)], '2026-02-25', '2026-02-27', '2026-02-27', now, calendar)[0]
        self.assertEqual(item['status'],'intraday')
        self.assertIsNone(item['first_seen_date'])
        self.assertEqual(item['checked_days'],1)

    def test_finalized_days_without_provisional_still_not_appeared(self):
        calendar=['2026-02-24','2026-02-25','2026-02-26']
        rows=[bar('2026-02-24',10), bar('2026-02-25',11), bar('2026-02-26',12)]
        now=dt.datetime(2026,2,27,10,0,tzinfo=TZ)
        item=self.review(rows, [metric()], '2026-02-24', '2026-02-26', '2026-02-26', now, calendar)[0]
        self.assertEqual(item['status'],'not_appeared')
        self.assertEqual(item['checked_days'],2)


class ObservationDateBindingTests(unittest.TestCase):
    """When id is present, the saved observation day is the sole authority."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Tracking(Path(self.tmp.name)/'records.sqlite3')
        self.market=Mock()
        self.market.calendar.return_value=['2026-02-24','2026-02-25','2026-02-26','2026-02-27']
        def quote(day, price):
            return {'date_ms':int(dt.datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()*1000),'close_price':price,'open_price':price,'high_price':price,'low_price':price,'volume':1000}
        self.market.get.return_value={'item':[quote('2026-02-25',10), quote('2026-02-26',11), quote('2026-02-27',25)]}
        saved=self.store.save({'thscode':'600487.SH','name':'测试','date':'2026-02-25','note':'核对条件','watch_points':[metric(value=20)]})
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

    def test_correct_date_unchanged(self):
        status, body=self.request(f'/api/followup?code=600487.SH&observed=2026-02-25&date=2026-02-27&id={self.oid}')
        self.assertEqual(status, 200)
        self.assertEqual(body['observed'],'2026-02-25')
        self.assertIn('watch_review', body)

    def test_wrong_date_uses_saved_observation_day(self):
        # Caller sends 2026-02-24; saved record is 2026-02-25. Both zones use saved.
        direct=followup(self.market,'600487.SH','2026-02-24','2026-02-27', observation_id=self.oid, tracking=self.store)
        self.assertEqual(direct['observed'],'2026-02-25')
        status, body=self.request(f'/api/followup?code=600487.SH&observed=2026-02-24&date=2026-02-27&id={self.oid}')
        self.assertEqual(status, 200)
        self.assertEqual(body['observed'],'2026-02-25')
        self.assertEqual(body['items'], direct['items'])
        self.assertEqual(body['watch_review']['items'], direct['watch_review']['items'])

    def test_wrong_stock_still_rejected(self):
        status, body=self.request(f'/api/followup?code=000001.SZ&observed=2026-02-25&date=2026-02-27&id={self.oid}')
        self.assertEqual(status, 502)
        self.assertEqual(body['error'],'观察记录与股票不一致。')

    def test_missing_id_rejected(self):
        with self.assertRaises(DataError) as caught:
            followup(self.market,'600487.SH','2026-02-25','2026-02-27', observation_id='missing', tracking=self.store)
        self.assertEqual(str(caught.exception),'观察记录不存在。')
        status, body=self.request('/api/followup?code=600487.SH&observed=2026-02-25&date=2026-02-27&id=missing')
        self.assertEqual(status, 502)
        self.assertEqual(body['error'],'观察记录不存在。')

    def test_without_id_keeps_caller_observed(self):
        plain=followup(self.market,'600487.SH','2026-02-24','2026-02-27')
        self.assertEqual(plain['observed'],'2026-02-24')
        self.assertNotIn('watch_review', plain)
        status, body=self.request('/api/followup?code=600487.SH&observed=2026-02-24&date=2026-02-27')
        self.assertEqual(status, 200)
        self.assertEqual(body['observed'],'2026-02-24')
        self.assertEqual(body, plain)



class DisclosureNoticeSuppressionTests(unittest.TestCase):
    """Failed / absent disclosures must not look like notices that disappeared."""

    def setUp(self):
        from report_compare import notice_view
        self.notice_view = notice_view

    def available(self, *items, period_end='2025-12-31'):
        return {"disclosures": {"status": "available", "period_end": period_end, "items": list(items)}}

    def test_failed_current_not_a_removed_notice(self):
        old = self.available({"id": "annual-1", "title": "合成年度报告", "notice_date": "2026-03-01"})
        new = {"disclosures": {"status": "failed", "period_end": "2025-12-31", "items": [],
                              "note": "披露资料校验未通过，暂不展示；其他分析仍可使用。"}}
        view = self.notice_view(old, new)
        self.assertEqual(view["items"], [])
        self.assertFalse(view["comparable"])
        self.assertNotIn("消失", view["summary"])
        self.assertIn("校验未通过", view["summary"])

    def test_absent_disclosures_field_not_a_removed_notice(self):
        old = self.available({"id": "annual-1", "title": "合成年度报告", "notice_date": "2026-03-01"})
        new = {"date": "2026-03-20", "technical": {}}
        view = self.notice_view(old, new)
        self.assertEqual(view["items"], [])
        self.assertFalse(view["comparable"])
        self.assertNotIn("消失", view["summary"])
        self.assertIn("未采集或未知", view["summary"])

    def test_unconfigured_and_failed_both_sides(self):
        old = {"disclosures": {"status": "unconfigured", "items": [], "period_end": "2025-12-31"}}
        new = {"disclosures": {"status": "failed", "items": [], "period_end": "2025-12-31"}}
        view = self.notice_view(old, new)
        self.assertEqual(view["items"], [])
        self.assertFalse(view["comparable"])
        self.assertNotRegex(view["summary"], r"新增 \d+ 项")
        self.assertNotRegex(view["summary"], r"消失 \d+ 项")
        self.assertIn("不能判断材料清单增减", view["summary"])

    def test_first_report_has_no_baseline_diff(self):
        new = self.available({"id": "annual-1", "title": "合成年度报告", "notice_date": "2026-03-01"})
        view = self.notice_view(None, new)
        self.assertEqual(view["items"], [])
        self.assertFalse(view["comparable"])
        self.assertIn("无更早报告", view["summary"])
        self.assertNotIn("新增 1", view["summary"])

    def test_different_period_end_suppressed(self):
        old = self.available({"id": "a", "title": "年报", "notice_date": "2025-03-01"}, period_end="2024-12-31")
        new = self.available({"id": "a", "title": "年报", "notice_date": "2026-03-01"}, period_end="2025-12-31")
        view = self.notice_view(old, new)
        self.assertEqual(view["items"], [])
        self.assertFalse(view["comparable"])
        self.assertIn("报告期不同", view["summary"])

    def test_normal_add_remove_still_works(self):
        old = self.available(
            {"id": "keep", "title": "保留", "notice_date": "2026-03-01"},
            {"id": "gone", "title": "旧材料", "notice_date": "2026-03-02"},
            period_end="2025-12-31",
        )
        new = self.available(
            {"id": "keep", "title": "保留", "notice_date": "2026-03-01"},
            {"id": "new", "title": "新材料", "notice_date": "2026-03-03"},
            period_end="2025-12-31",
        )
        view = self.notice_view(old, new)
        self.assertTrue(view["comparable"])
        kinds = {row["id"]: row["kind"] for row in view["items"]}
        self.assertEqual(kinds, {"new": "added", "gone": "removed", "keep": "unchanged"})
        self.assertIn("所存材料清单的变化", view["summary"])
