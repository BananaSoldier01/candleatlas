"""T01 可解释技术评分 — 纯函数评估器。

输入是观市 analysis.py::technical(rows) 已经算好的指标字典，不重复实现 MA/RSI/MACD。
输出是版本化、可追溯的分项画像；缺失不补零，不生成虚假完整分数。

规则版本: guanshi-tech-score-1
设计原则:
  1. 分项分离: trend / momentum / volume_coord / overheat
  2. 过热与趋势分开表达，上涨过热不计入趋势高分
  3. 量能必须结合价格方向，无条件成交量放大不加分
  4. 缺失 -> status=missing/partial，score 可为 None 或带 coverage 的部分分
  5. 同输入必得同输出（无时间、无随机、无 IO）
"""
from __future__ import annotations

from typing import Any, Optional

RULE_VERSION = "guanshi-tech-score-2"

# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    return None


def _band(value: float, bands: list[tuple[float, float, float]]) -> float:
    """bands: [(lo, hi, score), ...] 左闭右开，最后一档 hi 可用 None 表示 +inf。"""
    for lo, hi, score in bands:
        if value >= lo and (hi is None or value < hi):
            return score
    # 低于所有档位
    return bands[0][2]


def _rule(rule_id: str, input_name: str, raw: Any, points: float,
          max_points: float, threshold: str, note: str = "") -> dict:
    return {
        "id": rule_id,
        "input": input_name,
        "raw": raw,
        "points": points,
        "max_points": max_points,
        "threshold": threshold,
        "note": note,
    }


def _component(status: str, score: Optional[float], raw: dict,
               rules: list[dict], explanation: str,
               coverage: float, missing: list[str]) -> dict:
    return {
        "status": status,
        "score": score,
        "raw": raw,
        "rules": rules,
        "explanation": explanation,
        "coverage": round(coverage, 3),
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# 分项规则
# ---------------------------------------------------------------------------

def _eval_trend(t: dict) -> dict:
    """趋势强度 0-100（越高越强），过热不在本项扣分。"""
    raw = {
        "trend": t.get("trend"),
        "ma5": _num(t.get("ma5")),
        "ma10": _num(t.get("ma10")),
        "ma20": _num(t.get("ma20")),
        "bias20": _num(t.get("bias20")),
        "change20": _num(t.get("change20")),
        "macd_dif": _num(t.get("macd_dif")),
        "macd_dea": _num(t.get("macd_dea")),
        "macd_hist": _num(t.get("macd_hist")),
        "sample": t.get("sample"),
    }
    missing: list[str] = []
    rules: list[dict] = []

    # R_T_ALIGN 0-40
    align = raw["trend"]
    if align == "均线多头排列":
        align_pts, align_note = 40.0, "MA5>MA10>MA20 多头排列"
    elif align == "均线交错":
        align_pts, align_note = 18.0, "均线交叉，方向不清晰"
    elif align == "均线空头排列":
        align_pts, align_note = 0.0, "MA5<MA10<MA20 空头排列"
    else:
        align_pts, align_note = None, "trend 标签缺失或数据不足"
        missing.append("trend")
    if align_pts is not None:
        rules.append(_rule("R_T_ALIGN", "trend", align, align_pts, 40.0,
                           "多头=40 / 交错=18 / 空头=0", align_note))

    # R_T_BIAS20 0-25（站在 MA20 上方视为趋势偏强，不在此处理过热）
    bias = raw["bias20"]
    if bias is None:
        missing.append("bias20")
    else:
        pts = _band(bias, [
            (10.0, None, 25.0),
            (5.0, 10.0, 22.0),
            (0.0, 5.0, 18.0),
            (-5.0, 0.0, 10.0),
            (-10.0, -5.0, 5.0),
            (float("-inf"), -10.0, 0.0),
        ])
        rules.append(_rule(
            "R_T_BIAS20", "bias20", bias, pts, 25.0,
            ">=10:25 / 5-10:22 / 0-5:18 / -5-0:10 / -10--5:5 / <-10:0",
            "收盘相对 MA20 偏离，偏强计高，过热另记 overheat"))

    # R_T_MACD 0-25
    dif, dea, hist = raw["macd_dif"], raw["macd_dea"], raw["macd_hist"]
    if dif is None or dea is None or hist is None:
        missing.append("macd")
    else:
        if dif > dea and hist > 0:
            pts, note = 25.0, "DIF>DEA 且柱为正"
        elif dif > dea:
            pts, note = 18.0, "DIF>DEA，柱不配合"
        elif dif == dea:
            pts, note = 12.0, "DIF=DEA"
        elif dif < dea and hist < 0:
            pts, note = 0.0, "DIF<DEA 且柱为负"
        else:
            pts, note = 6.0, "DIF<DEA，柱未同步"
        rules.append(_rule(
            "R_T_MACD", "macd_dif/dea/hist", {"dif": dif, "dea": dea, "hist": hist},
            pts, 25.0, "同向+25 / 单边+18 / 平+12 / 反向+6 / 同向负+0", note))

    # R_T_CHANGE 0-10（近 20 日方向，小幅权重，与 momentum 有意重叠）
    chg = raw["change20"]
    if chg is None:
        missing.append("change20")
    else:
        pts = _band(chg, [
            (15.0, None, 10.0),
            (5.0, 15.0, 8.0),
            (0.0, 5.0, 5.0),
            (-5.0, 0.0, 3.0),
            (-15.0, -5.0, 1.0),
            (float("-inf"), -15.0, 0.0),
        ])
        rules.append(_rule(
            "R_T_CHANGE", "change20", chg, pts, 10.0,
            ">=15:10 / 5-15:8 / 0-5:5 / -5-0:3 / -15--5:1 / <-15:0",
            "与 momentum 的 R_M_CHG20 同源，权重刻意压低以缓和重复计分"))

    available_max = sum(r["max_points"] for r in rules) or 100.0
    planned_max = 100.0
    if not rules:
        return _component("missing", None, raw, rules,
                          "趋势：关键输入缺失，不给分。", 0.0, missing)
    got = sum(r["points"] for r in rules)
    score = round(got / available_max * 100.0, 1)
    coverage = available_max / planned_max
    status = "ok" if not missing else "partial"
    label = "强" if score >= 70 else "偏强" if score >= 55 else "中性" if score >= 40 else "偏弱" if score >= 25 else "弱"
    return _component(
        status, score, raw, rules,
        f"趋势{label}（{score}/100）。规则：均线排列、MA20 偏离、MACD 同向、20 日方向。",
        coverage, missing)


def _eval_momentum(t: dict) -> dict:
    """动量 0-100。RSI 不进入本项（避免与过热重复且不把高 RSI 当必涨）。"""
    raw = {
        "change20": _num(t.get("change20")),
        "macd_hist": _num(t.get("macd_hist")),
        "macd_dif": _num(t.get("macd_dif")),
        "macd_dea": _num(t.get("macd_dea")),
        "close": _num(t.get("close")),
        "sample": t.get("sample"),
    }
    missing: list[str] = []
    rules: list[dict] = []

    chg = raw["change20"]
    if chg is None:
        missing.append("change20")
    else:
        pts = _band(chg, [
            (20.0, None, 60.0),
            (10.0, 20.0, 50.0),
            (5.0, 10.0, 40.0),
            (0.0, 5.0, 30.0),
            (-5.0, 0.0, 18.0),
            (-10.0, -5.0, 8.0),
            (float("-inf"), -10.0, 0.0),
        ])
        rules.append(_rule(
            "R_M_CHG20", "change20", chg, pts, 60.0,
            ">=20:60 / 10-20:50 / 5-10:40 / 0-5:30 / -5-0:18 / -10--5:8 / <-10:0",
            "近 20 交易日前复权涨跌幅"))

    hist = raw["macd_hist"]
    dif, dea = raw["macd_dif"], raw["macd_dea"]
    close = raw["close"]
    if hist is None or dif is None or dea is None:
        missing.append("macd")
    else:
        # 用 hist/close 做无量纲强度，close 缺失则只取符号档
        if close and close > 0:
            ratio = hist / close
            if ratio >= 0.002:
                pts = 40.0
            elif ratio > 0:
                pts = 28.0
            elif ratio == 0:
                pts = 18.0
            elif ratio > -0.002:
                pts = 10.0
            else:
                pts = 0.0
            thr = "hist/close >=0.002:40 / >0:28 / =0:18 / >-0.002:10 / <=-0.002:0"
            note = f"MACD 柱/收盘={ratio:.5f}"
        else:
            pts = 20.0 if hist > 0 else 12.0 if hist == 0 else 0.0
            thr = "符号：正=20 / 零=12 / 负=0"
            note = "close 无效，仅用柱符号"
        if dif > dea and pts < 40.0:
            pts = min(40.0, pts + 6.0)
            note += "；DIF>DEA 附加"
        rules.append(_rule("R_M_MACD_HIST", "macd_hist", hist, pts, 40.0, thr, note))

    available_max = sum(r["max_points"] for r in rules) or 100.0
    if not rules:
        return _component("missing", None, raw, rules,
                          "动量：change20 或 MACD 全缺，不给分。", 0.0, missing)
    got = sum(r["points"] for r in rules)
    score = round(got / available_max * 100.0, 1)
    coverage = available_max / 100.0
    status = "ok" if not missing else "partial"
    label = "强" if score >= 70 else "偏强" if score >= 55 else "中性" if score >= 40 else "偏弱" if score >= 25 else "弱"
    return _component(
        status, score, raw, rules,
        f"动量{label}（{score}/100）。不使用 RSI 计入动量，避免把高 RSI 当上涨概率。",
        coverage, missing)


def _eval_volume(t: dict, context: Optional[dict] = None) -> dict:
    """量能配合 0-100。

    周期对齐（复核修订）: volume_ratio5 是日频量能，价格方向必须用
    当日涨跌 change1（或 prev_close 推算），不得用 change20 代替。
    无当日方向时只给无方向活跃度粗分，绝不写“放量上行”。
    """
    raw = {
        "volume_ratio5": _num(t.get("volume_ratio5")),
        "change1": None,
        "change20": _num(t.get("change20")),
        "bias20": _num(t.get("bias20")),
        "close": _num(t.get("close")),
        "sample": t.get("sample"),
    }
    missing: list[str] = []
    rules: list[dict] = []

    chg1 = _num(t.get("change1"))
    if chg1 is None and isinstance(context, dict):
        chg1 = _num(context.get("change1"))
        if chg1 is None:
            close = raw["close"]
            prev = _num(context.get("prev_close"))
            if close is not None and prev is not None and prev > 0:
                chg1 = round((close / prev - 1.0) * 100.0, 4)
    raw["change1"] = chg1

    vr = raw["volume_ratio5"]
    if vr is None:
        missing.append("volume_ratio5")
        return _component(
            "missing", None, raw, rules,
            "量能：volume_ratio5 缺失（可能零成交或样本不足），不给分。",
            0.0, missing)
    if vr == 0:
        rules.append(_rule("R_V_ZERO", "volume_ratio5", vr, 0.0, 0.0,
                           "vr==0 -> 不计分", "零成交或零均量，量能不可解释"))
        return _component(
            "insufficient", None, raw, rules,
            "量能：volume_ratio5=0（零成交/零均量），不产生量能分。",
            0.0, ["volume_ratio5==0"])

    if chg1 is None:
        missing.append("change1")
        pts = 20.0 if vr >= 1.5 else 35.0 if 0.8 <= vr <= 1.5 else 15.0
        rules.append(_rule("R_V_ACTIVE_ONLY", "volume_ratio5", vr, pts, 100.0,
                           "缺 change1：1.5+:20 / 0.8-1.5:35 / 其他:15",
                           "无当日涨跌，不能判放量上/下行；change20 不参与量价方向"))
        return _component(
            "partial", round(pts, 1), raw, rules,
            "量能：缺当日涨跌 change1，仅有无方向活跃度粗分；不给出放量上/下行判断。",
            0.35, missing)

    up, down = chg1 >= 0, chg1 < 0
    if up and vr >= 2.5:
        pts, note = 90.0, "放量上行，配合积极（也可能是情绪高潮，见 overheat）"
    elif up and vr >= 1.5:
        pts, note = 78.0, "温和放量上行"
    elif up and vr >= 0.8:
        pts, note = 55.0, "平量上行"
    elif up and vr < 0.8:
        pts, note = 35.0, "缩量上行，量价可能背离"
    elif down and vr >= 2.5:
        pts, note = 12.0, "放量下行，供给压力大（与 20 日趋势无关）"
    elif down and vr >= 1.5:
        pts, note = 22.0, "放量下跌，配合较差"
    elif down and vr >= 0.8:
        pts, note = 40.0, "平量下行"
    else:
        pts, note = 55.0, "缩量下行，抛压可能减轻（不等于见底）"
    rules.append(_rule(
        "R_V_COORD", "volume_ratio5+change1",
        {"vr": vr, "chg1": chg1, "chg20_ignored": raw["change20"]},
        pts, 100.0,
        "当日方向×日频量比（放量上行90 / 温放上行78 / 平量上行55 / 缩量上行35 / 放量下跌12-22 / 平量下跌40 / 缩量下跌55）",
        note + "；方向用 change1，不用 change20"))

    return _component(
        "ok", round(pts, 1), raw, rules,
        f"量能配合 {pts}/100。{note}（价格方向=当日 change1={chg1}）",
        1.0, [])


def _eval_overheat(t: dict, context: Optional[dict] = None) -> dict:
    """过热/回撤风险 0-100（越高风险越大）。与 trend 分离。"""
    chg1 = _num(t.get("change1"))
    if chg1 is None and isinstance(context, dict):
        chg1 = _num(context.get("change1"))
    raw = {
        "rsi14": _num(t.get("rsi14")),
        "bias20": _num(t.get("bias20")),
        "change20": _num(t.get("change20")),
        "change1": chg1,
        "volume_ratio5": _num(t.get("volume_ratio5")),
        "close": _num(t.get("close")),
        "sample": t.get("sample"),
    }
    missing: list[str] = []
    rules: list[dict] = []

    rsi = raw["rsi14"]
    if rsi is None:
        missing.append("rsi14")
    else:
        pts = _band(rsi, [
            (80.0, None, 35.0),
            (70.0, 80.0, 28.0),
            (60.0, 70.0, 18.0),
            (40.0, 60.0, 8.0),
            (25.0, 40.0, 6.0),
            (float("-inf"), 25.0, 4.0),
        ])
        rules.append(_rule(
            "R_O_RSI", "rsi14", rsi, pts, 35.0,
            ">=80:35 / 70-80:28 / 60-70:18 / 40-60:8 / 25-40:6 / <25:4",
            "RSI 高只表示短期过热/回撤风险上升，不表示必跌"))

    bias = raw["bias20"]
    if bias is None:
        missing.append("bias20")
    else:
        pts = _band(bias, [
            (15.0, None, 30.0),
            (10.0, 15.0, 24.0),
            (5.0, 10.0, 16.0),
            (0.0, 5.0, 8.0),
            (float("-inf"), 0.0, 2.0),
        ])
        rules.append(_rule(
            "R_O_BIAS", "bias20", bias, pts, 30.0,
            ">=15:30 / 10-15:24 / 5-10:16 / 0-5:8 / <0:2",
            "正偏离 MA20 过大是均值回归风险"))

    chg = raw["change20"]
    if chg is None:
        missing.append("change20")
    else:
        pts = _band(chg, [
            (30.0, None, 25.0),
            (20.0, 30.0, 18.0),
            (10.0, 20.0, 10.0),
            (0.0, 10.0, 5.0),
            (float("-inf"), 0.0, 2.0),
        ])
        rules.append(_rule(
            "R_O_EXTEND", "change20", chg, pts, 25.0,
            ">=30:25 / 20-30:18 / 10-20:10 / 0-10:5 / <0:2",
            "短时间大涨后的回撤风险，不是收益预测"))

    vr = raw["volume_ratio5"]
    if vr is None:
        missing.append("volume_ratio5")
    else:
        day = raw.get("change1")
        # 量能高潮看日频：无 change1 时不用 change20 冒充，只给保守 4 分
        if day is None:
            pts, note = 4.0, "缺 change1，不把 change20 当日频方向；量能高潮不加分"
        elif vr >= 2.5 and day > 3:
            pts, note = 20.0, "天量+当日大涨，情绪高潮风险"
        elif vr >= 1.8 and day > 3:
            pts, note = 12.0, "放量+当日上涨，略有拥挤"
        elif vr >= 1.8 and day < -3:
            pts, note = 14.0, "放量下跌，回撤/出清风险"
        else:
            pts, note = 4.0, "量能未见极端"
        rules.append(_rule(
            "R_O_VOLCLIMAX", "volume_ratio5+change1", {"vr": vr, "chg1": day, "chg20": chg},
            pts, 20.0, "日频放量大涨:12-20 / 放量大跌:14 / 其他:4（需 change1）", note))

    available_max = sum(r["max_points"] for r in rules) or 100.0
    planned = 35.0 + 30.0 + 25.0 + 20.0
    if not rules:
        return _component("missing", None, raw, rules,
                          "过热风险：关键输入缺失，不给分。", 0.0, missing)
    got = sum(r["points"] for r in rules)
    score = round(got / available_max * 100.0, 1)
    coverage = available_max / planned
    status = "ok" if not missing else "partial"
    label = "高" if score >= 70 else "偏高" if score >= 55 else "中等" if score >= 40 else "偏低" if score >= 25 else "低"
    return _component(
        status, score, raw, rules,
        f"过热/回撤风险{label}（{score}/100）。高风险不等于马上下跌，低风险也不等于安全。",
        coverage, missing)


# ---------------------------------------------------------------------------
# 总分（可选，启发式）
# ---------------------------------------------------------------------------

def _total(components: dict) -> Optional[dict]:
    """启发式总分。仅当四个分项都有分数时才计算，并标记不可与缺失样本比较。"""
    needed = ("trend", "momentum", "volume_coord", "overheat")
    scores = {}
    for key in needed:
        comp = components[key]
        if comp["score"] is None:
            return {
                "value": None,
                "status": "missing",
                "comparable": False,
                "formula": "0.30*trend + 0.25*momentum + 0.20*volume_coord + 0.25*(100-overheat)",
                "note": "存在缺失分项，不生成总分，避免伪完整。",
            }
        scores[key] = comp["score"]
    partial = any(components[k]["status"] != "ok" for k in needed)
    value = round(
        0.30 * scores["trend"]
        + 0.25 * scores["momentum"]
        + 0.20 * scores["volume_coord"]
        + 0.25 * (100.0 - scores["overheat"]),
        1,
    )
    return {
        "value": value,
        "status": "partial" if partial else "ok",
        "comparable": not partial,
        "formula": "0.30*trend + 0.25*momentum + 0.20*volume_coord + 0.25*(100-overheat)",
        "weights": {"trend": 0.30, "momentum": 0.25, "volume_coord": 0.20, "risk_inverse": 0.25},
        "note": (
            "启发式加权，阈值主观，不是统计优化或上涨概率。"
            "trend 与 momentum 共享 change20/MACD，存在重复计分，比较时优先看分项。"
            "overheat 以反向计入，过热高会拉低总分。"
        ),
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def evaluate(technical: dict, context: Optional[dict] = None) -> dict:
    """把 analysis.technical() 的结果变成可解释分项画像。

    参数:
      technical: analysis.py::technical(rows) 的返回值（只读使用）
      context: 可选元数据，如 {"window": 250, "source": "synthetic"}，原样放入 meta

    返回: 版本化 dict，见 contracts/assessment.schema.json
    """
    if not isinstance(technical, dict):
        raise TypeError("technical must be a dict")
    ctx = dict(context or {})
    t = technical
    sample = t.get("sample")
    try:
        sample_n = int(sample) if sample is not None else 0
    except (TypeError, ValueError):
        sample_n = 0

    components = {
        "trend": _eval_trend(t),
        "momentum": _eval_momentum(t),
        "volume_coord": _eval_volume(t, ctx),
        "overheat": _eval_overheat(t, ctx),
    }
    total = _total(components)

    missing_reasons = []
    for name, comp in components.items():
        for item in comp["missing"]:
            missing_reasons.append(f"{name}:{item}")
        if comp["status"] == "insufficient":
            missing_reasons.append(f"{name}:insufficient")

    # 解释段落：分项一句话 + 不承诺
    explanations = [
        components["trend"]["explanation"],
        components["momentum"]["explanation"],
        components["volume_coord"]["explanation"],
        components["overheat"]["explanation"],
        "分数只反映固定规则下的技术画像，不是买入建议、上涨概率或收益承诺。",
    ]

    warnings = []
    if sample_n < 21:
        warnings.append("样本不足 21 个连续有效收盘价，change20/MA20 不可用。")
    if sample_n < 60:
        warnings.append("样本不足 60，MACD 未计算或初始化窗口偏短，与长窗口结果不完全可比。")
    if any(components[k]["status"] != "ok" for k in components):
        warnings.append("存在缺失/部分分项，总分（若有）与其他股票比较时须核对 coverage。")
    # 重复计分提示
    warnings.append("trend 与 momentum 共用 change20，trend 与 overheat 共用 bias20，已降权但未完全消除重复计分。")

    return {
        "rule_version": RULE_VERSION,
        "asof": t.get("asof"),
        "sample": sample_n,
        "components": components,
        "total": total,
        "coverage": {
            "components_scored": sum(1 for c in components.values() if c["score"] is not None),
            "components_total": 4,
            "mean_rule_coverage": round(
                sum(c["coverage"] for c in components.values()) / 4.0, 3),
        },
        "missing_reasons": missing_reasons,
        "explanations": explanations,
        "warnings": warnings,
        "method": (
            "基于 analysis.technical() 已计算的 MA5/10/20/60、change20、bias20、"
            "volume_ratio5、rsi14、MACD12/26/9 与 trend 标签。"
            "不重新计算指标，不引入新闻情绪或财务值。"
        ),
        "meta": {
            "generated_by": "tech_score.py",
            "context": ctx,
            "disclaimer": "技术一致性≠策略有效性。分数高不代表越适合买入。",
        },
    }


__all__ = ["evaluate", "RULE_VERSION"]
