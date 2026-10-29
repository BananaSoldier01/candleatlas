"""正式报告对比接入模块（T03 小补丁）。

调用链：
  Analysis.get(id) → report_compare.build_delta(analysis, row) → payload/delta
  web/analysis.js render(d) → 渲染 d.delta

视图层可附加 kind / notices / process。不改 compare_reports 的输出，不改指标计算。
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Optional

from analysis import has_usable_technical
from compare import compare_reports, choose_baseline, COMPARE_VERSION  # noqa: F401

__all__ = ["build_delta", "compare_reports", "choose_baseline", "COMPARE_VERSION",
           "delta_view", "DEFAULT_METRIC_ORDER", "notice_view", "process_view",
           "MARK_INCOMPARABLE", "MARK_PROMPT", "PROCESS_NOTE", "BACKFILL_NOTE"]


DEFAULT_METRIC_ORDER = (
    "close", "change1", "change20", "bias20", "volume_ratio5", "rsi14",
    "macd_hist", "trend", "sample",
)

METRIC_LABELS = {
    "close": "收盘价", "change1": "当日涨跌（%）", "change20": "近20日涨跌（%）",
    "bias20": "偏离MA20（%）", "volume_ratio5": "较前5日均量（倍）",
    "rsi14": "RSI14", "macd_hist": "MACD柱值", "sample": "有效样本数",
}

# 红绿只留给收盘价和涨跌幅。均线、MACD 虽是价格单位，视图上仍算指标。
_PRICE_METRICS = frozenset({"close", "change1", "change20"})
_VOLUME_METRICS = frozenset({"volume_ratio5"})
_COUNT_METRICS = frozenset({"sample"})

_SH = dt.timezone(dt.timedelta(hours=8))
MISSING = "未记录"
MARK_INCOMPARABLE = "与本次不可比"
MARK_PROMPT = "AI 文本口径不同"
PROCESS_NOTE = "只比较方法与取数范围，不比较结果好坏。"
BACKFILL_NOTE = "基线可能是事后补做，不能当作当时可知信息。"
PROCESS_ROWS = (
    {"key": "method", "label": "方法"},
    {"key": "window", "label": "窗口"},
    {"key": "sample", "label": "样本"},
    {"key": "ai", "label": "是否含 AI"},
    {"key": "backfilled", "label": "是否事后补做"},
    {"key": "prompt_version", "label": "prompt_version"},
)


def _metric_class(key: str) -> str:
    if key in _PRICE_METRICS:
        return "price"
    if key in _VOLUME_METRICS:
        return "volume"
    if key in _COUNT_METRICS:
        return "count"
    return "indicator"


def _row_kind(d: dict, hide: bool) -> tuple[str, str]:
    """视图类型。None 保持缺失，不转成 0。"""
    old, new, diff = d.get("old"), d.get("new"), d.get("diff")
    direction = d.get("direction")
    if direction == "window_sensitive":
        return "incomparable", "窗口不同"
    # 双方都没有值时先保住“不补零”，即使整份报告被标成不可比。
    if direction == "both_missing" or (old is None and new is None):
        return "both_missing", "双方缺失"
    if hide or direction == "not_comparable":
        return "incomparable", "不可比"
    if old is None and new is not None:
        return "added", "新增"
    if old is not None and new is None:
        return "removed", "消失"
    if diff == 0 or old == new:
        return "unchanged", "没变"
    return "changed", "变了"


def _payload_from_row(row: dict) -> dict:
    """Analysis.get 返回行 → compare 所需 payload。缺 disclosures 时给 None，不报错。"""
    report = row.get("report")
    if report is None:
        raw = row.get("payload")
        if isinstance(raw, str):
            try:
                report = json.loads(raw or "{}")
            except (ValueError, TypeError):
                report = {}
        else:
            report = raw or {}
    if not isinstance(report, dict):
        report = {}
    disclosures = report.get("disclosures")
    return {
        "code": row.get("code") or report.get("code"),
        "date": row.get("day") or report.get("date"),
        "generated_at": report.get("generated_at") or row.get("created"),
        "prompt_version": report.get("prompt_version"),
        "technical": report.get("technical") or {},
        "assessment": report.get("assessment"),
        "ai": report.get("ai"),
        "model": report.get("model"),
        "disclosures": disclosures if isinstance(disclosures, dict) else None,
    }


def _disclosure_items(payload) -> list:
    if not isinstance(payload, dict):
        return []
    block = payload.get("disclosures")
    if not isinstance(block, dict):
        return []
    items = block.get("items")
    if not isinstance(items, list):
        return []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if isinstance(ident, bool) or ident is None:
            continue
        if isinstance(ident, (int, str)):
            text = str(ident).strip()
            if text:
                rows.append((text, item))
    return rows


def notice_view(old_payload, new_payload, backfilled: bool = False) -> dict:
    """按公告 id 比较材料清单。只描述增减，不解释含义。"""
    old_by = {ident: item for ident, item in _disclosure_items(old_payload)}
    new_by = {ident: item for ident, item in _disclosure_items(new_payload)}
    rows = []
    for ident in set(old_by) | set(new_by):
        if ident in old_by and ident in new_by:
            kind, label, src = "unchanged", "没变", new_by[ident]
        elif ident in new_by:
            kind, label, src = "added", "新增", new_by[ident]
        else:
            kind, label, src = "removed", "消失", old_by[ident]
        title = src.get("title") if isinstance(src.get("title"), str) else ""
        notice_date = src.get("notice_date") if isinstance(src.get("notice_date"), str) else ""
        rows.append({
            "id": ident, "title": title, "kind": kind, "kind_label": label,
            "notice_date": notice_date,
        })
    order = {"added": 0, "removed": 1, "unchanged": 2}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["notice_date"], r["id"]))
    added = sum(r["kind"] == "added" for r in rows)
    removed = sum(r["kind"] == "removed" for r in rows)
    same = sum(r["kind"] == "unchanged" for r in rows)
    summary = (f"材料清单的变化：新增 {added} 项，消失 {removed} 项，没变 {same} 项。"
               "只记录材料清单的增减，不判断利好或利空。")
    return {"items": rows, "summary": summary, "note": BACKFILL_NOTE if backfilled else ""}


def _text(value) -> str:
    return value if isinstance(value, str) and value else ""


def _report_of(item) -> dict:
    if isinstance(item, dict) and isinstance(item.get("report"), dict):
        return item["report"]
    return {}


def _code_of(item) -> str:
    if not isinstance(item, dict):
        return ""
    code = item.get("code")
    if isinstance(code, str) and code:
        return code
    return _text(_report_of(item).get("code"))


def _day_of(item) -> str:
    if not isinstance(item, dict):
        return ""
    day = item.get("day")
    if isinstance(day, str) and day:
        return day
    return _text(_report_of(item).get("date"))


def _created_of(item) -> str:
    if isinstance(item, dict) and isinstance(item.get("created"), str):
        return item["created"]
    return ""


def _shanghai_day(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            return dt.date.fromisoformat(text[:10]).isoformat() if len(text) >= 10 else None
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_SH)
    else:
        when = when.astimezone(_SH)
    return when.date().isoformat()


def _window_parts(assessment) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(assessment, dict):
        return None, None
    rule = assessment.get("rule_version")
    rule_text = rule.strip() if isinstance(rule, str) and rule.strip() else None
    window = assessment.get("window")
    meta = assessment.get("meta") if isinstance(assessment.get("meta"), dict) else {}
    if window is None:
        window = meta.get("window")
    context = meta.get("context") if isinstance(meta.get("context"), dict) else {}
    if window is None:
        window = context.get("window")
    if isinstance(window, bool) or window is None:
        shown = None
    elif isinstance(window, int):
        shown = str(window)
    elif isinstance(window, float) and window == window and window not in (float("inf"), float("-inf")):
        shown = str(int(window)) if window == int(window) else str(window)
    elif isinstance(window, str) and window.strip():
        shown = window.strip()
    else:
        shown = None
    return shown, rule_text


def _window_cell(assessment, current_assessment, is_current: bool) -> str:
    window, rule = _window_parts(assessment)
    if window is None and rule is None:
        return MISSING
    parts = [f"窗口 {window}" if window is not None else "窗口未记录",
             f"规则 {rule}" if rule is not None else "规则未记录"]
    text = " · ".join(parts)
    if not is_current and rule is not None:
        _, current_rule = _window_parts(current_assessment)
        if current_rule is not None and current_rule != rule:
            text += " · 规则版本与本次不同"
    return text


def _sample_cell(technical) -> str:
    if not isinstance(technical, dict) or "sample" not in technical:
        return MISSING
    sample = technical.get("sample")
    if isinstance(sample, bool) or not isinstance(sample, (int, float)):
        return MISSING
    if isinstance(sample, float) and (sample != sample or sample in (float("inf"), float("-inf"))):
        return MISSING
    if isinstance(sample, float):
        return str(int(sample)) if sample == int(sample) else str(sample)
    return str(sample)


def _ai_cell(report: dict) -> str:
    if "ai" not in report and "model" not in report:
        return MISSING
    ai = report.get("ai")
    model = report.get("model")
    if isinstance(ai, str):
        ai_on = bool(ai.strip())
    elif isinstance(ai, (dict, list)):
        ai_on = bool(ai)
    else:
        ai_on = ai not in (None, False)
    model_on = isinstance(model, str) and bool(model.strip())
    return "含 AI" if ai_on or model_on else "不含 AI"


def _backfill_cell(report: dict, day: str) -> str:
    gen = report.get("generated_at") if isinstance(report, dict) else None
    if not isinstance(gen, str) or not gen.strip():
        return MISSING
    generated = _shanghai_day(gen)
    observed = day[:10] if isinstance(day, str) and len(day) >= 10 else ""
    if not generated or not observed:
        return MISSING
    return "是" if generated > observed else "否"


def _method_diff_summary(current: str, other: str) -> str:
    """只摘差异附近的一小段，不把整段方法说明贴进表格。"""
    limit = 24
    index = 0
    while index < len(current) and index < len(other) and current[index] == other[index]:
        index += 1

    def clip(text: str) -> str:
        start = max(0, index - 4)
        frag = text[start:start + limit]
        prefix = "…" if start else ""
        suffix = "…" if start + limit < len(text) else ""
        return prefix + frag + suffix

    return f"本次「{clip(current)}」该份「{clip(other)}」"


def _method_cell(current_method: str, other_method: str, is_current: bool) -> str:
    if is_current:
        return "与本次相同" if current_method else MISSING
    if not other_method:
        return MISSING
    if not current_method:
        return "本次方法未记录"
    if current_method == other_method:
        return "与本次相同"
    return "与本次不同：" + _method_diff_summary(current_method, other_method)


def _eligible_process_item(item, code: str, day: str, created: str, current_id) -> bool:
    if not isinstance(item, dict) or item.get("status") != "complete":
        return False
    if _code_of(item) != code:
        return False
    report = _report_of(item)
    if not has_usable_technical(report.get("technical")):
        return False
    item_day = _day_of(item)
    if not item_day or not day or item_day > day:
        return False
    if item_day == day and item.get("id") != current_id and _created_of(item) > created:
        return False
    return True


def process_view(items, current_id) -> dict:
    """同一股票、观察日不晚于当前的最近至多 4 份报告，并排看做法。

    不排名、不打分。method 不同沿用 compare.py：整列标不可比。
    prompt_version 不同只说明 AI 文本口径不同，不把整列标成不可比。
    """
    rows = [dict(item) for item in PROCESS_ROWS]
    empty = {"note": PROCESS_NOTE, "columns": [], "rows": rows}
    if not isinstance(items, list):
        return empty
    current = next((item for item in items if isinstance(item, dict) and item.get("id") == current_id), None)
    if current is None:
        return empty
    code, day, created = _code_of(current), _day_of(current), _created_of(current)
    if not _eligible_process_item(current, code, day, created, current_id):
        return empty
    eligible = [item for item in items if _eligible_process_item(item, code, day, created, current_id)]
    # 同一 id 只留一条，避免重复列。
    unique = []
    seen = set()
    for item in eligible:
        ident = item.get("id")
        if ident in seen:
            continue
        seen.add(ident)
        unique.append(item)
    unique.sort(key=lambda item: (_day_of(item), _created_of(item), str(item.get("id") or "")), reverse=True)
    chosen = unique[:4]
    if current_id not in {item.get("id") for item in chosen}:
        chosen = chosen[:3] + [current]
    chosen.sort(key=lambda item: (
        _day_of(item), _created_of(item),
        1 if item.get("id") == current_id else 0,
        str(item.get("id") or ""),
    ))

    current_report = _report_of(current)
    current_tech = current_report.get("technical") if isinstance(current_report.get("technical"), dict) else {}
    current_method = _text(current_tech.get("method"))
    current_prompt = current_report.get("prompt_version")
    current_assessment = current_report.get("assessment")
    columns = []
    for item in chosen:
        report = _report_of(item)
        tech = report.get("technical") if isinstance(report.get("technical"), dict) else {}
        is_current = item.get("id") == current_id
        method = _text(tech.get("method"))
        method_diff = (not is_current) and bool(current_method and method and current_method != method)
        prompt_diff = (not is_current) and report.get("prompt_version") != current_prompt
        marks = []
        if method_diff:
            marks.append(MARK_INCOMPARABLE)
        if prompt_diff:
            marks.append(MARK_PROMPT)
        item_day = _day_of(item)
        columns.append({
            "id": "" if item.get("id") is None else str(item.get("id")),
            "day": item_day or MISSING,
            "current": bool(is_current),
            "marks": marks,
            "method_incomparable": method_diff,
            "prompt_differs": prompt_diff,
            "cells": {
                "method": _method_cell(current_method, method, is_current),
                "window": _window_cell(report.get("assessment"), current_assessment, is_current),
                "sample": _sample_cell(tech),
                "ai": _ai_cell(report),
                "backfilled": _backfill_cell(report, item_day),
                "prompt_version": _text(report.get("prompt_version")) or MISSING,
            },
        })
    return {"note": PROCESS_NOTE, "columns": columns, "rows": rows}


def build_delta(analysis, row: dict) -> Optional[dict]:
    """为单份报告附加 delta。返回展示结构（status_text/rows），raw 为完整对比结果。

    row: Analysis.get() 的返回 dict（含 code/day/report）
    notices / process 失败时不拖垮原有对比。
    """
    code = row.get("code") or (row.get("report") or {}).get("code")
    day = row.get("day") or (row.get("report") or {}).get("date")
    if not code or not day:
        return None
    current = _payload_from_row(row)

    with analysis.db() as db:
        rows = db.execute(
            "SELECT id,code,day,created,status,phase,payload,error FROM reports "
            "WHERE code=? AND status='complete' ORDER BY day DESC, created DESC",
            (code,),
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["report"] = json.loads(d.pop("payload")) if d["payload"] else None
        # Legacy complete rows may still lack the price data needed for comparison.
        if not isinstance(d["report"], dict) or not has_usable_technical(d["report"].get("technical")):
            continue
        items.append(d)

    baseline_row = choose_baseline(items, code, day)
    current_created = row.get("created") or current.get("generated_at") or ""
    if baseline_row is not None and baseline_row.get("day") == day:
        # 同日：只接受 created 严格早于当前报告的版本
        if (baseline_row.get("created") or "") >= current_created and baseline_row.get("id") != row.get("id"):
            older = [r for r in items
                     if r.get("day") == day and r.get("id") != row.get("id")
                     and (r.get("created") or "") < current_created]
            older.sort(key=lambda r: (r.get("created") or "", r.get("id") or ""), reverse=True)
            baseline_row = older[0] if older else None
        elif baseline_row.get("id") == row.get("id"):
            older = [r for r in items
                     if r.get("day") == day and r.get("id") != row.get("id")
                     and (r.get("created") or "") < current_created]
            older.sort(key=lambda r: (r.get("created") or "", r.get("id") or ""), reverse=True)
            baseline_row = older[0] if older else None

    if baseline_row is None:
        raw = compare_reports(None, current, context={"selection_rule": "none"})
    else:
        old = _payload_from_row(baseline_row)
        if old.get("date") == day:
            rule = "same_day_previous_version"
        else:
            rule = "same_code_earlier_observation_day_latest"
        raw = compare_reports(old, current, context={
            "selection_rule": rule,
            "baseline_id": baseline_row.get("id"),
        })
    # 前端 deltaHTML 读取 status_text/rows；此处必须做结构转换
    view = delta_view(raw)
    if view is None:
        return None
    view["raw"] = raw
    try:
        backfilled = bool((raw.get("selection") or {}).get("backfilled_baseline"))
        old_payload = _payload_from_row(baseline_row) if baseline_row else None
        view["notices"] = notice_view(old_payload, current, backfilled=backfilled)
    except Exception:
        pass
    try:
        view["process"] = process_view(items, row.get("id"))
    except Exception:
        pass
    return view


def delta_view(delta: Optional[dict], metric_order=DEFAULT_METRIC_ORDER) -> Optional[dict]:
    """给前端的精简结构：状态文案 + 有序指标行。不改 compare 契约字段。"""
    if not delta:
        return None
    status = delta.get("status")
    status_text = {
        "first_analysis": "首次分析，无更早报告可对比",
        "comparable": "与上一份报告可比",
        "limited": "有限可比（窗口或部分指标受限）",
        "incomparable": "口径不可比，不展示涨跌方向",
    }.get(status, status)
    rows = []
    by = {d["metric"]: d for d in delta.get("deltas") or []}
    for key in metric_order:
        d = by.get(key)
        if not d:
            continue
        hide = d.get("display") == "hidden_direction" or d.get("direction") in (
            "not_comparable", "window_sensitive",
        )
        kind, kind_label = _row_kind(d, bool(hide))
        rows.append({
            "metric": key,
            "label": METRIC_LABELS.get(key, key),
            "old": d.get("old"),
            "new": d.get("new"),
            "diff": d.get("diff"),
            "direction": d.get("direction"),
            "comparable": d.get("comparable"),
            "display": d.get("display") or ("hidden_direction" if hide else "full"),
            "hide_direction": bool(hide),
            "note": d.get("note") or "",
            "kind": kind,
            "kind_label": kind_label,
            "metric_class": _metric_class(key),
        })
    return {
        "status": status,
        "status_text": status_text,
        "comparable": delta.get("comparable"),
        "selection": delta.get("selection"),
        "reasons": delta.get("reasons"),
        "notes": delta.get("notes"),
        "rows": rows,
    }
