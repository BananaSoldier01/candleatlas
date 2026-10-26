"""Single-process technical batches with persisted progress and explicit retries.

约束（对齐正式 Analysis.start 的单任务锁思想）:
  - 同时最多一个 running 批次/任务；不绕过锁
  - 批次成员在提交时冻结
  - 同指纹复用已保存报告，除非显式 reanalyze；不承诺上游费用
  - 重启不自动恢复可能产生费用的请求
  - 取消只阻止未开始项
  - 部分成功可见；重试仅针对指定失败项
"""
from __future__ import annotations

import datetime as dt
import threading
import uuid
from typing import Callable, Optional

BATCH_VERSION = "guanshi-batch-5"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


class BatchError(Exception):
    pass


class RunGate:
    """进程内互斥运行槽。多个 BatchRunner 必须共享同一 gate，才不会并行跑批。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._holder: Optional[str] = None

    def try_acquire(self, token: str) -> bool:
        with self._lock:
            if self._holder is not None:
                return False
            self._holder = token
            return True

    def release(self, token: str) -> None:
        with self._lock:
            if self._holder == token:
                self._holder = None

    @property
    def holder(self) -> Optional[str]:
        return self._holder


# 默认进程级共享槽：即使新建多个 BatchRunner 也互斥
DEFAULT_RUN_GATE = RunGate()


class SqliteStore:
    """SQLite 批次、成员及兼容指纹存储。"""

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fingerprints("
                "fp TEXT PRIMARY KEY, report_id TEXT, created TEXT, report_status TEXT)")
            columns = {r[1] for r in db.execute("PRAGMA table_info(fingerprints)")}
            if 'report_status' not in columns:
                db.execute("ALTER TABLE fingerprints ADD COLUMN report_status TEXT")
            db.commit()
            db.execute(
                "CREATE TABLE IF NOT EXISTS batches("
                "batch_id TEXT PRIMARY KEY, payload TEXT, status TEXT, updated TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS batch_items("
                "batch_id TEXT, idx INTEGER, payload TEXT, "
                "PRIMARY KEY(batch_id, idx))")

    def connect(self):
        import sqlite3
        return sqlite3.connect(self.path, timeout=10)

    def _db(self):
        import contextlib
        db = self.connect()
        return contextlib.closing(db)

    def get_fp(self, fp: str):
        """返回 {"report_id","report_status"} 或 None。"""
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT report_id, report_status FROM fingerprints WHERE fp=?",
                (fp,)).fetchone()
        if not row:
            return None
        return {"report_id": row[0], "report_status": row[1] or "unknown"}

    def set_fp(self, fp: str, report_id: str, report_status: str = "complete") -> None:
        import datetime as dt
        with self._lock, self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO fingerprints(fp, report_id, report_status, created) VALUES (?,?,?,?)",
                (fp, report_id, report_status,
                 dt.datetime.now().astimezone().isoformat(timespec="seconds")))
            db.commit()

    def save_batch(self, batch_id: str, payload: dict, status: str) -> None:
        import json as _json
        with self._lock, self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO batches(batch_id, payload, status, updated) VALUES (?,?,?,?)",
                (batch_id, _json.dumps(payload, ensure_ascii=False), status, _now()))
            db.commit()

    def save_items(self, batch_id: str, items: list[dict]) -> None:
        import json as _json
        with self._lock, self._db() as db:
            for i, item in enumerate(items):
                db.execute(
                    "INSERT OR REPLACE INTO batch_items(batch_id, idx, payload) VALUES (?,?,?)",
                    (batch_id, i, _json.dumps(item, ensure_ascii=False)))
            db.commit()

    def load_batch(self, batch_id: str):
        import json as _json
        with self._lock, self._db() as db:
            row = db.execute(
                "SELECT payload, status FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if not row:
                return None
            items = db.execute(
                "SELECT payload FROM batch_items WHERE batch_id=? ORDER BY idx",
                (batch_id,)).fetchall()
        payload = _json.loads(row[0])
        payload["status"] = row[1]
        return {"batch": payload,
                "items": [_json.loads(i[0]) for i in items]}

    def mark_running_interrupted(self) -> list[str]:
        """启动时：running/queued → interrupted，不自动恢复。"""
        interrupted = []
        import json as _json
        with self._lock, self._db() as db:
            rows = db.execute(
                "SELECT batch_id, payload, status FROM batches").fetchall()
            for bid, payload, status in rows:
                if status in ("running", "queued"):
                    data = _json.loads(payload)
                    data["status"] = "interrupted"
                    data["note"] = "服务重启，未自动恢复；请人工决定是否重新分析。"
                    db.execute(
                        "UPDATE batches SET status='interrupted', payload=?, updated=? WHERE batch_id=?",
                        (_json.dumps(data, ensure_ascii=False), _now(), bid))
                    interrupted.append(bid)
            db.commit()
        return interrupted

    def list_ids(self) -> list[str]:
        with self._lock, self._db() as db:
            return [r[0] for r in db.execute(
                "SELECT batch_id FROM batches ORDER BY updated DESC, rowid DESC")]


class BatchRunner:
    """串行批次执行器。task_fn 由调用方注入（测试用 fake）。"""

    def __init__(
        self,
        task_fn: Callable[[dict], dict],
        lock: Optional[threading.Lock] = None,
        gate: Optional[RunGate] = None,
        fingerprint_store: Optional[dict] = None,
        store: Optional["SqliteStore"] = None,
        manage_fingerprints: bool = True,
    ):
        """task_fn(member) -> {'report_id': str|None, 'ok': bool, 'error': str|None, 'charged': bool}

        gate: 共享运行槽，默认 DEFAULT_RUN_GATE（跨实例互斥）
        fingerprint_store: 可注入共享字典；生产桥接使用自己的两阶段指纹表。
        """
        self.task_fn = task_fn
        self.lock = lock or threading.Lock()
        self.gate = gate if gate is not None else DEFAULT_RUN_GATE
        self.store = store  # SqliteStore or None
        # The production AnalysisBridge owns its two-phase fingerprint records.
        self.manage_fingerprints = manage_fingerprints
        self.batches: dict[str, dict] = {}
        self.items: dict[str, list[dict]] = {}
        self._running_batch: Optional[str] = None
        self._cancelled: set[str] = set()
        # fingerprint_store: 可注入 dict；若给了 store 则用 SQLite 幂等表
        self._fingerprints: dict[str, str] = (
            fingerprint_store if fingerprint_store is not None else {}
        )


    # -- 提交 ---------------------------------------------------------------
    def submit(self, members: list[dict], day: str, mode: str = "technical",
               explicit: bool = False) -> dict:
        """冻结成员并创建批次。mode 初版仅 technical。"""
        if mode != "technical":
            raise BatchError("初版批次仅支持 technical；AI 批量需显式单独开通。")
        if not members:
            raise BatchError("批次成员不能为空。")
        frozen = []
        seen = set()
        for m in members:
            code = m.get("code")
            if not code:
                raise BatchError("成员缺少 code。")
            if code in seen:
                continue
            seen.add(code)
            frozen.append({
                "code": code,
                "name": m.get("name", code),
                "day": day,
                "mode": mode,
                "status": "queued",
                "report_id": None,
                "error": None,
                "started_at": None,
                "finished_at": None,
                "charged": False,
                "explicit_reanalyze": bool(m.get("reanalyze") or explicit),
            })

        batch_id = uuid.uuid4().hex
        now = _now()
        batch = {
            "batch_id": batch_id,
            "day": day,
            "mode": mode,
            "created_at": now,
            "status": "queued",
            "member_count": len(frozen),
            "completed": 0,
            "failed": 0,
            "skipped_duplicate": 0,
            "cancelled_pending": 0,
        }
        self.batches[batch_id] = batch
        self.items[batch_id] = frozen
        self._persist(batch_id)
        return batch

    def _persist(self, batch_id: str) -> None:
        if self.store is None:
            return
        self.store.save_batch(batch_id, self.batches[batch_id], self.batches[batch_id].get("status", "queued"))
        self.store.save_items(batch_id, self.items[batch_id])

    def _fp_get(self, fp: str):
        """返回 {"report_id","report_status"} 或 None。"""
        if self.store is not None:
            raw = self.store.get_fp(fp)
        else:
            raw = self._fingerprints.get(fp)
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        return {"report_id": raw, "report_status": "unknown"}

    def _fp_set(self, fp: str, report_id: str, report_status: str = "complete") -> None:
        rec = {"report_id": report_id, "report_status": report_status}
        if self.store is not None:
            self.store.set_fp(fp, report_id, report_status)
        else:
            self._fingerprints[fp] = rec

    def fingerprints(self, members: list[dict], day: str, mode: str = "technical") -> list[str]:
        return [f"{m['code']}|{day}|{mode}" for m in members]

    # -- 运行 ---------------------------------------------------------------
    def _recount(self, batch_id: str) -> dict:
        """按 items 重算计数与状态，避免重试后仍报 partial/failed。"""
        items = self.items[batch_id]
        batch = self.batches[batch_id]
        batch["completed"] = sum(1 for i in items if i["status"] == "done")
        batch["partial"] = sum(1 for i in items if i["status"] == "partial")
        batch["needs_review"] = sum(1 for i in items if i["status"] == "needs_review")
        batch["failed"] = sum(1 for i in items if i["status"] == "failed")
        batch["skipped_duplicate"] = sum(1 for i in items if i["status"] == "skipped_duplicate")
        # 去重命中但原报告不完整，也计入 partial 语义
        batch["partial"] += sum(
            1 for i in items
            if i["status"] == "skipped_duplicate" and i.get("report_status") == "partial")
        batch["cancelled_pending"] = sum(1 for i in items if i["status"] == "cancelled")
        if batch_id in self._cancelled and any(i["status"] == "cancelled" for i in items):
            batch["status"] = "cancelled"
        elif any(i["status"] in ("running", "queued") for i in items):
            batch["status"] = "running" if any(i["status"] == "running" for i in items) else "queued"
        elif batch["needs_review"]:
            batch["status"] = "needs_review"
        elif batch["partial"]:
            batch["status"] = "partial"
        elif batch["failed"] and batch["completed"]:
            batch["status"] = "partial"
        elif batch["failed"]:
            batch["status"] = "failed"
        else:
            batch["status"] = "done"
        return batch

    def run(self, batch_id: str) -> dict:
        """串行执行。共享 gate：同一时刻全进程只允许一个批次 running。"""
        if batch_id not in self.batches:
            raise BatchError("批次不存在。")
        batch = self.batches[batch_id]
        has_queued = any(i["status"] == "queued" for i in self.items[batch_id])
        if batch.get("status") == "interrupted":
            raise BatchError("批次已中断，不自动续跑；请核对后新建批次。")
        if batch.get("status") in ("done", "failed", "partial", "cancelled", "needs_review") and not has_queued:
            raise BatchError("批次已结束；如需重跑请对失败项执行 retry_failed。")
        token = f"{id(self)}:{batch_id}"
        if not self.gate.try_acquire(token):
            raise BatchError("已有批次或分析任务运行中，等待完成后再提交。")
        self._running_batch = batch_id
        self.batches[batch_id]["status"] = "running"
        self.batches[batch_id]["started_at"] = _now()
        try:
            # 落盘必须在 finally 释放 Gate 保护之内
            self._persist(batch_id)
            for idx, item in enumerate(self.items[batch_id]):
                # 复核：只把 queued 转成 cancelled，不得覆盖 done/failed/skipped
                if batch_id in self._cancelled and item["status"] == "queued":
                    item["status"] = "cancelled"
                    item["error"] = "用户取消，未开始"
                    continue
                if item["status"] != "queued":
                    continue

                fp = f"{item['code']}|{item['day']}|{item['mode']}"
                prior = None if item["explicit_reanalyze"] or not self.manage_fingerprints else self._fp_get(fp)
                if prior is not None:
                    rid = prior.get("report_id") if isinstance(prior, dict) else prior
                    rst = (prior.get("report_status") if isinstance(prior, dict) else "unknown") or "unknown"
                    item["status"] = "skipped_duplicate"
                    item["report_id"] = rid
                    item["report_status"] = rst
                    if rst == "partial":
                        item["error"] = "同指纹已有报告（原报告不完整/partial），未重复请求；缺失原因见原报告"
                    else:
                        item["error"] = "同指纹已有报告（状态 %s），未重复请求（显式重新分析可覆盖）" % rst
                    self.batches[batch_id]["skipped_duplicate"] += 1
                    self._persist(batch_id)
                    continue

                item["status"] = "running"
                item["started_at"] = _now()
                self._persist(batch_id)
                try:
                    result = self.task_fn(item)
                except Exception as exc:  # noqa: BLE001
                    item["status"] = "failed"
                    item["error"] = f"{type(exc).__name__}: {exc}"
                    item["finished_at"] = _now()
                    self.batches[batch_id]["failed"] += 1
                    continue

                item["finished_at"] = _now()
                item["charged"] = bool(result.get("charged"))
                if result.get("report_id") is not None:
                    item["report_id"] = result.get("report_id")
                if result.get("skipped") or result.get("skip_reason") == "fingerprint_done":
                    # 去重命中：保留原报告状态，不得伪装成 complete
                    item["status"] = "skipped_duplicate"
                    item["report_status"] = result.get("report_status") or "unknown"
                    item["error"] = result.get("error") or (
                        "同指纹已有报告（原报告状态 %s）" % item["report_status"])
                    self.batches[batch_id]["skipped_duplicate"] += 1
                elif result.get("needs_review") or result.get("unknown"):
                    item["status"] = "needs_review"
                    item["report_status"] = result.get("report_status") or "unknown"
                    item["error"] = result.get("error") or "执行结果待核对，不自动重跑"
                elif result.get("partial") or result.get("report_status") == "partial":
                    item["status"] = "partial"
                    item["error"] = result.get("error") or "报告不完整"
                    item["report_status"] = "partial"
                elif result.get("ok"):
                    item["status"] = "done"
                    item["error"] = None
                    item["report_status"] = "complete"
                else:
                    item["status"] = "failed"
                    item["error"] = result.get("error") or "未知失败"
                    item["report_status"] = result.get("report_status") or "failed"
                # 既有去重契约：done/partial 写入 BatchRunner 指纹
                if self.manage_fingerprints and item["status"] in ("done", "partial") and item.get("report_id"):
                    self._fp_set(fp, item["report_id"],
                                 report_status=item.get("report_status") or item["status"])
                self._persist(batch_id)

            self.batches[batch_id]["finished_at"] = _now()
            result = self._recount(batch_id)
            self._persist(batch_id)
            return result
        finally:
            self._running_batch = None
            self.gate.release(token)

    def cancel(self, batch_id: str) -> dict:
        """只阻止未开始项；已在跑的单股请求不假装能撤回。"""
        if batch_id not in self.batches:
            raise BatchError("批次不存在。")
        self._cancelled.add(batch_id)
        pending = [i for i in self.items[batch_id] if i["status"] in ("queued",)]
        self._persist(batch_id)
        return {
            "batch_id": batch_id,
            "cancelled_queued": len(pending),
            "note": "仅阻止未开始项；已发出的单股请求不会被撤回；已完成成员状态保留。",
        }

    def retry_failed(self, batch_id: str) -> dict:
        """只把 failed 项重置为 queued，已完成项不覆盖。"""
        if batch_id not in self.batches:
            raise BatchError("批次不存在。")
        reset = 0
        for item in self.items[batch_id]:
            if item["status"] != "failed":
                continue
            # 未知结果/待核对：保留 report_id，不纳入普通重试
            rs = item.get("report_status")
            if rs in ("unknown", "running") or (item.get("report_id") and rs not in ("complete", "partial", "failed")):
                item["status"] = "needs_review"
                item["error"] = (item.get("error") or "") + "；已保留 report_id，请人工核对"
                continue
            item.update(status="queued", error=None, report_id=None,
                        started_at=None, finished_at=None, charged=False)
            reset += 1
        self._recount(batch_id)
        self._persist(batch_id)
        return {"batch_id": batch_id, "reset_failed": reset, "note": "已完成项未被覆盖；计数已重算。"}

    def snapshot(self, batch_id: str) -> dict:
        return {
            "batch": dict(self.batches[batch_id]),
            "items": [dict(i) for i in self.items[batch_id]],
            "version": BATCH_VERSION,
        }


class RestartPolicy:
    """服务重启：不自动恢复付费批次，只保留中断记录。"""

    @staticmethod
    def on_startup(batches: dict, store: Optional[SqliteStore] = None) -> dict:
        if store is not None:
            store.mark_running_interrupted()
        interrupted = []
        for bid, batch in batches.items():
            if batch.get("status") in ("running", "queued"):
                batch["status"] = "interrupted"
                batch["note"] = "服务重启，未自动恢复；请人工决定是否重新分析。"
                interrupted.append(bid)
        return {"interrupted": interrupted, "auto_resumed": []}


__all__ = ["BatchRunner", "BatchError", "RestartPolicy", "RunGate", "DEFAULT_RUN_GATE",
           "SqliteStore", "BATCH_VERSION"]
