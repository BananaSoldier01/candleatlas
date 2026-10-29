"""Replace unsourced number claims in AI prose without dropping the item.

Items that cite only technical (T*) or financial (F*) evidence are left as
written. News and disclosure items (N*/D*) keep the sentence, but a figure
is swapped for MARK unless the same magnitude and dimension appear in the
cited N/D text or, when those are mixed with T/F, in the cited T/F text.
Dates, years written with 年, material ids, "近 N 日" windows and known
indicator parameter groups are not claims. This checks citation presence,
not that the sentence is factually or semantically correct.
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
_PARAM=r'[（(]'+_SPACE+r'[0-9]+(?:\.[0-9]+)?(?:'+_SPACE+r'[,，]'+_SPACE+r'[0-9]+(?:\.[0-9]+)?)+'+_SPACE+r'[）)]'
# 年份只豁免「2001年」。参数组只豁免指标名后的括号，裸 (1,2,3) 仍要核对。
_PROTECT=(
    re.compile(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?'),
    re.compile(r'(?<![A-Za-z0-9])[TNDMF][0-9]+(?![0-9])'),
    re.compile(r'近'+_SPACE+r'[0-9]+(?:\.[0-9]+)?'+_SPACE+r'(?:个'+_SPACE+r')?(?:交易'+_SPACE+r')?[日天]'),
    re.compile(r'(?i)(?<![A-Za-z])(?:MACD|RSI|KDJ|BOLL|EMA|MA)'+_SPACE+_PARAM),
    re.compile(r'(?<![0-9.])(?:19|20)[0-9]{2}'+_SPACE+r'年'),
)
_CLAIM=re.compile(
    r'(?<![0-9.])'
    r'(?P<sign>[-+])?'
    r'(?P<int>[0-9]{1,3}(?:[,，][0-9]{3})+|[0-9]+)'
    r'(?:\.(?P<frac>[0-9]+))?'
    r'(?:'+_SPACE+r'(?P<mag>万亿|亿|万))?'
    r'(?:'+_SPACE+r'(?P<unit>[%％元股倍点]+))?'
)
# 元股%倍点同时出现时取最后一项（「亿元」的单位是末尾的元）。
_DIM={'元':'money','股':'shares','%':'percent','％':'percent','倍':'multiple','点':'points'}
_CONTENT_KEYS=frozenset(('title','content','summary','abstract','正文','摘要','metrics','indicators','facts','items','structured','figures','values'))


def _spans(text):
    found=[]
    for pattern in _PROTECT:
        found.extend(match.span() for match in pattern.finditer(text))
    return found


def _overlaps(start,end,spans):
    return any(start<stop and end>begin for begin,stop in spans)


def _dimension(unit):
    found=[_DIM[char] for char in (unit or '') if char in _DIM]
    return found[-1] if found else 'unitless'


def _amount(match):
    raw=match.group('int').replace(',','').replace('，','')
    if match.group('frac'):raw+='.'+match.group('frac')
    value=Decimal(raw)*_SCALE[match.group('mag') or '']
    unit=match.group('unit') or ''
    if '%' in unit or '％' in unit:value/=Decimal(100)
    if match.group('sign')=='-':value=-value
    return value,_dimension(unit)


def _numbers_in(text):
    spans=_spans(text)
    found=set()
    for match in _CLAIM.finditer(text):
        if match.start()==match.end() or _overlaps(match.start(),match.end(),spans):
            continue
        found.add(_amount(match))
    return found


def source_numbers(texts):
    """(magnitude, dimension) pairs. 万/亿 expand; % is divided by 100.

    dimension is money, shares, percent, multiple, points, or unitless.
    The same magnitude in two dimensions is not one claim.
    """
    found=set()
    if not isinstance(texts,(list,tuple)):
        return found
    for text in texts:
        if isinstance(text,str):
            found.update(_numbers_in(text))
    return found


def _leaf_texts(value):
    if isinstance(value,str):return [value]
    if isinstance(value,bool) or value is None:return []
    if isinstance(value,int):return [str(value)]
    if isinstance(value,float):
        if value!=value or value in (float('inf'),float('-inf')):return []
        return [format(Decimal(str(value)),'f')]
    return None


def _value_texts(value):
    leaves=_leaf_texts(value)
    if leaves is not None:return leaves
    if isinstance(value,(dict,list,tuple)):
        try:return [json.dumps(value,ensure_ascii=False,allow_nan=False,default=str)]
        except (TypeError,ValueError):
            pieces=[]
            items=value.values() if isinstance(value,dict) else value
            for item in items:pieces.extend(_value_texts(item))
            return pieces
    return []


def _content_texts(value):
    """N/D content only. Nested dicts stay on the whitelist; list items do not."""
    leaves=_leaf_texts(value)
    if leaves is not None:return leaves
    if isinstance(value,dict):
        pieces=[]
        for key,item in value.items():
            if key in _CONTENT_KEYS:pieces.extend(_content_texts(item))
        return pieces
    if isinstance(value,(list,tuple)):
        pieces=[]
        for item in value:pieces.extend(_content_texts(item))
        return pieces
    return []


def _material_texts(item,narrow=False):
    if not isinstance(item,dict):return []
    texts=[]
    title=item.get('title')
    if isinstance(title,str):texts.append(title)
    value=item.get('value')
    texts.extend(_content_texts(value) if narrow else _value_texts(value))
    return texts


def _allowed(ids,by_id):
    ids=[item for item in ids if item]
    kinds={item[:1] for item in ids}
    # 只有 T/F、没有 N/D：整条跳过。混有 N/D 时不能因为旁边有 T/F 就跳过。
    if kinds&{'T','F'} and not kinds&{'N','D'}:return None
    chosen=[item for item in ids if item[:1] in 'NDTF'] if kinds&{'N','D'} else list(ids)
    blobs=[]
    for item in chosen:blobs.extend(_material_texts(by_id.get(item),item[:1] in 'ND'))
    return source_numbers(blobs)


def _replace(text,allowed):
    spans=_spans(text)
    pieces=[]
    last=0
    changed=False
    for match in _CLAIM.finditer(text):
        if match.start()==match.end() or _overlaps(match.start(),match.end(),spans):continue
        if _amount(match) in allowed:continue
        pieces.append(text[last:match.start()])
        pieces.append(MARK)
        last=match.end()
        changed=True
    if not changed:return text
    pieces.append(text[last:])
    body=''.join(pieces)
    if NOTE not in body:body+=NOTE
    return body


def gate_ai_report(ai,evidence):
    """Return a deep copy of ai with unsourced number claims marked.

    Evidence id lists are preserved. The input is not modified. Items that
    cite only T*/F* are copied unchanged. N/D mixed with T/F keeps a number
    when either side contains that magnitude and dimension.
    """
    if not isinstance(ai,dict):return copy.deepcopy(ai)
    by_id={}
    if isinstance(evidence,list):
        for item in evidence:
            if isinstance(item,dict) and isinstance(item.get('id'),str):by_id.setdefault(item['id'],item)
    out=copy.deepcopy(ai)
    for key in _KEYS:
        rows=out.get(key)
        if not isinstance(rows,list):continue
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('text'),str):continue
            refs=row.get('evidence')
            ids=[item for item in refs if isinstance(item,str)] if isinstance(refs,list) else []
            allowed=_allowed(ids,by_id)
            if allowed is None:continue
            row['text']=_replace(row['text'],allowed)
    return out
