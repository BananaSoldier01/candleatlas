"""Technical-only Analysis adapter with durable two-phase fingerprints.

指纹两阶段（针对「任务已成功但指纹未写入」）:
  1. 调用前写入 in_flight
  2. 成功后更新 done + report_id
  3. 失败则删除 in_flight（允许重试）
  4. 启动时扫到 in_flight 且无对应 report → needs_review，禁止自动重跑
  5. 任务成功后进程崩溃、指纹仍为 in_flight → 重启后 needs_review（人工核对）
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from batch import RunGate

def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class FingerprintStore:
    """重启后可读取的指纹表；实例锁只保护进程内，不提供多进程互斥。"""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        db = self._conn()
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fp2("
                "fp TEXT PRIMARY KEY, report_id TEXT, status TEXT, "
                "created TEXT, updated TEXT, note TEXT)")
            db.commit()
        finally:
            db.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _execute(self, fn):
        with self._lock:
            db = self._conn()
            try:
                return fn(db)
            finally:
                db.close()

    def begin(self, fp: str, allow_redo: bool = False) -> str:
        """调用前标记 in_flight。

        - done 且非 allow_redo → 'done'（跳过）
        - needs_review → 'needs_review'（禁止自动重跑；reanalyze 也不得绕过）
        - 残留 in_flight → 'needs_review'
        - allow_redo 且已 done → 写入**新的** in_flight（旧 report_id 放入 note）
        """

        def work(db):
            row = db.execute("SELECT status, report_id FROM fp2 WHERE fp=?", (fp,)).fetchone()
            if row and row[0] == "needs_review":
                return "needs_review"
            if row and row[0] == "in_flight":
                db.execute(
                    "UPDATE fp2 SET status='needs_review', note=?, updated=? WHERE fp=?",
                    ("发现残留 in_flight，上次是否成功未知，需人工核对", _now(), fp))
                db.commit()
                return "needs_review"
            if row and row[0] == "done":
                if not allow_redo:
                    return "done"
                prev = row[1]
                db.execute(
                    "INSERT OR REPLACE INTO fp2(fp, report_id, status, created, updated, note) "
                    "VALUES (?,?,?,?,?,?)",
                    (fp, None, "in_flight", _now(), _now(),
                     f"reanalyze 新执行开始；旧 report_id={prev}"))
                db.commit()
                return "in_flight"
            db.execute(
                "INSERT OR REPLACE INTO fp2(fp, report_id, status, created, updated, note) "
                "VALUES (?,?,?,?,?,?)",
                (fp, None, "in_flight", _now(), _now(), None))
            db.commit()
            return "in_flight"
        return self._execute(work)

    def commit(self, fp: str, report_id: str, report_status: str = "complete") -> None:
        def work(db):
            db.execute(
                "INSERT OR REPLACE INTO fp2(fp, report_id, status, created, updated, note) "
                "VALUES (?,?,?,?,?,?)",
                (fp, report_id, "done", _now(), _now(), f"report_status={report_status}"))
            db.commit()
        self._execute(work)

    def rollback(self, fp: str) -> None:
        """任务失败：允许重试，清除 in_flight。"""
        def work(db):
            db.execute("DELETE FROM fp2 WHERE fp=? AND status='in_flight'", (fp,))
            db.commit()
        self._execute(work)

    def mark_needs_review(self, fp: str, note: str, report_id: str | None = None) -> None:
        """保留已知 report_id（结构化字段，不只依赖 note 文本）。"""
        def work(db):
            prev = db.execute("SELECT report_id FROM fp2 WHERE fp=?", (fp,)).fetchone()
            rid = report_id if report_id is not None else (prev[0] if prev else None)
            db.execute(
                "INSERT OR REPLACE INTO fp2(fp, report_id, status, created, updated, note) "
                "VALUES (?,?,?,?,?,?)",
                (fp, rid, "needs_review", _now(), _now(), note))
            db.commit()
        self._execute(work)

    def get(self, fp: str) -> Optional[dict]:
        def work(db):
            return db.execute(
                "SELECT fp, report_id, status, created, updated, note FROM fp2 WHERE fp=?",
                (fp,)).fetchone()
        row = self._execute(work)
        if not row:
            return None
        note = row[5] or ""
        rs = "unknown"
        for part in note.split(";"):
            part = part.strip()
            if part.startswith("report_status="):
                rs = part.split("=", 1)[1]
        return {"fp": row[0], "report_id": row[1], "status": row[2],
                "created": row[3], "updated": row[4], "note": row[5],
                "report_status": rs}

    def all(self) -> list[dict]:
        def work(db):
            return db.execute(
                "SELECT fp, report_id, status, created, updated, note FROM fp2").fetchall()
        rows = self._execute(work)
        return [{"fp": r[0], "report_id": r[1], "status": r[2],
                 "created": r[3], "updated": r[4], "note": r[5]} for r in rows]

    def reconcile_on_startup(self, analysis=None) -> dict:
        """重启核对：in_flight → needs_review；已 done 但报告缺失 → needs_review。"""
        upgraded = []
        for rec in self.all():
            if rec["status"] == "in_flight":
                self.mark_needs_review(rec["fp"], "进程退出时指纹为 in_flight，需人工核对是否已生成报告")
                upgraded.append(rec["fp"])
            elif rec["status"] == "done" and analysis is not None and rec.get("report_id"):
                try:
                    analysis.get(rec["report_id"])
                except Exception:
                    self.mark_needs_review(rec["fp"], "指纹 done 但报告不存在，需人工核对")
                    upgraded.append(rec["fp"])
        return {"upgraded_to_needs_review": upgraded, "auto_resumed": []}


class AnalysisBridge:
    """把 BatchRunner 任务映射到正式 Analysis.start + 轮询完成。

    - 与手动 start 共用 Analysis.lock（start 内已有 running 检查）
    - 技术分析 only（use_ai=False），不调用模型
    - 两阶段指纹
    """

    def __init__(self, analysis, fp: FingerprintStore, gate: RunGate,
                 poll_s: float = 0.02, timeout_s: float = 8.0):
        self.analysis = analysis
        self.fp = fp
        self.gate = gate
        self.poll_s = poll_s
        self.timeout_s = timeout_s
        self.call_log: list[dict] = []

    def make_task(self) -> Callable[[dict], dict]:
        def task(item: dict) -> dict:
            code, day = item["code"], item["day"]
            key = f"{code}|{day}|{item.get('mode', 'technical')}"
            self.call_log.append({"fp": key, "code": code, "day": day, "at": _now(), "phase": "begin"})
            previous = self.fp.get(key)
            state = self.fp.begin(key, allow_redo=bool(item.get("explicit_reanalyze")))
            if state == "done":
                rec = self.fp.get(key) or {}
                return {"ok": True, "report_id": rec.get("report_id"),
                        "charged": False, "skipped": True, "skip_reason": "fingerprint_done",
                        "report_status": rec.get("report_status") or "unknown",
                        "error": "同指纹已有报告（原报告状态 %s）" % (rec.get("report_status") or "unknown")}
            if state == "needs_review":
                rec = self.fp.get(key) or {}
                return {"ok": False, "report_id": rec.get("report_id"), "charged": False,
                        "needs_review": True, "report_status": "unknown",
                        "error": "指纹需人工核对（上次执行结果未知），未自动重跑"}
            # state == in_flight
            # 注意：BatchRunner.run 已持有 RunGate；此处不再重复获取。
            # 与「手动 Analysis.start」的互斥由正式 Analysis 的 running 单任务检查保证。
            try:
                body = {"code": code, "date": day, "name": item.get("name", code), "ai": False}
                try:
                    started = self.analysis.start(body)
                except Exception as start_exc:
                    # 手动任务占用或参数问题：允许重试，不升 needs_review
                    if previous and previous['status'] == 'done':
                        self.fp.commit(key, previous['report_id'], previous.get('report_status', 'unknown'))
                    else:
                        self.fp.rollback(key)
                    self.call_log.append({"fp": key, "phase": "start_rejected", "error": str(start_exc)})
                    return {"ok": False, "report_id": None, "charged": False,
                            "error": f"start_rejected: {start_exc}"}
                report_id = started["id"]
                self.call_log.append({"fp": key, "report_id": report_id, "phase": "started"})
                # 轮询至 complete/partial/failed
                deadline = time.time() + self.timeout_s
                status = "running"
                while time.time() < deadline:
                    row = self.analysis.get(report_id)
                    status = row.get("status")
                    if status in ("complete", "partial", "failed", "interrupted"):
                        break
                    time.sleep(self.poll_s)
                if status == "complete":
                    technical = (row.get('report') or {}).get('technical') or {}
                    if not technical.get('sample') or technical.get('close') is None:
                        # Analysis can save complete materials even when its market
                        # request failed; a technical batch must retain a retryable failure.
                        self.fp.rollback(key)
                        return {'ok': False, 'report_id': report_id, 'charged': False,
                                'report_status': 'complete',
                                'error': '未取得有效日 K 技术指标，已有材料已保存；可仅重试失败项。'}
                    self.fp.commit(key, report_id, report_status="complete")
                    self.call_log.append({"fp": key, "report_id": report_id, "phase": "committed"})
                    return {"ok": True, "report_id": report_id, "charged": False}
                if status == "partial":
                    self.fp.commit(key, report_id, report_status="partial")
                    self.call_log.append({"fp": key, "report_id": report_id, "phase": "partial"})
                    return {"ok": False, "report_id": report_id, "charged": False,
                            "error": "partial: 报告不完整，已保留 report_id，请人工查看缺失项",
                            "report_status": "partial", "partial": True}
                if status in ("failed", "interrupted"):
                    # 明确失败：可重试，但记录 report_id（若有）
                    self.fp.rollback(key)
                    return {"ok": False, "report_id": report_id, "charged": False,
                            "error": row.get("error") or f"status={status}", "report_status": status}
                # 超时 / running：任务已发出，禁止 rollback 当作未执行
                self.fp.mark_needs_review(
                    key,
                    f"超时且状态={status}；报告 {report_id} 可能仍在执行或已完成，需人工核对",
                    report_id=report_id)
                self.call_log.append({"fp": key, "report_id": report_id,
                                      "phase": "timeout_keep", "status": status})
                return {"ok": False, "report_id": report_id, "charged": False,
                        "error": f"timeout/unknown status={status}; report_id={report_id}；已保留关联，禁止自动重跑",
                        "report_status": status, "unknown": True}
            except Exception as exc:  # noqa: BLE001
                # 若 start 已发出（locals 有 report_id），保留关联，禁止自动重跑
                rid = locals().get("report_id")
                self.fp.mark_needs_review(key, f"执行异常：{type(exc).__name__}: {exc}",
                                           report_id=rid)
                self.call_log.append({"fp": key, "phase": "error", "error": str(exc),
                                      "report_id": rid})
                return {"ok": False, "report_id": rid, "charged": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "report_status": "unknown"}
        return task

