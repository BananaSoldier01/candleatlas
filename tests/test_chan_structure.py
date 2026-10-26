import math
import unittest
import datetime as dt
from chan_structure import calculate, engine, unit, snapshot
from market import DataError


def rows(n=150):
    data=[]
    for i in range(n):
        p=50+8*math.sin(i/7)+4*math.sin(i/23)
        data.append(dict(date=(dt.date(2024,1,1)+dt.timedelta(days=i)).isoformat(),open_price=p-.2,
                         close_price=p+.2,high_price=p+1,low_price=p-1))
    return data


class ChanTests(unittest.TestCase):
    def calc(self,r):return calculate(r,'2025-01-01',closed_before='2025-01-02')

    def test_prefix_and_batch(self):
        r=rows();d=self.calc(r)
        self.assertTrue(d['frames'][-1]['bi'])
        for n in (20,50,100,150):
            self.assertEqual(self.calc(r[:n])['frames'][-1],d['frames'][n-1])
            core=engine(False);prev=None
            for i,row in enumerate(r[:n]):
                u=unit(row,i,prev);core.add_single_klu(u);prev=u
            core.cal_seg_and_zs()
            frame={k:[{a:b for a,b in x.items() if a!='confirmed_at'} for x in d['frames'][n-1][k]] for k in ('bi','seg','zs')}
            self.assertEqual(frame,snapshot(core))

    def test_confirmation_not_backdated(self):
        r=rows();d=self.calc(r);delayed=False
        for f in d['frames']:
            for k in ('bi','seg','zs'):
                for x in f[k]:
                    if x['sure']:
                        self.assertLessEqual(x['end'],x['confirmed_at'])
                        self.assertLessEqual(x['confirmed_at'],f['date'])
                        delayed |= x['end']<x['confirmed_at']
                    else:self.assertIsNone(x['confirmed_at'])
        self.assertTrue(delayed)

    def test_cutoff_current_bar_and_gap(self):
        r=rows();day=r[80]['date']
        self.assertEqual(calculate(r,day,closed_before=day)['frames'],self.calc(r[:80])['frames'])
        r[70]['high_price']=None
        d=self.calc(r)
        self.assertEqual(d['start'],r[71]['date'])
        self.assertEqual(d['sample'],79)
        r[-1]['low_price']=float('nan')
        self.assertEqual(self.calc(r)['frames'],[])

    def test_invalid_order_and_ohlc(self):
        r=rows(5)
        with self.assertRaises(DataError):self.calc(r[::-1])
        with self.assertRaises(DataError):self.calc(r+r)
        r[2]['high_price']=1
        self.assertEqual(self.calc(r)['sample'],2)
