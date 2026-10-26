import unittest
from theme_clues import groups, ThemeClues
from market import DataError
from unittest.mock import Mock

class ThemeTests(unittest.TestCase):
    def test_groups_deduplicate_and_finance_is_source_label(self):
        rows=[{'thscode':'A','keyword_list':['业绩增长','芯片','芯片']},{'thscode':'B','keyword_list':['芯片']},{'thscode':'A','keyword_list':['业绩增长']}]
        self.assertEqual([(x['name'],x['count']) for x in groups(rows)],[('芯片',2),('业绩增长',1)])
        self.assertEqual([x['name'] for x in groups(rows,True)],['业绩增长'])
    def test_current_members_not_used_historically(self):
        m=Mock();m.calendar.return_value=['2026-09-22','2026-09-23'];r=Mock();r.read.return_value=None
        c=ThemeClues(m,r)
        with self.assertRaises(DataError):c.catalog('2026-09-22','concept')
        with self.assertRaises(DataError):c.catalog('2026-09-22','topics')
        m.get.assert_not_called()
    def test_financial_units_and_actual_field_names(self):
        m=Mock();m.get.return_value={'abilities':[{'indicators':[{'index_id':'calculate_parent_holder_net_profit_yoy_growth_ratio','value':'93.381059'},{'index_id':'sale_net_interest_ratio','value':None}]}]}
        d=ThemeClues(m,Mock()).financial('600487.SH','2026-2')
        self.assertEqual(d['items'][0],{'label':'归母净利润同比','value':93.381059})
        self.assertIsNone(d['items'][1]['value'])
