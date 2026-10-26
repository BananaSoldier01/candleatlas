"""Offline metadata fixture helpers. PDF transport bytes here are synthetic, not official evidence."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import datetime as dt
from analysis import Analysis
from disclosures import DisclosureStore

FIXTURE=json.loads((Path(__file__).parent/'fixtures/official_disclosures.json').read_text())

def fixture_bundle(folder):
    folder=Path(folder);(folder/'documents').mkdir(parents=True);(folder/'evidence').mkdir()
    catalog=copy.deepcopy(FIXTURE['catalog'])
    for doc in catalog['documents']:
        body=('%PDF-1.7\nSYNTHETIC UNIT FIXTURE '+doc['id']+'\n%%EOF').encode()
        (folder/doc['pdf_path']).write_bytes(body);doc['sha256']=hashlib.sha256(body).hexdigest()
    for digest,raw in FIXTURE['index_bytes'].items():(folder/catalog['index_evidence'][digest]['path']).write_text(raw)
    (folder/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False))
    return catalog


def fake_analysis(folder,day='2025-03-26'):
    folder=Path(folder);fixture_bundle(folder/'disclosures')
    market=Mock();market.calendar.return_value=[day]
    end=dt.date.fromisoformat(day)
    market.prices.return_value={'items':[dict(date=(end-dt.timedelta(days=79-i)).isoformat(),close_price=10+i*.1,volume=100) for i in range(80)]}
    news=Mock();news.stock.return_value={'items':[]};model=Mock();model.complete.side_effect=AssertionError('model forbidden')
    themes=Mock();themes.financial.side_effect=AssertionError('historical current values forbidden')
    engine=Analysis(folder/'reports.db',market,news,themes,model,DisclosureStore(folder/'disclosures'))
    return engine
