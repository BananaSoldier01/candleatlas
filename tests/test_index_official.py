import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import index_official
from index_official import (
    LICENSE_NOTE,
    fetch_constituents,
    fetch_valuation,
    fetch_weights,
    official_file_url,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "index_official"


def _read(name):
    return (FIXTURES / name).read_bytes()


def _blob(result):
    return json.dumps(result, ensure_ascii=False)


class IndexOfficialTests(unittest.TestCase):
    def test_network_off_without_bytes_is_explicit_gap(self):
        called = []

        def boom(*_args, **_kwargs):
            called.append(True)
            raise AssertionError("network")

        with patch("urllib.request.urlopen", side_effect=boom), patch("index_official._http_get", side_effect=boom):
            constituents = fetch_constituents("000300")
            weights = fetch_weights("000300.SH", provider="csi")
            valuation = fetch_valuation("SH000905", provider="CSI")
        self.assertEqual(called, [])
        for result in (constituents, weights, valuation):
            self.assertEqual(result["items"], [])
            self.assertIsNone(result["as_of"])
            self.assertEqual(result["license_note"], LICENSE_NOTE)
            self.assertTrue(result["license_note"])
            self.assertIn("不是买卖建议", " ".join(result["notes"]))
            self.assertTrue(any("allow_network=False" in gap for gap in result["gaps"]))
        self.assertEqual(constituents["source"], "csindex")
        self.assertEqual(constituents["provider"], "csi")
        self.assertEqual(weights["index_code"], "000300")
        self.assertEqual(valuation["index_code"], "000905")
        self.assertIn("closeweight/000300closeweight.xls", " ".join(weights["notes"]))
        self.assertNotIn("cnindex", " ".join(weights["gaps"]))

    def test_fixture_constituents_weights_and_valuation(self):
        constituents = fetch_constituents("000300", fetch_bytes=_read("csi_constituents.csv"))
        self.assertEqual(constituents["kind"], "constituents")
        self.assertEqual(constituents["as_of"], "2024-06-28")
        self.assertEqual([item["code"] for item in constituents["items"]], ["910001", "910002"])
        self.assertEqual(constituents["items"][0]["name"], "示例甲")
        self.assertEqual(constituents["items"][0]["exchange"], "示例交易所")
        self.assertNotIn("weight", constituents["items"][0])
        self.assertTrue(any("000905" in gap for gap in constituents["gaps"]))
        self.assertTrue(any("成分代码为空" in gap for gap in constituents["gaps"]))

        weights = fetch_weights("000300", fetch_bytes=_read("csi_weights.csv"))
        self.assertEqual([item["code"] for item in weights["items"]], ["910001", "910003", "910004"])
        self.assertEqual([item["weight"] for item in weights["items"]], [1.25, 0.0, 9.5])
        self.assertTrue(all(item["weight_unit"] == "percent" for item in weights["items"]))
        self.assertNotIn(0, [item["weight"] for item in weights["items"] if item["code"] == "910002"])
        self.assertTrue(any("910002" not in gap and "权重为空，未记为 0" in gap for gap in weights["gaps"]))
        self.assertTrue(any("无法解析，未记为 0" in gap for gap in weights["gaps"]))
        self.assertTrue(any("000905" in gap for gap in weights["gaps"]))
        self.assertNotIn("910002", [item["code"] for item in weights["items"]])

        valuation = fetch_valuation("000300", fetch_bytes=_read("csi_valuation.csv"))
        self.assertEqual(valuation["as_of"], "2024-06-28")
        self.assertEqual(len(valuation["items"]), 2)
        self.assertEqual(valuation["items"][1]["pe1"], 12.5)
        self.assertEqual(valuation["items"][1]["pe2"], 11.25)
        self.assertEqual(valuation["items"][1]["dividend_yield1"], 2.1)
        self.assertNotIn("dividend_yield2", valuation["items"][1])
        self.assertTrue(any("部分估值列为空" in gap for gap in valuation["gaps"]))
        self.assertTrue(any("估值列为空，未记为 0" in gap for gap in valuation["gaps"]))
        self.assertTrue(any("多个日期" in note for note in valuation["notes"]))
        self.assertNotIn("pe", valuation["items"][0])

    def test_bad_files_binary_html_and_stock_level(self):
        missing = fetch_weights("000300", fetch_bytes=_read("missing_weight_column.csv"))
        self.assertEqual(missing["items"], [])
        self.assertTrue(any("缺少权重列" in gap for gap in missing["gaps"]))
        self.assertNotIn("0", _blob({"items": missing["items"]}))

        same = fetch_constituents("000300", fetch_bytes=_read("missing_weight_column.csv"))
        self.assertEqual([item["code"] for item in same["items"]], ["910001", "910002"])

        binary = fetch_weights("000300", fetch_bytes=b"\xd0\xcf\x11\xe0" + b"not-a-table")
        self.assertEqual(binary["items"], [])
        self.assertTrue(any("二进制表格（xls）" in gap for gap in binary["gaps"]))
        workbook = fetch_valuation("000300", fetch_bytes=b"PK\x03\x04" + b"xlsx")
        self.assertTrue(any("二进制表格（xlsx）" in gap for gap in workbook["gaps"]))

        junk = fetch_constituents("000300", fetch_bytes="这不是表格\n没有表头\n".encode())
        self.assertEqual(junk["items"], [])
        self.assertTrue(junk["gaps"])

        html = fetch_weights("000300", fetch_bytes=_read("csi_weights.html"))
        self.assertEqual(html["as_of"], "2024-06-28")
        self.assertEqual(html["items"], [{"date": "2024-06-28", "code": "910001", "weight": 1.25, "weight_unit": "percent", "name": "示例甲"}])
        self.assertTrue(any("权重为空，未记为 0" in gap for gap in html["gaps"]))

        screened = fetch_valuation("000300", fetch_bytes=_read("stock_level_valuation.csv"))
        self.assertEqual(screened["items"], [])
        self.assertTrue(any("个股估值筛选" in gap for gap in screened["gaps"]))

    def test_cni_fixture_and_urls_are_not_mixed(self):
        result = fetch_constituents("399006", provider="cni", fetch_bytes=_read("cni_constituents.csv"))
        self.assertEqual(result["source"], "cnindex")
        self.assertEqual(result["provider"], "cni")
        self.assertEqual(result["index_code"], "399006")
        self.assertEqual([item["code"] for item in result["items"]], ["910011", "910012"])
        self.assertIn("cnindex.com.cn/sample-detail/download?indexcode=399006", " ".join(result["notes"]))
        self.assertNotIn("csindex", " ".join(result["notes"]))
        self.assertEqual(
            official_file_url("cni", "weights", "399006"),
            official_file_url("cni", "constituents", "399006"),
        )
        self.assertEqual(
            official_file_url("csi", "valuation", "H30269"),
            index_official.CSI_VALUATION_URL.format(code="H30269"),
        )
        self.assertIsNone(official_file_url("csi", "weights", "../000300"))
        self.assertIn("gz_399006indicator.xls", official_file_url("cni", "valuation", "399006"))

    def test_rejected_input_does_not_fetch(self):
        with patch("index_official._http_get", side_effect=AssertionError("network")) as getter:
            bad_code = fetch_constituents("../../etc/passwd", allow_network=True)
            bad_provider = fetch_weights("000300", provider="eastmoney", allow_network=True)
            bad_flag = fetch_valuation("000300", allow_network="yes")
            bad_bytes = fetch_constituents("000300", allow_network=True, fetch_bytes="not-bytes")
        getter.assert_not_called()
        self.assertEqual(bad_code["items"], [])
        self.assertEqual(bad_code["index_code"], "")
        self.assertTrue(any("指数代码无效" in gap for gap in bad_code["gaps"]))
        self.assertTrue(any("provider 只能是" in gap for gap in bad_provider["gaps"]))
        self.assertTrue(any("布尔值" in gap for gap in bad_flag["gaps"]))
        self.assertTrue(any("必须是字节" in gap for gap in bad_bytes["gaps"]))
        for result in (bad_code, bad_provider, bad_flag, bad_bytes):
            self.assertTrue(result["license_note"])

    def test_injected_bytes_win_over_network_flag(self):
        with patch("index_official._http_get", side_effect=AssertionError("network")) as getter:
            result = fetch_weights("000300", allow_network=True, fetch_bytes=_read("csi_weights.csv"))
        getter.assert_not_called()
        self.assertGreaterEqual(len(result["items"]), 1)
        self.assertTrue(any("未访问网络" in note for note in result["notes"]))

    def test_network_uses_one_url_and_records_failure(self):
        payload = _read("csi_weights.csv")
        seen = []

        def fake(url):
            seen.append(url)
            return payload

        with patch("index_official._http_get", side_effect=fake):
            ok = fetch_weights("000300", provider="csi", allow_network=True)
        self.assertEqual(seen, [index_official.CSI_WEIGHTS_URL.format(code="000300")])
        self.assertEqual(ok["source"], "csindex")
        self.assertEqual(ok["items"][0]["code"], "910001")

        seen.clear()

        def fail(url):
            seen.append(url)
            raise TimeoutError("timed out")

        with patch("index_official._http_get", side_effect=fail):
            failed = fetch_valuation("000300", provider="csi", allow_network=True)
        self.assertEqual(seen, [index_official.CSI_VALUATION_URL.format(code="000300")])
        self.assertEqual(failed["items"], [])
        self.assertEqual(len(seen), 1)
        joined = " ".join(failed["gaps"])
        self.assertIn(seen[0], joined)
        self.assertIn("未改试其他来源", joined)
        self.assertNotIn("cnindex", joined)
        self.assertNotIn("closeweight", joined)

    def test_gb18030_preamble_and_no_advice_language(self):
        text = "截止日期：2024-01-31\n指数代码,成分券代码,成分券名称\n000300,910001,示例甲\n"
        result = fetch_constituents("000300", fetch_bytes=text.encode("gb18030"))
        self.assertEqual(result["as_of"], "2024-01-31")
        self.assertEqual(result["items"], [{"code": "910001", "name": "示例甲"}])
        self.assertTrue(any("截止日期行" in note for note in result["notes"]))
        blob = _blob(result)
        for word in ("建议买入", "建议卖出", "值得买", "偏贵", "低估", "高估", "上涨概率", "目标价", "便宜"):
            self.assertNotIn(word, blob)
        self.assertIn("不是买卖建议", blob)

    def test_redirect_does_not_leave_official_host(self):
        handler = index_official._SameHostRedirect()
        request = urllib.request.Request(index_official.CSI_CONSTITUENTS_URL.format(code="000300"))
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/other.xls")

    def test_source_has_no_env_or_primary_fallback(self):
        text = Path(index_official.__file__).read_text(encoding="utf-8")
        self.assertNotIn(".env", text)
        self.assertNotIn("HITHINK", text)
        self.assertNotIn("baostock", text)
        self.assertNotIn("requests", text)
        self.assertIn("allow_network=False", text)


if __name__ == "__main__":
    unittest.main()
