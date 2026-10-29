"""Replace unsourced number claims in AI prose without dropping the item.

Technical (T*) and financial (F*) items are left as written. News and
disclosure items (N*/D*) keep the sentence, but figures that cited N/D
text does not contain are swapped for MARK. Dates, standalone years,
material ids, "近 N 日" windows and parameter groups are not claims.
"""
import copy
import json
import re
from decimal import Decimal

MARK='（略※）'
NOTE='（文中（略※）表示该数字未在所引新闻/披露材料中找到出处，未整段丢弃本条。）'
_KEYS=('overview','supporting','opposing','watch')
_SCALE={'':Decimal(1),'万':Decimal(10_000),'亿':Decimal(100_000_000),'万亿':Decimal('1000000000000')}
_SPACE=r'[ \t\u3000]*'
_PROTECT=(
    re.compile(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?'),
    re.compile(r'(?<![A-Za-z0-9])[TNDMF][0-9]+(?![0-9])'),
    re.compile(r'近'+_SPACE+r'[0-9]+(?:\.[0-9]+)?'+_SPACE+r'(?:个'+_SPACE+r')?(?:交易'+_SPACE+r')?[日天]'),
    re.compile(r'[（(]'+_SPACE+r'[0-9]+(?:\.[0-9]+)?(?:'+_SPACE+r'[,，]'+_SPACE+r'[0-9]+(?:\.[0-9]+)?)+'+_SPACE+r'[）)]'),
    re.compile(r'(?<![0-9.])(?:19|20)[0-9]{2}'+_SPACE+r'年'),
    re.compile(r'(?<![0-9.])(?:19|20)[0-9]{2}(?!'+_SPACE+r'(?:[0-9.]|万|亿|%|％|元))'),
)
_CLAIM=re.compile(
    r'(?<![0-9.])'
    r'(?P<sign>[-+])?'
    r'(?P<int>[0-9]{1,3}(?:[,，][0-9]{3})+|[0-9]+)'
    r'(?:\.(?P<frac>[0-9]+))?'
    r'(?:'+_SPACE+r'(?P<mag>万亿|亿|万))?'
    r'(?:'+_SPACE+r'(?P<unit>[%％元股倍点]+))?'
)


def _spans(text):
    found=[]
    for pattern in _PROTECT:
        found.extend(match.span() for match in pattern.finditer(text))
    return found


def _overlaps(start,end,spans):
    return any(start<stop and end>begin for begin,stop in spans)


def _amount(match):
    raw=match.group('int').replace(',','').replace('，','')
    if match.group('frac'):
        raw+='.'+match.group('frac')
    value=Decimal(raw)*_SCALE[match.group('mag') or '']
    unit=match.group('unit') or ''
    if '%' in unit or '％' in unit:
        value/=Decimal(100)
    if match.group('sign')=='-':
        value=-value
    return value


def _numbers_in(text):
    spans=_spans(text)
    found=set()
    for match in _CLAIM.finditer(text):
        if match.start()==match.end() or _overlaps(match.start(),match.end(),spans):
            continue
        found.add(_amount(match))
    return found


def source_numbers(texts):
    """Comparable magnitudes (万/亿 expanded, percent scaled) found in texts."""
    found=set()
    if not isinstance(texts,(list,tuple)):
        return found
    for text in texts:
        if isinstance(text,str):
            found.update(_numbers_in(text))
    return found


def _value_texts(value):
    if isinstance(value,str):
        return [value]
    if isinstance(value,bool) or value is None:
        return []
    if isinstance(value,int):
        return [str(value)]
    if isinstance(value,float):
        if value!=value or value in (float('inf'),float('-inf')):
            return []
        return [format(Decimal(str(value)),'f')]
    if isinstance(value,(dict,list,tuple)):
        try:
            return [json.dumps(value,ensure_ascii=False,allow_nan=False,default=str)]
        except (TypeError,ValueError):
            pieces=[]
            items=value.values() if isinstance(value,dict) else value
            for item in items:
                pieces.extend(_value_texts(item))
            return pieces
    return []


def _material_texts(item):
    if not isinstance(item,dict):
        return []
    texts=[]
    title=item.get('title')
    if isinstance(title,str):
        texts.append(title)
    texts.extend(_value_texts(item.get('value')))
    return texts


def _allowed(ids,by_id):
    kinds={item[:1] for item in ids if item}
    if kinds&{'T','F'} and not kinds&{'N','D'}:
        return None
    chosen=[item for item in ids if item[:1] in 'ND'] if kinds&{'N','D'} else list(ids)
    blobs=[]
    for item in chosen:
        blobs.extend(_material_texts(by_id.get(item)))
    return source_numbers(blobs)


def _replace(text,allowed):
    spans=_spans(text)
    pieces=[]
    last=0
    changed=False
    for match in _CLAIM.finditer(text):
        if match.start()==match.end() or _overlaps(match.start(),match.end(),spans):
            continue
        if _amount(match) in allowed:
            continue
        pieces.append(text[last:match.start()])
        pieces.append(MARK)
        last=match.end()
        changed=True
    if not changed:
        return text
    pieces.append(text[last:])
    body=''.join(pieces)
    if NOTE not in body:
        body+=NOTE
    return body


def gate_ai_report(ai,evidence):
    """Return a deep copy of ai with unsourced number claims marked.

    Evidence id lists are preserved. The input is not modified. T*/F* items
    that do not also cite N*/D* are copied unchanged.
    """
    if not isinstance(ai,dict):
        return copy.deepcopy(ai)
    by_id={}
    if isinstance(evidence,list):
        for item in evidence:
            if isinstance(item,dict) and isinstance(item.get('id'),str):
                by_id.setdefault(item['id'],item)
    out=copy.deepcopy(ai)
    for key in _KEYS:
        rows=out.get(key)
        if not isinstance(rows,list):
            continue
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('text'),str):
                continue
            refs=row.get('evidence')
            ids=[item for item in refs if isinstance(item,str)] if isinstance(refs,list) else []
            allowed=_allowed(ids,by_id)
            if allowed is None:
                continue
            row['text']=_replace(row['text'],allowed)
    return out
