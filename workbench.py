"""Read-only personal workspace assembled from local records and saved reports."""
import datetime as dt
import json

from market import DataError


def summary(tracking, analysis, day):
    try: dt.date.fromisoformat(day)
    except (TypeError, ValueError): raise DataError('请选择有效观察日。')
    records = tracking.list()['items']
    active = [r for r in records if r['active'] and r['date'] <= day]
    grouped = {}
    for r in sorted(active, key=lambda r:(r['date'],r['createdAt']), reverse=True):
        grouped.setdefault(r['thscode'], []).append(r)
    items=[]
    with analysis.db() as db:
        for code, notes in grouped.items():
            row=db.execute('SELECT id,day,created,status,phase,payload,error FROM reports WHERE code=? AND day<=? ORDER BY day DESC,created DESC,id DESC LIMIT 1',(code,day)).fetchone()
            report=dict(row) if row else None
            payload=json.loads(report.pop('payload') or '{}') if report else {}
            t=payload.get('technical') or {}
            status='missing' if not report else 'running' if report['status']=='running' else 'incomplete' if report['status']!='complete' or not t.get('close') else 'outdated' if report['day']<day or t.get('asof')!=day else 'ready'
            ai=payload.get('ai') or {}
            items.append({'thscode':code,'name':notes[0]['name'],'note':notes[0]['note'],
                          'observed':notes[0]['date'],'record_count':len(notes),'status':status,
                          'report':report,'technical':{k:t.get(k) for k in ('asof','close','trend','change20','change1','volume_ratio5','rsi14')},
                          'assessment':None if not payload.get('assessment') else {
                              'rule_version':payload['assessment'].get('rule_version'),
                              'coverage':payload['assessment'].get('coverage'),
                              'components':{k:payload['assessment']['components'][k].get('score')
                                            for k in ('trend','momentum','volume_coord','overheat')
                                            if k in payload['assessment'].get('components',{})},
                              'statuses':{k:payload['assessment']['components'][k].get('status')
                                          for k in ('trend','momentum','volume_coord','overheat')
                                          if k in payload['assessment'].get('components',{})},
                          },
                          'overview':(ai.get('overview') or [])[:1], 'watch':(ai.get('watch') or [])[:3],
                          'has_ai':bool(ai), 'limitations':(payload.get('limitations') or [])[:3]})
    priority={'incomplete':0,'missing':1,'outdated':2,'running':3,'ready':4}
    items.sort(key=lambda r:(priority[r['status']],r['thscode']))
    return {'date':day,'items':items,'counts':{'stocks':len(items),'ready':sum(r['status']=='ready' for r in items),
            'pending':sum(r['status'] in ('missing','outdated','incomplete') for r in items),
            'records':len(active)},'future_records':sum(r['active'] and r['date']>day for r in records)}
