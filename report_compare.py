"""正式报告对比接入模块（T03 小补丁）。

调用链：
  Analysis.get(id) → report_compare.build_delta(analysis, row) → payload/delta
  web/analysis.js render(d) → 渲染 d.delta

不改指标计算、不碰批次/缠论。
"""
from __future__ import annotations

import json
from typing import Optional

from analysis import has_usable_technical
from compare import compare_reports, choose_baseline, COMPARE_VERSION  # noqa: F401

__all__ = ["build_delta", "compare_reports", "choose_baseline", "COMPARE_VERSION",
           "delta_view", "DEFAULT_METRIC_ORDER"]


DEFAULT_METRIC_ORDER = (
    "close", "change1", "change20", "bias20", "volume_ratio5", "rsi14",
    "macd_hist", "trend", "sample",
)

METRIC_LABELS = {
    "close": "收盘价", "change1": "当日涨跌（%）", "change20": "近20日涨跌（%）",
    "bias20": "偏离MA20（%）", "volume_ratio5": "较前5日均量（倍）",
    "rsi14": "RSI14", "macd_hist": "MACD柱值", "sample": "有效样本数",
}


def _payload_from_row(row: dict) -> dict:
    """Analysis.get 返回行 → compare 所需 payload。"""
    report = row.get("report")
    if report is None:
        report = json.loads(row.get("payload") or "{}") if isinstance(row.get("payload"), str) else (row.get("payload") or {})
    return {
        "code": row.get("code"),
        "date": row.get("day") or report.get("date"),
        "generated_at": report.get("generated_at") or row.get("created"),
        "prompt_version": report.get("prompt_version"),
        "technical": report.get("technical") or {},
        "assessment": report.get("assessment"),
        "ai": report.get("ai"),
    }


def build_delta(analysis, row: dict) -> Optional[dict]:
    """为单份报告附加 delta。返回展示结构（status_text/rows），raw 为完整对比结果。

    row: Analysis.get() 的返回 dict（含 code/day/report）
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
    return view


def delta_view(delta: Optional[dict], metric_order=DEFAULT_METRIC_ORDER) -> Optional[dict]:
    """给前端的精简结构：状态文案 + 有序指标行。"""
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
