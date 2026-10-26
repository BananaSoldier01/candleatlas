"""T03 报告对比纯函数 — 比较同一股票两份分析报告的可复核变化。

口径:
  - 只比程序指标与可用性，不对 AI 文本做“利好增加”断言
  - 缺失不转 0；规则版本/复权说明/窗口不同则标不可比
  - “前一份”默认=同股票、更早观察日的最近报告；同日重生成是版本差异
  - 历史观察日不得用更晚观察日的报告做基线
"""
from __future__ import annotations

from typing import Any, Optional

COMPARE_VERSION = "guanshi-report-delta-2"

# 指标定义: key, 数值型, 单位标签, 方向语义（+1 越高越强 / -1 越高风险越大 / 0 无方向）
METRICS = (
    ("close", True, "price", 0),
    ("change1", True, "pct", 1),
    ("ma5", True, "price", 0),
    ("ma10", True, "price", 0),
    ("ma20", True, "price", 0),
    ("ma60", True, "price", 0),
    ("change20", True, "pct", 1),
    ("bias20", True, "pct", 0),
    ("volume_ratio5", True, "ratio", 0),
    ("rsi14", True, "index", -1),
    ("macd_dif", True, "price", 1),
    ("macd_dea", True, "price", 1),
    ("macd_hist", True, "price", 1),
    ("sample", True, "count", 0),
)

NON_NUMERIC = ("trend", "asof", "method")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return None if f != f else f
    return None


def _technical(payload: dict) -> dict:
    return payload.get("technical") or {}


def _asof(payload: dict) -> Optional[str]:
    t = _technical(payload)
    return t.get("asof") or payload.get("date")


def compare_reports(old: Optional[dict], new: dict, context: Optional[dict] = None) -> dict:
    """比较 old/new 两份报告 payload（analysis.run 产生的 dict）。

    old 为 None 表示首次分析。context 可含 {'selection_rule': ..., 'note': ...}
    """
    ctx = dict(context or {})
    if not isinstance(new, dict):
        raise TypeError("new must be a dict")
    if old is not None and not isinstance(old, dict):
        raise TypeError("old must be a dict or None")

    new_t = _technical(new)
    new_day = new.get("date")
    new_asof = _asof(new)

    if old is None:
        return {
            "compare_version": COMPARE_VERSION,
            "status": "first_analysis",
            "comparable": False,
            "reasons": ["没有更早报告，本次为首次分析"],
            "selection": {"rule": "none"},
            "baseline": None,
            "current": {"date": new_day, "asof": new_asof, "generated_at": new.get("generated_at"),
                        "rule_version": new.get("prompt_version"), "sample": new_t.get("sample")},
            "deltas": [],
            "labels": {},
            "notes": ["首次分析，无可比基线。"],
        }

    old_t = _technical(old)
    old_day = old.get("date")
    old_asof = _asof(old)
    old_gen = old.get("generated_at")
    new_gen = new.get("generated_at")

    reasons: list[str] = []
    comparable = True

    # 观察日关系
    if old_day and new_day:
        if old_day > new_day:
            comparable = False
            reasons.append("基线观察日晚于当前观察日，禁止用未来报告回看")
        elif old_day == new_day:
            reasons.append("同一观察日的不同版本；属于版本差异而非跨日变化")
        else:
            reasons.append(f"基线观察日 {old_day} → 当前 {new_day}")

    # 事后补做
    backfilled = False
    if old_gen and new_gen and old_day and new_day and old_day < new_day and old_gen > new_gen:
        backfilled = True
        reasons.append("基线生成时间晚于当前报告生成时间，存在事后补做")

    # 口径
    old_method = old_t.get("method")
    new_method = new_t.get("method")
    if old_method and new_method and old_method != new_method:
        comparable = False
        reasons.append("指标 method 口径不同，不可比")
    if old.get("prompt_version") != new.get("prompt_version"):
        reasons.append("prompt_version 不同，AI 文本不参与数值对比")

    # 指标 delta
    deltas = []
    for key, is_num, unit, direction in METRICS:
        ov, nv = old_t.get(key), new_t.get(key)
        if not is_num:
            continue
        on, nn = _num(ov), _num(nv)
        if on is None and nn is None:
            deltas.append({"metric": key, "unit": unit, "old": None, "new": None, "diff": None,
                           "direction": "both_missing", "comparable": False,
                           "note": "双方缺失，不补零"})
            continue
        if on is None or nn is None:
            deltas.append({"metric": key, "unit": unit, "old": on, "new": nn, "diff": None,
                           "direction": "one_missing",
                           "comparable": False,
                           "note": "单侧缺失，不把 null 当 0"})
            continue
        diff = round(nn - on, 6)
        if diff > 0:
            dir_label = "up"
        elif diff < 0:
            dir_label = "down"
        else:
            dir_label = "flat"
        deltas.append({
            "metric": key, "unit": unit,
            "old": on, "new": nn, "diff": diff,
            "direction": dir_label,
            "score_direction": direction,
            "comparable": True,
            "note": "",
        })

    # 标签类
    labels = {}
    for key in ("trend",):
        labels[key] = {"old": old_t.get(key), "new": new_t.get(key),
                       "changed": old_t.get(key) != new_t.get(key)}
    labels["asof"] = {"old": old_asof, "new": new_asof, "changed": old_asof != new_asof}

    # 样本/覆盖：窗口不同 → 不得标“完全可比”
    old_sample = _num(old_t.get("sample"))
    new_sample = _num(new_t.get("sample"))
    window_mismatch = False
    init_sensitive = {"macd_dif", "macd_dea", "macd_hist", "rsi14"}
    if old_sample is not None and new_sample is not None and old_sample != new_sample:
        window_mismatch = True
        reasons.append(
            f"样本数 {old_sample}→{new_sample}，指标初始化窗口可能不同"
            "（MACD/RSI 依赖窗口起点；均线/change20 主要看尾部）")
        for d in deltas:
            if d.get("metric") in init_sensitive and d.get("comparable") and d.get("diff") is not None:
                d["window_init_sensitive"] = True
                d["note"] = "窗口初始化敏感：MACD/RSI 从样本起点累计，80/250 不完全可比"

    # asof 变化
    if old_asof and new_asof and old_asof != new_asof:
        reasons.append(f"数据日期 {old_asof}→{new_asof}")

    # 技术失败
    if not new_t:
        comparable = False
        reasons.append("当前报告无 technical")
    if not old_t:
        comparable = False
        reasons.append("基线报告无 technical")

    # 整体不可比时（口径不同 / 未来基线 / 缺 technical）：
    # 单条 delta 不得仍标 comparable，并抑制方向性展示
    if not comparable:
        for d in deltas:
            d["comparable"] = False
            d["display"] = "hidden_direction"
            if d.get("diff") is not None:
                d["direction_suppressed"] = True
                d["direction"] = "not_comparable"
            if not d.get("note"):
                d["note"] = "整体口径不可比，本条 diff 不作为可比变化，接入端不得展示涨跌方向"
    elif window_mismatch:
        for d in deltas:
            if d.get("metric") in init_sensitive and d.get("diff") is not None:
                d["display"] = "value_only"
                d["direction_suppressed"] = True
                d["direction"] = "window_sensitive"

    status = (
        "incomparable" if not comparable
        else "limited" if window_mismatch
        else "comparable" if not any(
            d["direction"] in ("both_missing", "one_missing") or d.get("window_init_sensitive")
            for d in deltas
        )
        else "limited" if any(d.get("diff") is not None for d in deltas)
        else "incomparable"
    )
    window_note = ("窗口不同：status=limited，禁止把本结果当成完全可比排名依据。"
                   if window_mismatch else None)

    notes = [
        "只比程序指标与数据可用性。",
        "不把 AI 文本变化解释为利好/利空增加。",
        "趋势标签变化不等于买卖信号。",
    ]
    if window_note:
        notes.append(window_note)
    if backfilled:
        notes.append("基线可能是事后补做，不能当作当时可知信息。")

    return {
        "compare_version": COMPARE_VERSION,
        "status": status,
        "comparable": comparable,
        "reasons": reasons,
        "selection": {
            "rule": ctx.get("selection_rule", "same_code_earlier_observation_day_latest"),
            "note": ctx.get("note", ""),
            "old_date": old_day,
            "new_date": new_day,
            "old_generated_at": old_gen,
            "new_generated_at": new_gen,
            "backfilled_baseline": backfilled,
        },
        "baseline": {
            "date": old_day, "asof": old_asof, "generated_at": old_gen,
            "prompt_version": old.get("prompt_version"), "sample": old_t.get("sample"),
        },
        "current": {
            "date": new_day, "asof": new_asof, "generated_at": new_gen,
            "prompt_version": new.get("prompt_version"), "sample": new_t.get("sample"),
        },
        "deltas": deltas,
        "labels": labels,
        "notes": notes,
    }


def choose_baseline(reports: list[dict], code: str, observation_day: str) -> Optional[dict]:
    """从报告列表选择“前一份”。

    规则:
      - 同 code
      - 优先观察日 < observation_day 的最近一份（跨日基线）
      - 若无跨日基线，则取同日、created 更早的最近版本（版本差异）
      - 观察日 > observation_day 的报告一律不用（防未来）
    """
    earlier = [
        r for r in reports
        if r.get("code") == code and r.get("day") and r["day"] < observation_day
    ]
    if earlier:
        earlier.sort(key=lambda r: (r["day"], r.get("created") or ""), reverse=True)
        return earlier[0]
    same_day = [
        r for r in reports
        if r.get("code") == code and r.get("day") == observation_day
        and (r.get("created") or "")  # 可排序
    ]
    # 调用方再按 created 过滤“当前报告之前”的版本；此处返回同日最近，由 build_delta 收窄
    if same_day:
        same_day.sort(key=lambda r: (r.get("created") or "", r.get("id") or ""), reverse=True)
        return same_day[0]
    return None


__all__ = ["compare_reports", "choose_baseline", "COMPARE_VERSION", "METRICS"]
