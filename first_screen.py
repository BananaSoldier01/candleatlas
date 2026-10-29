"""首屏前提与缺口说明。只读报告字段，不写库、不打分、不预测涨跌。"""
import datetime as dt
import re

# RSI14 与 MACD(12,26,9) 的最少连续样本。analysis.technical 在 n>=15 时写 rsi14，
# n>=60 时写 macd_*（analysis.py）。此处复用这两个门槛，不另造数字。
RSI14_MIN_BARS = 15
MACD_MIN_BARS = 60

# 分项键与 tech_score.evaluate 的 components 一致。missing 含义见 tech_score._eval_*。
COMPONENTS = (
    ('trend', '趋势'),
    ('momentum', '动量'),
    ('volume_coord', '量能配合'),
    ('overheat', '过热/回撤风险'),
)
_LABELS = dict(COMPONENTS)
# tech_score 会写入 missing 的键。momentum 不使用 rsi14。未知键不翻译成其他分项。
_KNOWN_MISSING = {
    'trend', 'bias20', 'macd', 'change20', 'change1', 'volume_ratio5', 'volume_ratio5==0', 'rsi14',
}
_CALIBER_MARKS = ('口径', 'method', 'prompt_version', '窗口', '复权')
_LEVELS = ('ok', 'note', 'warn')
# 这些 limitation 原文里的片段可以对应到材料，而不是技术分项。
_MATERIAL = (
    ('新闻获取失败', '新闻获取失败', 'AI 解读缺少 N 类材料（不据此认定无事件）'),
    ('未选择财务报告期', '未选择财务报告期', '无 F 类财务材料'),
    ('财务数据暂不可用', '财务数据暂不可用', '无 F 类财务材料'),
    ('财务接口缺少披露时间', '财务接口缺少披露时间', '历史观察日不调用当前财务值，本次无 F 类财务材料'),
    ('披露资料读取未完成', '披露资料读取未完成', '披露资料未纳入，未据此补充历史财务值'),
    ('本机尚未导入已核验披露资料', '本机尚未导入已核验披露资料', '披露材料未纳入本次，AI 解读缺少 D 类材料'),
    ('尚未纳入本机已核验披露资料', '尚未纳入本机已核验披露资料', '披露材料未纳入本次，AI 解读缺少 D 类材料'),
    ('尚无可用的已核验披露材料', '尚无可用的已核验披露材料', '披露材料未纳入本次，AI 解读缺少 D 类材料'),
    ('披露资料校验未通过', '披露资料校验未通过', '披露资料未展示；其他已取得的分析仍可使用'),
    ('技术评分未生成', '技术评分未生成', '分项画像未生成，不影响已算出的技术指标'),
)
_KINDS = {
    'T': '程序计算',
    'D': '公告标题',
    'N': '新闻标题',
    'F': '财务指标',
    'M': '无依据说明',
}

try:
    from zoneinfo import ZoneInfo
    _SHANGHAI = ZoneInfo('Asia/Shanghai')
except Exception:
    _SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def _item(key, label, text, level):
    if level not in _LEVELS:
        level = 'note'
    return {'key': key, 'label': label, 'text': text, 'level': level}


def _as_report(row, report):
    if isinstance(report, dict):
        return report
    if isinstance(row, dict) and isinstance(row.get('report'), dict):
        return row['report']
    return None


def _dates(report):
    if not isinstance(report, dict) or not isinstance(report.get('technical'), dict):
        return '行情未取得', 'warn'
    tech = report['technical']
    obs, asof = report.get('date'), tech.get('asof')
    if not isinstance(obs, str) or not obs or not isinstance(asof, str) or not asof:
        return '未取得', 'note'
    if obs == asof:
        return f'一致：观察日与数据日均为 {obs}', 'ok'
    return f'不一致：观察日 {obs}，数据日 {asof}', 'warn'


def _sample_count(report):
    tech = report.get('technical') if isinstance(report, dict) else None
    if not isinstance(tech, dict):
        return None
    sample = tech.get('sample')
    if type(sample) is int and sample >= 0:
        return sample
    return None


def _sample(report):
    sample = _sample_count(report)
    if sample is None:
        return '未取得', 'note'
    rsi = '够' if sample >= RSI14_MIN_BARS else '不够'
    macd = '够' if sample >= MACD_MIN_BARS else '不够'
    level = 'ok' if rsi == '够' and macd == '够' else 'warn' if rsi == '不够' else 'note'
    text = (f'RSI14（至少 {RSI14_MIN_BARS} 根）：{rsi}；'
            f'MACD(12,26,9)（至少 {MACD_MIN_BARS} 根）：{macd}（当前样本 {sample} 根）')
    return text, level


def _caliber_reason(delta):
    reasons = delta.get('reasons') if isinstance(delta, dict) else None
    if not isinstance(reasons, list):
        return None
    for reason in reasons:
        if isinstance(reason, str) and any(mark in reason for mark in _CALIBER_MARKS):
            return reason
    return None


def _baseline(delta):
    # 用 Analysis.get 已算好的 delta.status，不重新对比。
    status = delta.get('status') if isinstance(delta, dict) else None
    text = {
        'first_analysis': '无更早基线',
        'comparable': '可比',
        'limited': '有限可比',
        'incomparable': '口径不可比',
    }.get(status)
    if text is None:
        return '未取得', 'note'
    if status == 'incomparable':
        reason = _caliber_reason(delta)
        if reason:
            text = f'口径不可比（{reason}）'
        return text, 'warn'
    if status == 'comparable':
        return text, 'ok'
    return text, 'note'


def _shanghai_day(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(_SHANGHAI).date()
    except (OverflowError, OSError, ValueError):
        return None


def _observation_day(report):
    if not isinstance(report, dict):
        return None
    value = report.get('date')
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _backfill(report):
    """只看当前这份的生成日是否晚于观察日。

    compare.py 的「基线事后补做」比较的是两份报告谁后生成。这里不沿用那个判据。
    生成日早于观察日时，按「不晚于观察日」走「否：生成于观察日当天」。
    """
    obs = _observation_day(report)
    generated = _shanghai_day(report.get('generated_at')) if isinstance(report, dict) else None
    if obs is None or generated is None:
        return '未取得', 'note'
    if generated > obs:
        return '是：生成于观察日之后，不代表当时可知', 'warn'
    return '否：生成于观察日当天', 'ok'


def _ai(report):
    if not isinstance(report, dict):
        return '未取得', 'note'
    if report.get('ai'):
        model = report.get('model')
        name = model.strip() if isinstance(model, str) and model.strip() else '未取得'
        return f'含 AI 解读（{name}）', 'note'
    return '仅程序计算，未调用 AI', 'ok'


def disclosure_items(row, report, delta):
    """固定 5 项。缺信息写「未取得」，不省略。level 只用于样式。"""
    data = _as_report(row, report)
    return [
        _item('dates', '观察日与数据日', *_dates(data)),
        _item('sample', '样本窗口', *_sample(data)),
        _item('baseline', '基线是否可比', *_baseline(delta)),
        _item('backfill', '当前这份是否事后补做', *_backfill(data)),
        _item('ai', '是否含 AI', *_ai(data)),
    ]


def evidence_kind(evidence_id):
    prefix = evidence_id[0] if isinstance(evidence_id, str) and evidence_id else ''
    if prefix in _KINDS:
        return {'code': prefix, 'label': _KINDS[prefix]}
    return {'code': 'other', 'label': '其他'}


def evidence_kinds(report):
    out = {}
    rows = report.get('evidence') if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        evidence_id = row.get('id')
        if isinstance(evidence_id, str) and evidence_id:
            out[evidence_id] = evidence_kind(evidence_id)
    return out


def _limitation_texts(report):
    rows = report.get('limitations') if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, str)]


def _status_phrase(name, components):
    label = _LABELS.get(name, name)
    comp = components.get(name) if isinstance(components, dict) else None
    if not isinstance(comp, dict):
        return label
    status = comp.get('status')
    if status in ('missing', 'insufficient') or comp.get('score') is None:
        return label + '不可算'
    if status == 'partial':
        return label + '部分规则不计'
    return label


def _joined(affects, components):
    phrases = [_status_phrase(name, components) for name in affects]
    return '；'.join(phrases) if phrases else '影响范围未核实'


def _describe_missing(key, affects, components, sample, texts):
    detail = _joined(affects, components)
    if key == 'volume_ratio5':
        return {'gap': 'volume_ratio5', 'affects': affects,
                'text': f'成交量不足以计算 volume_ratio5 → {detail}'}
    if key == 'volume_ratio5==0':
        return {'gap': 'volume_ratio5', 'affects': affects,
                'text': f'volume_ratio5 为 0（零成交或零均量）→ {detail}'}
    if key == 'macd':
        if sample is not None and sample < MACD_MIN_BARS and any('不足 60' in text for text in texts):
            gap = '不足 60'
        else:
            gap = 'MACD'
        if sample is not None and sample < MACD_MIN_BARS:
            lead = f'连续样本 {sample} 根，不足 {MACD_MIN_BARS}，MACD 缺失'
        else:
            lead = 'MACD 缺失'
        return {'gap': gap, 'affects': affects, 'text': f'{lead} → {detail}'}
    if key == 'rsi14':
        if sample is not None and sample < RSI14_MIN_BARS:
            lead = f'连续样本 {sample} 根，不足 {RSI14_MIN_BARS}，RSI14 缺失'
        else:
            lead = 'RSI14 缺失'
        return {'gap': 'RSI14', 'affects': affects, 'text': f'{lead} → {detail}'}
    if key == 'change20':
        return {'gap': 'change20', 'affects': affects, 'text': f'change20 缺失 → {detail}'}
    if key == 'change1':
        return {'gap': 'change1', 'affects': affects,
                'text': f'当日涨跌 change1 缺失，不能判断当日量价方向 → {detail}'}
    if key == 'bias20':
        return {'gap': 'bias20', 'affects': affects, 'text': f'bias20 缺失 → {detail}'}
    if key == 'trend':
        return {'gap': 'trend', 'affects': affects, 'text': f'趋势标签缺失或数据不足 → {detail}'}
    return {'gap': str(key), 'affects': [], 'text': '影响范围未核实'}


def _score_components(tech, assessment):
    comps = assessment.get('components') if isinstance(assessment, dict) else None
    if isinstance(comps, dict) and any(isinstance(comps.get(key), dict) for key, _label in COMPONENTS):
        return comps
    try:
        from tech_score import evaluate
        scored = evaluate(tech)
    except Exception:
        return None
    comps = scored.get('components') if isinstance(scored, dict) else None
    return comps if isinstance(comps, dict) else None


def _indicator_gaps(tech, components, texts):
    grouped = {}
    order = []
    for name, _label in COMPONENTS:
        comp = components.get(name)
        if not isinstance(comp, dict):
            continue
        missing = comp.get('missing')
        if not isinstance(missing, list):
            if comp.get('status') in ('missing', 'partial', 'insufficient'):
                token = '__status__:' + name
                if token not in grouped:
                    grouped[token] = []
                    order.append(token)
            continue
        for item in missing:
            if not isinstance(item, str) or not item:
                token = '__blank__'
            else:
                token = item
            if token not in grouped:
                grouped[token] = []
                order.append(token)
            if name in _LABELS and name not in grouped[token]:
                grouped[token].append(name)
    sample = tech.get('sample')
    sample_n = sample if type(sample) is int and sample >= 0 else None
    gaps = []
    for token in order:
        affects = grouped[token]
        if token.startswith('__') or token not in _KNOWN_MISSING:
            gaps.append({'gap': token.split(':', 1)[-1], 'affects': [], 'text': '影响范围未核实'})
            continue
        gaps.append(_describe_missing(token, affects, components, sample_n, texts))
    return gaps


def _material_gaps(texts):
    gaps = []
    for needle, gap, text in _MATERIAL:
        if any(needle in line for line in texts):
            gaps.append({'gap': gap, 'affects': [], 'text': text})
    return gaps


def gap_impacts(report):
    """缺什么 → 影响哪个分项或哪类材料。判断不了就写影响范围未核实。"""
    if not isinstance(report, dict):
        return []
    texts = _limitation_texts(report)
    tech = report.get('technical')
    gaps = []
    if not isinstance(tech, dict):
        if any('日 K 获取失败' in line for line in texts):
            gaps.append({
                'gap': '日 K 获取失败',
                'affects': [key for key, _label in COMPONENTS],
                'text': '日 K 获取失败，全部分项与技术指标不可用',
            })
        else:
            gaps.append({
                'gap': '技术指标未取得',
                'affects': [key for key, _label in COMPONENTS],
                'text': '行情或技术指标未取得，全部分项与技术指标不可用',
            })
    else:
        components = _score_components(tech, report.get('assessment') if isinstance(report.get('assessment'), dict) else None)
        if components is None:
            gaps.append({'gap': '技术画像', 'affects': [], 'text': '影响范围未核实'})
        else:
            gaps.extend(_indicator_gaps(tech, components, texts))
    gaps.extend(_material_gaps(texts))
    return gaps


def attach_disclosure(row):
    """给已取出的报告行附加只读字段。调用方负责不把这些字段写回库。"""
    if not isinstance(row, dict):
        return
    report = row.get('report') if isinstance(row.get('report'), dict) else None
    delta = row.get('delta')
    screen = disclosure_items(row, report, delta)
    kinds = evidence_kinds(report)
    impacts = gap_impacts(report)
    row['first_screen'] = screen
    row['evidence_kinds'] = kinds
    row['gap_impacts'] = impacts
