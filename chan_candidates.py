"""Candidate observer for the pinned engine; candidates remain unconfirmed."""
import hashlib
import json
import math
from typing import Optional
RULE_VERSION="guanshi-bsp-events-2"
ENGINE_REVISION="429d6ed3043e27c93a003ba2b10e70a05575e1f5"
CANDIDATE_TYPES = ("1", "1p", "2", "2s", "3a", "3b")

def sample_hash(rows: list[dict]) -> str:
    blob = json.dumps(
        [{k: r[k] for k in ("date", "open_price", "high_price", "low_price", "close_price", "volume") if k in r}
         for r in rows], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def _price(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else round(f, 6)

def _point_dict(bsp, source: str, is_target: bool, last_sure_pos) -> dict:
    end = bsp.bi.get_end_klu()
    begin = bsp.bi.get_begin_klu()
    # 拐点价：买点取笔末端低点，卖点取高点；字段不存在时退回 close
    pivot_price = _price(getattr(end, "low", None) if bsp.is_buy else getattr(end, "high", None))
    if pivot_price is None:
        pivot_price = _price(getattr(end, "close", None))
    types = [t.value if hasattr(t, "value") else str(t) for t in bsp.type]
    end_idx = getattr(end, "idx", None)
    stability = ("locked_by_last_sure_pos"
                 if end_idx is not None and last_sure_pos is not None and end_idx <= last_sure_pos
                 else "rewrite_zone")
    return {
        "source": source,
        "is_target": is_target,
        "is_buy": bool(bsp.is_buy),
        "types": types,
        "pivot_date": end.time.toDateStr("-"),
        "pivot_price": pivot_price,
        "begin_date": begin.time.toDateStr("-"),
        "begin_price": _price(getattr(begin, "close", None)),
        "bi_idx": getattr(bsp.bi, "idx", None),
        "end_klu_idx": end_idx,
        "begin_klu_idx": getattr(begin, "idx", None),
        "is_segbsp": bool(getattr(bsp, "is_segbsp", False)),
        "relate_bsp1_klu": (
            getattr(getattr(bsp, "relate_bsp1", None), "klu", None).idx
            if getattr(bsp, "relate_bsp1", None) is not None else None),
        "bi_sure": bool(getattr(bsp.bi, "is_sure", False)),
        "last_sure_pos": last_sure_pos,
        "stability": stability,
    }

def _visible_points(core) -> list[dict]:
    """合并目标点（bsp_store）与非目标 T1/T1P（仅 bsp1_list）。"""
    out = []
    seen_ids = set()
    for source, lst in (("bi_bsp", core.bs_point_lst), ("seg_bsp", core.seg_bs_point_lst)):
        last_sure_pos = getattr(lst, "last_sure_pos", -1)
        for bsp in lst.bsp_iter():
            seen_ids.add(id(bsp))
            out.append(_point_dict(bsp, source=source, is_target=True, last_sure_pos=last_sure_pos))
        for bsp in getattr(lst, "bsp1_list", []):
            if id(bsp) in seen_ids:
                continue
            seen_ids.add(id(bsp))
            out.append(_point_dict(bsp, source=source + "_1only", is_target=False, last_sure_pos=last_sure_pos))
    return out

def identity_key(item: dict) -> tuple:
    """稳定身份：来源层(笔/线段) + 方向 + 拐点日 + 拐点价。

    复核修订：同一拐点的笔级与线段级候选是不同对象，不得合并成一条并触发假 moved。
    """
    src = item.get("source") or "bi_bsp"
    layer = "seg" if str(src).startswith("seg") else "bi"
    return (layer, item["is_buy"], item["pivot_date"], item["pivot_price"])

class EventTracker:
    def __init__(self, sample_id: str, window_start: str):
        self.sample_id = sample_id
        self.window_start = window_start
        self.live: dict[tuple, dict] = {}
        self.events: list[dict] = []
        self._seq = 0

    def _emit(self, kind: str, key: tuple, snapshot: dict, observed_at: str, **extra):
        self._seq += 1
        event = {
            "seq": self._seq,
            "event": kind,
            "identity": {"layer": key[0], "is_buy": key[1], "pivot_date": key[2], "pivot_price": key[3]},
            "observed_at": observed_at,
            "sample_id": self.sample_id,
            "rule_version": RULE_VERSION,
            "engine_revision": ENGINE_REVISION,
            "window_start": self.window_start,
            "confirmation": "unknown",
            **extra,
            **{k: snapshot.get(k) for k in (
                "source", "is_target", "types", "begin_date", "begin_price", "bi_idx",
                "end_klu_idx", "stability", "bi_sure", "last_sure_pos",
                "is_segbsp", "relate_bsp1_klu",
            ) if k in snapshot},
        }
        self.events.append(event)

    def observe(self, visible: list[dict], observed_at: str):
        current = {}
        for item in visible:
            key = identity_key(item)
            current[key] = item
            prev = self.live.get(key)
            if prev is None:
                self.live[key] = {
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                    "types_seen": set(item["types"]),
                    "item": item,
                }
                self._emit(
                    "appearing", key, item, observed_at,
                    first_seen_at=observed_at, last_seen_at=observed_at,
                    note="首次可见；上游无通用‘信号已确认’字段，confirmation=unknown")
            else:
                prev["last_seen_at"] = observed_at
                new_types = set(item["types"]) - prev["types_seen"]
                if new_types:
                    prev["types_seen"] |= new_types
                    self._emit(
                        "type_extended", key, item, observed_at,
                        first_seen_at=prev["first_seen_at"], last_seen_at=observed_at,
                        added_types=sorted(new_types),
                        note="同一拐点叠加新的买卖点类型（add_another_bsp_prop）")
                if item.get("bi_idx") != prev["item"].get("bi_idx") or item.get("end_klu_idx") != prev["item"].get("end_klu_idx"):
                    self._emit(
                        "moved", key, item, observed_at,
                        first_seen_at=prev["first_seen_at"], last_seen_at=observed_at,
                        previous_bi_idx=prev["item"].get("bi_idx"),
                        previous_end_klu_idx=prev["item"].get("end_klu_idx"),
                        note="身份重建后结构编号变化，不等于信号性质变化")
                if item.get("is_target") != prev["item"].get("is_target"):
                    self._emit(
                        "target_flag_changed", key, item, observed_at,
                        first_seen_at=prev["first_seen_at"], last_seen_at=observed_at,
                        previous_is_target=prev["item"].get("is_target"),
                        note="is_target 来自是否进入 bsp_store 的适配层推断")
                prev["item"] = item

        for key, prev in list(self.live.items()):
            if key not in current:
                item = prev["item"]
                last = prev["last_seen_at"]
                status, reason = self._classify_vanish(item)
                self._emit(
                    "vanished", key, item, observed_at,
                    first_seen_at=prev["first_seen_at"], last_seen_at=last,
                    lifecycle_status=status, vanish_reason=reason,
                    note="本帧不再出现；无证据不写成‘规则失效’")
                del self.live[key]

    @staticmethod
    def _classify_vanish(item: dict) -> tuple[str, str]:
        if item.get("stability") == "rewrite_zone":
            return "vanished_rewrite_zone", "点落在 last_sure_pos 之后，清理/重算窗口内消失"
        return "vanished_after_lock", "已过 last_sure_pos 仍消失，需核对结构修订或样本变化"

class Collector:
    """Observe the same core used for structures; display only validated types."""
    def __init__(self, rows):
        self.tracker = EventTracker(sample_hash(rows), rows[0]['date'] if rows else '')

    def observe(self, core, day):
        import copy
        points = []
        for point in _visible_points(core):
            types = [value for value in point['types'] if value in CANDIDATE_TYPES]
            if types:
                points.append({**point, 'types': types})
        offset = len(self.tracker.events)
        self.tracker.observe(points, day)
        current = []
        for identity, record in self.tracker.live.items():
            current.append({**record['item'],
                            'identity': {'layer': identity[0], 'is_buy': identity[1],
                                         'pivot_date': identity[2], 'pivot_price': identity[3]},
                            'first_seen_at': record['first_seen_at'],
                            'last_seen_at': record['last_seen_at'], 'confirmation': 'unknown'})
        return {'candidates': copy.deepcopy(current),
                'candidate_events': copy.deepcopy(self.tracker.events[offset:])}
