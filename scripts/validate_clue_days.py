"""Validate dated public CNINFO evidence. Offline by default; --execute collects within per-day caps."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from announcement_clues import AnnouncementClues, PROFILE
from market import DataError
from scripts.official_collect import Collector


def ledger_state(folder):
    paths=[folder/'ledger.json',folder.parent/'market-gaps-v1'/'ledger.json']
    backfill=folder.parent/'verified-backfill-v1'
    paths.extend([backfill/'package.json']+[backfill/p/'ledger.json'for p in ('seed-1','seed-2','additional')])
    evidence=[p.read_bytes()for p in paths if p.exists()]
    return hashlib.sha256(b''.join(evidence)).hexdigest() if evidence else None


def validate(directory,days,execute=False):
    source=AnnouncementClues(directory)
    rows=[]
    source_stopped=False
    for day in days:
        folder=Path(directory)/day/PROFILE
        result={'day':day,'notice_day':(dt.date.fromisoformat(day)-dt.timedelta(days=1)).isoformat()}
        before=ledger_state(folder)
        try:
            data=source.get(day) if execute and not source_stopped else source.read(day)
            if data is None:
                result.update(status='not_collected',reason='source_stopped' if source_stopped else 'not_collected')
            else:
                # get() must replay existing evidence without additional public requests.
                after=ledger_state(folder)
                if execute and not source_stopped:
                    again=source.get(day)
                    if after!=ledger_state(folder) or data['item']!=again['item']:
                        raise AssertionError('replay changed evidence or dispatched another request')
                if not execute and before!=ledger_state(folder):
                    raise AssertionError('offline replay modified ledger')
                proof=[e for r in data['item'] for e in r['evidence']]
                dates_ok=all(e['notice_date']==result['notice_day'] and e['available_at'][:10]==day for e in proof)
                identities=[(e['id'],e['thscode'])for e in proof]
                if not dates_ok or len(identities)!=len(set(identities)):
                    raise AssertionError('date or deduplication check failed')
                result.update(status='verified',coverage=data['coverage'],unique_verified=data['unique_verified'],
                    excluded_non_a=data['excluded_non_a'],repair_added=data['repair_added'],
                    pagination_reconciled=data['pagination_reconciled'],limited=data['limited'],
                    segment_repair=data.get('segment_repair'),backfill=data.get('backfill'),
                    stocks=len(data['item']),notices=len(proof),dates_ok=dates_ok,replay_unchanged=True)
        except DataError as exc:
            result.update(status='unavailable',reason=exc.reason,error=str(exc))
        result['ledger_changed']=before!=ledger_state(folder)
        backfill=folder.parent/'verified-backfill-v1'
        if (folder/'ledger.json').exists()or(backfill/'package.json').exists():
            if (backfill/'package.json').exists():folders=[backfill/p for p in ('seed-1','seed-2','additional')if(backfill/p/'ledger.json').exists()]
            else:
                folders=[folder]
                if (folder.parent/'market-gaps-v1'/'ledger.json').exists():folders.append(folder.parent/'market-gaps-v1')
            replays=[Collector(f).replay()for f in folders]
            result.update(requests=sum(r['attempts']for r in replays),primary_requests=sum(r['attempts']for f,r in zip(folders,replays)if f.name in ('seed-1','seed-2'))if(backfill/'package.json').exists()else replays[0]['attempts'],
                segment_requests=sum(r['attempts']for f,r in zip(folders,replays)if f.name=='market-gaps-v1'),
                backfill_requests=sum(r['attempts']for f,r in zip(folders,replays)if f.name=='additional'),
                integrity='pass' if all(r['status']=='pass'for r in replays)else 'failed',matched=sum(r['matched']for r in replays))
            if result['integrity']!='pass':result['status']='failed'
            requests=[r for f in folders for r in Collector(f).data['requests']]
            if any(r.get('status') in (401,402,403,429) for r in requests) or (len(requests)>=2 and all(not r.get('ok') for r in requests[-2:])):
                source_stopped=True
        rows.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--days',nargs='+',required=True)
    p.add_argument('--directory',default='data/cache/clue-announcements')
    p.add_argument('--output',required=True)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    rows=validate(args.directory,args.days,args.execute)
    Path(args.output).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    raise SystemExit(1 if any(r['status']=='failed' for r in rows) else 0)


if __name__=='__main__':main()
