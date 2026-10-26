"""All default candidate types: bidirectional real-engine coverage and full prefix replay."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from chan_structure import calculate, RULES
from chan_candidates import CANDIDATE_TYPES, Collector

SAMPLES=json.loads((Path(__file__).parent/'fixtures/chan_extended.json').read_text())['samples']

def calc(rows,enabled=True):
    return calculate(rows,rows[-1]['date'],closed_before='2099-01-01',include_candidates=enabled)

def signals(frame):
    value={k:copy.deepcopy(frame[k]) for k in ('date','candidates','candidate_events')}
    for event in value['candidate_events']: event.pop('sample_id')
    return value

class ExtendedCandidatesTests(unittest.TestCase):
    def test_all_types_both_directions_full_prefix_and_unchanged_structure(self):
        coverage=set();checked=0
        for sample in SAMPLES:
            rows=copy.deepcopy(sample['rows']);before=copy.deepcopy(rows);rules=copy.deepcopy(RULES)
            full=calc(rows);normal=calc(rows,False)
            self.assertNotIn('candidate_meta',normal)
            for index,frame in enumerate(full['frames']):
                prefix=calc(rows[:index+1])['frames'][-1]
                self.assertEqual(signals(prefix),signals(frame),(sample['mirror'],frame['date']))
                self.assertEqual({k:v for k,v in frame.items() if k not in ('candidates','candidate_events')},normal['frames'][index])
                for candidate in frame['candidates']:
                    self.assertEqual(candidate['confirmation'],'unknown')
                    self.assertLessEqual(candidate['pivot_date'],candidate['first_seen_at'])
                    self.assertLessEqual(candidate['first_seen_at'],frame['date'])
                    self.assertEqual(candidate['last_seen_at'],frame['date'])
                    coverage.update((value,candidate['is_buy']) for value in candidate['types'])
                checked+=1
            self.assertEqual(rows,before);self.assertEqual(RULES,rules)
        self.assertEqual(checked,432)
        self.assertEqual(coverage,{(value,direction) for value in CANDIDATE_TYPES for direction in (False,True)})
    def test_historical_cutoff_and_gap_do_not_inherit_later_candidates(self):
        rows=copy.deepcopy(SAMPLES[0]['rows']);day=rows[160]['date']
        full=calculate(rows,day,closed_before='2099-01-01',include_candidates=True)
        self.assertEqual(full,calc(rows[:161]))
        rows[90]['close_price']=None
        self.assertEqual(calc(rows)['frames'],calc(rows[91:])['frames'])
    def test_full_prefix_comparison_detects_each_attribute_fault(self):
        rows=SAMPLES[0]['rows'];result=calc(rows)
        frame=next(f for f in result['frames'] if any('3a' in c['types'] or '3b' in c['types'] for c in f['candidates']))
        original=signals(frame)
        for field,value in [('first_seen_at','2000-01-01'),('types',[]),('source','wrong'),('stability','wrong'),('is_target',None),('identity',{})]:
            corrupted=copy.deepcopy(frame);corrupted['candidates'][0][field]=value
            self.assertNotEqual(signals(corrupted),original,field)
    def test_candidate_exception_preserves_structure_and_failure_status(self):
        rows=SAMPLES[0]['rows']
        with patch.object(Collector,'observe',side_effect=RuntimeError('synthetic fault')):
            result=calc(rows)
        self.assertEqual(result['candidate_meta']['status'],'failed')
        self.assertTrue(all(f['candidates'] is None for f in result['frames']))
        for frame,normal in zip(result['frames'],calc(rows,False)['frames']):
            self.assertEqual({k:v for k,v in frame.items() if k not in ('candidates','candidate_events')},normal)
