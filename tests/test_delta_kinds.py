"""P3 对比展示：类型标签、材料清单、价格着色数据、过程并排。不改 compare 契约。"""
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from analysis import Analysis
from compare import METRICS, compare_reports
from demo import Demo
from report_compare import (BACKFILL_NOTE, MARK_INCOMPARABLE, MARK_PROMPT, PROCESS_NOTE,
                            delta_view, notice_view, process_view)
from server import Handler

ROOT = Path(__file__).resolve().parents[1]
COMPARE_KEYS = {
    "compare_version", "status", "comparable", "reasons", "selection",
    "baseline", "current", "deltas", "labels", "notes",
}
NUMERIC_DELTA_KEYS = {
    "metric", "unit", "old", "new", "diff", "direction", "score_direction", "comparable", "note",
}


def _base(day="2026-03-21", **technical):
    values = dict(close=10, change1=1, change20=5, bias20=2, volume_ratio5=1.2, rsi14=55,
                  ma5=10, ma10=9, ma20=8, ma60=7, macd_dif=.1, macd_dea=.05, macd_hist=.1,
                  sample=80, asof=day, method="same-method")
    values.update(technical)
    return dict(code="600487.SH", date=day, generated_at=day + "T16:00:00+08:00",
                prompt_version="v1", technical=values)


class DeltaKindTests(unittest.TestCase):
    def view(self, old, new=None, order=None):
        raw = compare_reports(old, new or _base())
        return raw, delta_view(raw, order) if order else delta_view(raw)

    def test_kind_branches_keep_missing_as_none(self):
        raw = {
            "status": "limited", "comparable": True, "reasons": [], "selection": {}, "notes": [],
            "deltas": [
                {"metric": "close", "old": 10, "new": 12, "diff": 2, "direction": "up", "comparable": True},
                {"metric": "change1", "old": 1, "new": 1, "diff": 0, "direction": "flat", "comparable": True},
                {"metric": "change20", "old": None, "new": 4, "diff": None, "direction": "one_missing", "comparable": False},
                {"metric": "bias20", "old": 2, "new": None, "diff": None, "direction": "one_missing", "comparable": False},
                {"metric": "volume_ratio5", "old": None, "new": None, "diff": None, "direction": "both_missing", "comparable": False},
                {"metric": "rsi14", "old": 40, "new": 55, "diff": 15, "direction": "window_sensitive", "comparable": True, "display": "value_only"},
                {"metric": "macd_hist", "old": .1, "new": .2, "diff": .1, "direction": "not_comparable", "comparable": False, "display": "hidden_direction"},
                {"metric": "sample", "old": 0, "new": 80, "diff": 80, "direction": "up", "comparable": True},
                {"metric": "ma5", "old": None, "new": 9, "diff": None, "direction": "one_missing", "comparable": False, "display": "hidden_direction"},
                {"metric": "ma20", "old": 0, "new": 0, "diff": 0, "direction": "flat", "comparable": True},
                {"metric": "macd_dif", "old": None, "new": None, "diff": None, "direction": "both_missing", "comparable": False, "display": "hidden_direction"},
            ],
        }
        rows = {r["metric"]: r for r in delta_view(raw, [d["metric"] for d in raw["deltas"]])["rows"]}
        self.assertEqual((rows["close"]["kind"], rows["close"]["kind_label"]), ("changed", "变了"))
        self.assertEqual((rows["change1"]["kind"], rows["change1"]["kind_label"]), ("unchanged", "没变"))
        self.assertEqual((rows["change20"]["kind"], rows["change20"]["kind_label"]), ("added", "新增"))
        self.assertIsNone(rows["change20"]["old"])
        self.assertIsNone(rows["change20"]["diff"])
        self.assertEqual(rows["change20"]["new"], 4)
        self.assertEqual((rows["bias20"]["kind"], rows["bias20"]["kind_label"]), ("removed", "消失"))
        self.assertIsNone(rows["bias20"]["new"])
        self.assertEqual((rows["volume_ratio5"]["kind"], rows["volume_ratio5"]["kind_label"]), ("both_missing", "双方缺失"))
        self.assertIsNone(rows["volume_ratio5"]["old"])
        self.assertIsNone(rows["volume_ratio5"]["new"])
        self.assertIsNone(rows["volume_ratio5"]["diff"])
        self.assertEqual((rows["rsi14"]["kind"], rows["rsi14"]["kind_label"]), ("incomparable", "窗口不同"))
        self.assertEqual((rows["macd_hist"]["kind"], rows["macd_hist"]["kind_label"]), ("incomparable", "不可比"))
        self.assertEqual(rows["sample"]["old"], 0)
        self.assertEqual(rows["sample"]["kind"], "changed")
        self.assertEqual((rows["ma5"]["kind"], rows["ma5"]["kind_label"]), ("incomparable", "不可比"))
        self.assertIsNone(rows["ma5"]["old"])
        self.assertEqual((rows["ma20"]["kind"], rows["ma20"]["old"]), ("unchanged", 0))
        self.assertEqual(rows["macd_dif"]["kind"], "both_missing")
        self.assertIsNone(rows["macd_dif"]["old"])
        self.assertIsNone(rows["macd_dif"]["new"])
        for row in rows.values():
            self.assertNotEqual(row["old"], 0) if row["old"] is None else None
            self.assertNotEqual(row["new"], 0) if row["new"] is None else None

    def test_real_compare_window_and_method_kinds(self):
        raw, view = self.view(_base("2026-03-20", sample=250, close=9), _base(close=10))
        kinds = {r["metric"]: r for r in view["rows"]}
        self.assertEqual(kinds["close"]["kind"], "changed")
        self.assertEqual(kinds["rsi14"]["direction"], "window_sensitive")
        self.assertEqual((kinds["rsi14"]["kind"], kinds["rsi14"]["kind_label"]), ("incomparable", "窗口不同"))
        self.assertEqual(kinds["macd_hist"]["kind_label"], "窗口不同")
        self.assertNotIn("kind", raw["deltas"][0])
        raw, view = self.view(_base("2026-03-20", method="other-method"))
        self.assertTrue(all(r["kind"] == "incomparable" and r["kind_label"] == "不可比" for r in view["rows"]))
        self.assertTrue(all(r["hide_direction"] for r in view["rows"]))

    def test_metric_class_reserves_price_for_close_and_changes(self):
        _, view = self.view(_base("2026-03-20"), order=[m[0] for m in METRICS] + ["trend"])
        classes = {r["metric"]: r["metric_class"] for r in view["rows"]}
        self.assertEqual({k for k, v in classes.items() if v == "price"}, {"close", "change1", "change20"})
        self.assertEqual(classes["volume_ratio5"], "volume")
        self.assertEqual(classes["sample"], "count")
        for key in ("bias20", "rsi14", "macd_hist", "macd_dif", "macd_dea", "ma5", "ma20", "ma60"):
            self.assertEqual(classes[key], "indicator", key)
        self.assertNotIn("trend", classes)

    def test_compare_reports_keys_stay_on_the_contract(self):
        schema = json.loads((ROOT / "contracts" / "compare.schema.json").read_text())
        self.assertEqual(schema["required"], [
            "compare_version", "status", "comparable", "reasons", "selection",
            "baseline", "current", "deltas", "labels", "notes"])
        self.assertEqual(schema["properties"]["deltas"]["items"]["properties"]["direction"]["enum"], [
            "up", "down", "flat", "one_missing", "both_missing", "not_comparable", "window_sensitive"])
        for old in (None, _base("2026-03-20"), _base("2026-03-20", sample=250), _base("2026-03-20", method="other")):
            result = compare_reports(old, _base())
            self.assertEqual(set(result), COMPARE_KEYS)
            self.assertNotIn("notices", result)
            self.assertNotIn("process", result)
            for row in result["deltas"]:
                self.assertNotIn("kind", row)
                self.assertNotIn("metric_class", row)
        plain = compare_reports(_base("2026-03-20", close=9), _base())
        close = next(r for r in plain["deltas"] if r["metric"] == "close")
        self.assertTrue(NUMERIC_DELTA_KEYS <= set(close))
        self.assertEqual(close["direction"], "up")


class NoticeViewTests(unittest.TestCase):
    def test_added_removed_and_unchanged_by_id(self):
        old = {"disclosures": {"items": [
            {"id": "a", "title": "年报", "notice_date": "2026-03-01"},
            {"id": "b", "title": "更正前", "notice_date": "2026-03-02"},
            {"id": 7, "title": "数字编号", "notice_date": "2026-02-01"},
        ]}}
        new = {"disclosures": {"items": [
            {"id": "b", "title": "更正后", "notice_date": "2026-03-02"},
            {"id": "c", "title": "<新公告>", "notice_date": "2026-03-03"},
            {"id": "7", "title": "数字编号", "notice_date": "2026-02-01"},
        ]}}
        view = notice_view(old, new, backfilled=True)
        self.assertEqual([(r["id"], r["kind"], r["kind_label"]) for r in view["items"]], [
            ("c", "added", "新增"), ("a", "removed", "消失"),
            ("7", "unchanged", "没变"), ("b", "unchanged", "没变"),
        ])
        self.assertEqual(view["items"][0]["title"], "<新公告>")
        self.assertEqual(view["items"][3]["title"], "更正后")
        self.assertIn("所存材料清单的变化", view["summary"])
        self.assertIn("不判断利好或利空", view["summary"])
        self.assertEqual(view["note"], BACKFILL_NOTE)
        self.assertEqual(notice_view(old, new)["note"], "")

    def test_missing_disclosures_are_suppressed_not_empty_diff(self):
        cases = (
            ({}, {}),
            (None, None),
            ({"disclosures": None}, {"date": "2026-03-20"}),
            ({"disclosures": []}, {"disclosures": {"items": "bad"}}),
            ({"disclosures": {"items": [None, "x", {"title": "无编号"}]}}, {"disclosures": {"items": None}}),
        )
        for old, new in cases:
            with self.subTest(old=old, new=new):
                view = notice_view(old, new)
                self.assertEqual(view["items"], [])
                self.assertFalse(view.get("comparable", True))
                self.assertNotIn("消失", view["summary"])
                self.assertNotIn("新增 0 项", view["summary"])
                self.assertTrue(view["summary"])


class ProcessViewTests(unittest.TestCase):
    def item(self, identifier, day, created=None, status="complete", code="600487.SH", **changes):
        report = {
            "code": code, "date": day,
            "generated_at": changes.pop("generated_at", day + "T16:00:00+08:00"),
            "prompt_version": changes.pop("prompt_version", "v1"),
            "technical": {"sample": changes.pop("sample", 80), "close": changes.pop("close", 10),
                          "method": changes.pop("method", "same-method"), "asof": day},
            "assessment": changes.pop("assessment", {"rule_version": "r1", "meta": {"context": {"window": 250}}}),
            "ai": changes.pop("ai", None), "model": changes.pop("model", None),
        }
        for key in changes.pop("drop", ()):
            report.pop(key, None)
        if "technical_drop" in changes:
            for key in changes.pop("technical_drop"):
                report["technical"].pop(key, None)
        report.update(changes)
        return {"id": identifier, "code": code, "day": day,
                "created": created or day + "T16:00:00+08:00", "status": status, "report": report}

    def test_limits_to_four_without_future_or_later_same_day(self):
        current = self.item("cur", "2026-03-10", "2026-03-10T12:00:00+08:00")
        items = [self.item("d" + str(n), f"2026-03-0{n}") for n in range(1, 7)]
        items += [
            self.item("earlier", "2026-03-10", "2026-03-10T09:00:00+08:00"),
            self.item("same-created", "2026-03-10", "2026-03-10T12:00:00+08:00"),
            self.item("later", "2026-03-10", "2026-03-10T18:00:00+08:00", close=11),
            self.item("future", "2026-03-11", close=12),
            self.item("other", "2026-03-09", code="000001.SZ"),
            self.item("draft", "2026-03-08", status="running"),
            self.item("bad", "2026-03-07", sample=0, close=None),
            current,
        ]
        view = process_view(items, "cur")
        self.assertEqual(PROCESS_NOTE, view["note"])
        self.assertEqual([c["id"] for c in view["columns"]], ["d6", "earlier", "same-created", "cur"])
        self.assertTrue(view["columns"][-1]["current"])
        self.assertNotIn("future", [c["id"] for c in view["columns"]])
        self.assertNotIn("later", [c["id"] for c in view["columns"]])
        self.assertLessEqual(len(view["columns"]), 4)

    def test_method_prompt_missing_backfill_and_ai(self):
        current = self.item("cur", "2026-03-21", prompt_version="v2", method="本次方法",
                            assessment={"rule_version": "r2", "window": 250},
                            generated_at="2026-03-21T16:00:00+08:00", ai={"overview": [{"text": "状态"}]}, model=None)
        other = self.item("old", "2026-03-20", method="另一方法" + "乙" * 80, prompt_version="v1",
                          assessment={"rule_version": "r1", "meta": {"context": {"window": 80}}},
                          generated_at="2026-03-22T01:00:00+08:00", ai=None, model=None)
        bare = self.item("bare", "2026-03-19", drop=("assessment", "ai", "model", "prompt_version", "generated_at"),
                         technical_drop=("method",))
        none_ai = self.item("none-ai", "2026-03-17", ai=None, model=None)
        view = process_view([none_ai, bare, other, current], "cur")
        by = {c["id"]: c for c in view["columns"]}
        self.assertEqual(by["old"]["marks"], [MARK_INCOMPARABLE, MARK_PROMPT])
        self.assertTrue(by["old"]["method_incomparable"])
        self.assertTrue(by["old"]["prompt_differs"])
        self.assertNotIn("乙" * 80, by["old"]["cells"]["method"])
        self.assertIn("与本次不同", by["old"]["cells"]["method"])
        self.assertLess(len(by["old"]["cells"]["method"]), 90)
        self.assertIn("规则版本与本次不同", by["old"]["cells"]["window"])
        self.assertNotIn(MARK_INCOMPARABLE, by["old"]["cells"]["window"])
        self.assertEqual(by["old"]["cells"]["backfilled"], "是")
        self.assertEqual(by["old"]["cells"]["ai"], "不含 AI")
        self.assertEqual(by["cur"]["marks"], [])
        self.assertEqual(by["cur"]["cells"]["method"], "与本次相同")
        self.assertEqual(by["cur"]["cells"]["ai"], "含 AI")
        self.assertEqual(by["cur"]["cells"]["backfilled"], "否")
        self.assertEqual(by["cur"]["cells"]["window"], "窗口 250 · 规则 r2")
        self.assertEqual(by["bare"]["cells"]["method"], "未记录")
        self.assertEqual(by["bare"]["cells"]["window"], "未记录")
        self.assertEqual(by["bare"]["cells"]["ai"], "未记录")
        self.assertEqual(by["bare"]["cells"]["backfilled"], "未记录")
        self.assertEqual(by["bare"]["cells"]["prompt_version"], "未记录")
        self.assertEqual(by["bare"]["marks"], [MARK_PROMPT])
        self.assertFalse(by["bare"]["method_incomparable"])
        self.assertEqual(by["none-ai"]["cells"]["ai"], "不含 AI")
        utc = process_view([
            self.item("utc", "2026-03-18", generated_at="2026-03-18T16:30:00Z", ai=None, model="demo-model"),
            self.item("cur2", "2026-03-21", prompt_version="v1", method="same-method"),
        ], "cur2")
        utc_col = utc["columns"][0]
        self.assertEqual(utc_col["cells"]["backfilled"], "是")
        self.assertEqual(utc_col["cells"]["ai"], "含 AI")
        self.assertEqual(utc_col["marks"], [])
        self.assertIn("样本", [r["label"] for r in view["rows"]])
        self.assertEqual(by["cur"]["cells"]["sample"], "80")

    def test_prompt_difference_is_not_an_overall_incomparable_mark(self):
        current = self.item("cur", "2026-03-21", prompt_version="new")
        old = self.item("old", "2026-03-20", prompt_version="old")
        column = process_view([old, current], "cur")["columns"][0]
        self.assertEqual(column["marks"], [MARK_PROMPT])
        self.assertFalse(column["method_incomparable"])
        self.assertNotIn(MARK_INCOMPARABLE, column["marks"])

    def test_unknown_current_is_empty(self):
        view = process_view([self.item("a", "2026-03-20")], "missing")
        self.assertEqual(view["columns"], [])
        self.assertEqual(view["note"], PROCESS_NOTE)


class BuildDeltaCompatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.analysis = Analysis(Path(self.tmp.name) / "reports.sqlite3", None, None, None, None)

    def tearDown(self):
        self.tmp.cleanup()

    def insert(self, identifier, day, created=None, payload=None, status="complete"):
        created = created or day + "T16:00:00+08:00"
        body = payload if payload is not None else _base(day)
        with self.analysis.db() as db:
            db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)",
                       (identifier, "600487.SH", day, created, status, "done", json.dumps(body), None))
        return json.dumps(body)

    def test_old_payload_does_not_raise_and_raw_stays_plain(self):
        legacy = {"code": "600487.SH", "date": "2026-03-20", "technical": {"sample": 80, "close": 9, "method": "same-method"}}
        encoded = self.insert("old", "2026-03-20", payload=legacy)
        current = _base("2026-03-21")
        current["disclosures"] = {"items": [{"id": "n1", "title": "补充材料", "notice_date": "2026-03-18"}]}
        current["technical"]["change1"] = None
        self.insert("cur", "2026-03-21", payload=current)
        self.insert("future", "2026-03-22", payload=_base("2026-03-22"))
        delta = self.analysis.get("cur")["delta"]
        self.assertIsNotNone(delta)
        self.assertEqual(set(delta["raw"]), COMPARE_KEYS)
        self.assertNotIn("notices", delta["raw"])
        self.assertNotIn("kind", delta["raw"]["deltas"][0])
        change = next(r for r in delta["rows"] if r["metric"] == "change1")
        self.assertIsNone(change["old"])
        self.assertIsNone(change["new"])
        self.assertIsNone(change["diff"])
        self.assertEqual(change["kind"], "both_missing")
        # Legacy baseline has no disclosures field: suppress清单差, do not claim "added".
        self.assertEqual(delta["notices"]["items"], [])
        self.assertFalse(delta["notices"]["comparable"])
        self.assertIn("此前报告", delta["notices"]["summary"])
        self.assertNotIn("future", [c["id"] for c in delta["process"]["columns"]])
        self.assertIn("cur", [c["id"] for c in delta["process"]["columns"]])
        self.assertLessEqual(len(delta["process"]["columns"]), 4)
        with self.analysis.db() as db:
            self.assertEqual(db.execute("SELECT payload FROM reports WHERE id=?", ("old",)).fetchone()[0], encoded)

    def test_notice_changes_and_backfill_note_come_from_saved_reports(self):
        old = _base("2026-03-20")
        old["generated_at"] = "2026-03-25T10:00:00+08:00"
        old["disclosures"] = {"items": [
            {"id": "keep", "title": "保留", "notice_date": "2026-03-01"},
            {"id": "gone", "title": "不再列入", "notice_date": "2026-02-01"},
        ]}
        new = _base("2026-03-21")
        new["generated_at"] = "2026-03-21T16:00:00+08:00"
        new["disclosures"] = {"items": [
            {"id": "keep", "title": "保留", "notice_date": "2026-03-01"},
            {"id": "new", "title": "新材料", "notice_date": "2026-03-11"},
        ]}
        self.insert("old", "2026-03-20", payload=old)
        self.insert("cur", "2026-03-21", payload=new)
        delta = self.analysis.get("cur")["delta"]
        self.assertEqual([(n["id"], n["kind"]) for n in delta["notices"]["items"]],
                         [("new", "added"), ("gone", "removed"), ("keep", "unchanged")])
        self.assertEqual(delta["notices"]["note"], BACKFILL_NOTE)
        self.assertTrue(delta["raw"]["selection"]["backfilled_baseline"])
        columns = {c["id"]: c for c in delta["process"]["columns"]}
        self.assertEqual(columns["old"]["cells"]["backfilled"], "是")
        self.assertEqual(columns["cur"]["cells"]["backfilled"], "否")

    def test_view_attachments_fail_open(self):
        self.insert("old", "2026-03-20", payload=_base("2026-03-20", close=9))
        self.insert("cur", "2026-03-21")
        with patch("report_compare.process_view", side_effect=RuntimeError("process failed")):
            delta = self.analysis.get("cur")["delta"]
        self.assertEqual(delta["rows"][0]["metric"], "close")
        self.assertNotIn("process", delta)
        self.assertIn("notices", delta)
        self.assertIn("raw", delta)
        with patch("report_compare.notice_view", side_effect=RuntimeError("notice failed")):
            delta = self.analysis.get("cur")["delta"]
        self.assertNotIn("notices", delta)
        self.assertIn("process", delta)
        self.assertIn("rows", delta)


class DemoDeltaShapeTests(unittest.TestCase):
    def test_demo_delta_has_kinds_without_notices_and_post_stays_forbidden(self):
        demo = Demo()
        report = demo.report("600000.SH", demo.day)
        rows = report["delta"]["rows"]
        self.assertTrue(rows)
        self.assertTrue(all(r.get("kind") and r.get("kind_label") and r.get("metric_class") for r in rows))
        self.assertEqual({r["metric"] for r in rows if r["metric_class"] == "price"}, {"close", "change1", "change20"})
        self.assertNotIn("notices", report["delta"])
        self.assertNotIn("process", report["delta"])
        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        http.demo = demo
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.shutdown)
        self.addCleanup(http.server_close)
        conn = HTTPConnection("127.0.0.1", http.server_port, timeout=10)
        conn.request("POST", "/api/analysis", "{}", headers={
            "Host": f"127.0.0.1:{http.server_port}", "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{http.server_port}"})
        response = conn.getresponse()
        body = json.loads(response.read())
        self.assertEqual(response.status, 403)
        self.assertEqual(body["reason"], "demo_read_only")
        conn.close()
        conn = HTTPConnection("127.0.0.1", http.server_port, timeout=10)
        conn.request("GET", "/api/analysis?id=" + report["id"], headers={"Host": f"127.0.0.1:{http.server_port}"})
        got = json.loads(conn.getresponse().read())
        conn.close()
        self.assertEqual(got["delta"]["rows"][0]["metric_class"], report["delta"]["rows"][0]["metric_class"])
        self.assertNotIn("notices", got["delta"])


class DeltaStyleGuardTests(unittest.TestCase):
    def test_undefined_delta_color_classes_stay_unused(self):
        css = (ROOT / "web" / "style.css").read_text()
        script = (ROOT / "web" / "analysis.js").read_text()
        display = (ROOT / "web" / "delta-display.js").read_text()
        self.assertIn(".delta-na{color:var(--muted)}", css)
        self.assertIn(".delta-kind{", css)
        self.assertNotIn(".delta-up", css)
        self.assertNotIn(".delta-down", css)
        self.assertNotIn(".delta-flat", css)
        for name in ("delta-up", "delta-down", "delta-flat"):
            self.assertNotIn(name, script)
            self.assertNotIn(name, display)
        self.assertIn("DeltaDisplay.deltaToneClass", script)
        self.assertIn("quote-up", display)
        self.assertIn("quote-down", display)
        self.assertIn(".quote-up{color:#cd4b43}", css)
        self.assertIn(".quote-down{color:#207452}", css)
        for word in ("应买", "应卖", "看多", "看空", "目标价", "胜率", "上涨概率"):
            self.assertNotIn(word, (ROOT / "report_compare.py").read_text())
