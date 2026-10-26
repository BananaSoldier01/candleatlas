import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from news import News, normalize
from market import DataError

class NewsTests(unittest.TestCase):
    def test_normalize_sanitizes_sorts_deduplicates(self):
        rows=[{'id':1,'create_time':'2026-09-23 10:00:00','rich_text':'<b>消息</b><script>bad()</script>&amp;内容','docurl':'javascript:alert(1)'},
              {'id':2,'create_time':'2026-09-23 11:00:00','rich_text':'最新','docurl':'https://finance.sina.cn/a'},
              {'id':2,'create_time':'2026-09-23 11:00:00','rich_text':'重复'},
              {'id':3,'create_time':'bad','rich_text':'错误日期'}]
        result=normalize(rows)
        self.assertEqual([r['id'] for r in result],['2','1'])
        self.assertEqual(result[1]['content'],'消息&内容')
        self.assertEqual(result[1]['url'],'')
    def test_cache_and_stale_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            n=News(Path(d));data={'items':[{'id':'1'}],'fetched_at':100,'updated_at':'test'}
            with patch.object(n,'fetch',return_value=data) as fetch,patch('news.time.time',return_value=100):
                self.assertFalse(n.get()['stale']);n.get();self.assertEqual(fetch.call_count,1)
            with patch.object(n,'fetch',side_effect=OSError),patch('news.time.time',return_value=200):
                self.assertTrue(n.get()['stale'])
                self.assertEqual(n.get()['items'],data['items'])
    def test_empty_cache_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(News,'fetch',side_effect=OSError):
                with self.assertRaises(DataError):News(Path(d)).get()

class AssociationTests(unittest.TestCase):
    def test_distinguish_stock_index_fund(self):
        import json
        from news import associations
        stocks,topics=associations({'ext':json.dumps({'stocks':[{'market':'cn','symbol':'sh600487','key':'亨通光电'},{'market':'cn','symbol':'si931071','key':'人工智能'},{'market':'fund','symbol':'159363','key':'基金'}]}),'tag':[{'name':'行业'}]})
        self.assertEqual(stocks,[{'thscode':'600487.SH','name':'亨通光电'}])
        self.assertEqual(topics,['人工智能','行业'])
    def test_historical_cutoff_and_code_validation(self):
        with tempfile.TemporaryDirectory() as d:
            n=News(Path(d))
            with patch.object(n,'cached',return_value={'items':[{'time':'2026-09-22 12:00:00'},{'time':'2026-09-23 10:00:00'}]}):
                self.assertEqual(len(n.stock('600487.SH','2026-09-22')['items']),1)
                with self.assertRaises(DataError):n.stock('../secret','2026-09-22')
