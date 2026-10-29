"""One invalidation line for each strong technical-profile component.

Read-only. Old reports without an assessment return an empty list.
"""
LABELS={'trend':'趋势','momentum':'动量','volume_coord':'量能配合','overheat':'过热/回撤风险'}
ORDER=('trend','momentum','volume_coord','overheat')


def _score(component):
    if not isinstance(component, dict):
        return None
    score=component.get('score')
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if score!=score or score in (float('inf'), float('-inf')):
        return None
    return float(score)


def _sample(payload, assessment, technical):
    for source in (technical.get('sample'), assessment.get('sample')):
        if isinstance(source, bool):
            continue
        if isinstance(source, int):
            return source
        if isinstance(source, float) and source==int(source):
            return int(source)
    return None


def _overlap(assessment):
    warnings=assessment.get('warnings')
    if isinstance(warnings, list) and any(isinstance(item, str) and '重复计分' in item for item in warnings):
        return True
    total=assessment.get('total')
    if isinstance(total, dict):
        note=total.get('note')
        if isinstance(note, str) and '重复计分' in note and 'change20' in note:
            return True
    meta=assessment.get('meta')
    if isinstance(meta, dict):
        for value in meta.values():
            if isinstance(value, str) and '重复计分' in value:
                return True
    return False


def invalidation_lines(payload):
    if not isinstance(payload, dict):
        return []
    assessment=payload.get('assessment')
    if not isinstance(assessment, dict):
        return []
    components=assessment.get('components')
    if not isinstance(components, dict):
        return []
    technical=payload.get('technical') if isinstance(payload.get('technical'), dict) else {}
    sample=_sample(payload, assessment, technical)
    asof=technical.get('asof') if isinstance(technical.get('asof'), str) and technical.get('asof') else assessment.get('asof')
    asof=asof if isinstance(asof, str) else ''
    date=payload.get('date') if isinstance(payload.get('date'), str) else ''
    method=technical.get('method') if isinstance(technical.get('method'), str) else ''
    overlap=_overlap(assessment)
    lines=[]
    for key in ORDER:
        score=_score(components.get(key))
        if score is None or score<70:
            continue
        comp=components[key]
        bits=[]
        if sample is None or sample<60:
            bits.append('连续有效样本不足 60（MACD 不可算，初始化窗口影响 RSI/MACD）')
        if '前复权' in method or not method:
            bits.append('前复权修订可能改变历史序列')
        if date and asof and date!=asof:
            bits.append('观察日与行情截至日不一致')
        elif date and not asof:
            bits.append('行情截至日未取得，不能与观察日对齐')
        if key=='volume_coord':
            bits.append('量能配合依赖当日涨跌与当日成交量（缺量则不可算）')
        coverage=comp.get('coverage') if isinstance(comp, dict) else None
        status=comp.get('status') if isinstance(comp, dict) else None
        thin=isinstance(coverage, (int, float)) and not isinstance(coverage, bool) and coverage<1
        partial=status=='partial'
        if thin and partial:
            bits.append('该分项规则覆盖度不足 100%，且 status=partial')
        elif thin:
            bits.append('该分项规则覆盖度不足 100%')
        elif partial:
            bits.append('该分项 status=partial')
        if key in ('trend','momentum') and overlap:
            bits.append('trend 与 momentum 共用近 20 日涨跌，存在重复计分')
        body='；'.join(bits)+'。' if bits else '本次材料未标出样本、覆盖度或截至日方面的失效条件。'
        lines.append({
            'component':key,'score':score,
            'text':f'{LABELS[key]}这一读法会失效：{body}技术画像不是上涨概率。',
        })
    return lines
