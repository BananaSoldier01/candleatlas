"""Local lifecycle for single-process, technical-only report batches."""
import datetime as dt
from pathlib import Path
import threading

from analysis_bridge import AnalysisBridge, FingerprintStore
from batch import BatchError, BatchRunner, RunGate, SqliteStore, RestartPolicy, _now


class BatchService:
    def __init__(self, analysis, path, *, timeout_s=120):
        self.analysis = analysis
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = SqliteStore(path)
        self.fingerprints = FingerprintStore(path)
        self.gate = RunGate()
        self.bridge = AnalysisBridge(analysis, self.fingerprints, self.gate,
                                     poll_s=.1, timeout_s=timeout_s)
        # Only the bridge's two-phase ledger decides production deduplication.
        self.runner = BatchRunner(self.bridge.make_task(), gate=self.gate,
                                  store=self.store, manage_fingerprints=False)
        self._lock = threading.RLock()
        self._active = None
        self._thread = None
        RestartPolicy.on_startup({}, store=self.store)
        self.fingerprints.reconcile_on_startup(analysis)
        for identifier in self.store.list_ids():
            self._load(identifier, restarting=True)
        path.chmod(0o600)

    @staticmethod
    def _key(item):
        return f"{item['code']}|{item['day']}|{item['mode']}"

    def _load(self, identifier, restarting=False):
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise BatchError('批次编号无效。')
        if identifier in self.runner.batches:
            return
        saved = self.store.load_batch(identifier)
        if not saved:
            raise BatchError('批次不存在。')
        self.runner.batches[identifier] = saved['batch']
        self.runner.items[identifier] = saved['items']
        changed = False
        if restarting:
            for item in saved['items']:
                if item['status'] == 'running':
                    rec = self.fingerprints.get(self._key(item)) or {}
                    item.update(status='needs_review', report_status='unknown',
                                report_id=item.get('report_id') or rec.get('report_id'),
                                error='服务退出时此项仍在执行，请核对已有报告；未自动重跑。')
                    changed = True
            if changed:
                saved['batch'].update(status='interrupted', note='服务重启，未自动续跑；请先核对已生成报告。')
                self.runner._persist(identifier)

    def _idle(self):
        if self._active:
            raise BatchError('已有批次执行中，请等待完成或取消未开始项。')

    def _start(self, identifier):
        self._active = identifier

        def work():
            try:
                self.runner.run(identifier)
            except Exception:
                self.runner.batches[identifier].update(
                    status='interrupted', error='批次执行中断，请核对已生成报告；未自动重试。')
                try:
                    self.runner._persist(identifier)
                except Exception:
                    pass  # Reconcile the last durable checkpoint on startup.
            finally:
                with self._lock:
                    self._active = None

        self._thread = threading.Thread(target=work, name='technical-batch', daemon=True)
        self._thread.start()

    def submit(self, body):
        if not isinstance(body, dict):
            raise BatchError('批次参数必须为 JSON 对象。')
        if body.get('mode', 'technical') != 'technical' or body.get('ai', False) is not False:
            raise BatchError('批次仅支持技术分析，不支持 AI 批量调用。')
        day = body.get('date')
        try:
            dt.date.fromisoformat(day)
        except (ValueError, TypeError):
            raise BatchError('请选择有效观察日。')
        members = body.get('members')
        if not isinstance(members, list) or not 1 <= len(members) <= 50:
            raise BatchError('每批请选择 1 至 50 只股票。')
        if not isinstance(body.get('reanalyze', False), bool):
            raise BatchError('重新分析选项无效。')
        frozen = []
        for member in members:
            if not isinstance(member, dict):
                raise BatchError('股票成员格式无效。')
            code = member.get('code')
            self.analysis.validate_code(code)
            name = member.get('name', code)
            if not isinstance(name, str) or len(name) > 100:
                raise BatchError('股票名称无效。')
            frozen.append({'code': code, 'name': name})
        with self._lock:
            self._idle()
            if day not in self.analysis.market.calendar():
                raise BatchError('该观察日不在交易日历中。')
            batch = self.runner.submit(frozen, day, explicit=body.get('reanalyze', False))
            self._start(batch['batch_id'])
            return self.snapshot(batch['batch_id'])

    def snapshot(self, identifier):
        with self._lock:
            self._load(identifier)
            result = self.runner.snapshot(identifier)
            result['active'] = self._active == identifier
            for item in result['items']:
                if item['status'] in ('needs_review', 'running'):
                    rec = self.fingerprints.get(self._key(item)) or {}
                    item['report_id'] = item.get('report_id') or rec.get('report_id')
            return result

    def history(self, day=''):
        with self._lock:
            batches = []
            for identifier in self.store.list_ids():
                self._load(identifier)
                batch = dict(self.runner.batches[identifier])
                if not day or batch['day'] == day:
                    batches.append(batch)
                if len(batches) >= 20:
                    break
            return {'items': batches, 'active_batch': self._active}

    def cancel(self, identifier):
        with self._lock:
            self._load(identifier)
            if self._active != identifier:
                raise BatchError('此批次未在运行。')
            self.runner.cancel(identifier)
            return self.snapshot(identifier)

    def retry(self, identifier):
        with self._lock:
            self._idle()
            self._load(identifier)
            if self.runner.batches[identifier]['status'] == 'interrupted':
                raise BatchError('中断批次不续跑；请核对后新建批次。')
            if not any(i['status'] == 'failed' for i in self.runner.items[identifier]):
                return self.snapshot(identifier)
            self.runner.retry_failed(identifier)
            if any(i['status'] == 'queued' for i in self.runner.items[identifier]):
                self._start(identifier)
            return self.snapshot(identifier)

    def review(self, identifier, index):
        """User confirms an existing finished report; never issues a new request."""
        with self._lock:
            self._idle()
            self._load(identifier)
            items = self.runner.items[identifier]
            if type(index) is not int or not 0 <= index < len(items):
                raise BatchError('待核对成员无效。')
            item = items[index]
            if item['status'] != 'needs_review':
                raise BatchError('此成员不需要人工核对。')
            rec = self.fingerprints.get(self._key(item)) or {}
            rid = item.get('report_id') or rec.get('report_id')
            if not rid:
                raise BatchError('没有可关联的报告，请先到个股分析历史核对；此处不会重跑。')
            report = self.analysis.get(rid)
            if report['code'] != item['code'] or report['day'] != item['day']:
                raise BatchError('报告与成员不一致，不能确认。')
            status = report['status']
            if status not in ('complete', 'partial'):
                raise BatchError('报告尚未生成可保留的结果，请稍后核对；不会重跑。')
            self.fingerprints.commit(self._key(item), rid, status)
            item.update(status='done' if status == 'complete' else 'partial',
                        report_status=status, report_id=rid, finished_at=_now(),
                        error=None if status == 'complete' else report.get('error') or '报告不完整，请查看缺失项。')
            was_interrupted = self.runner.batches[identifier]['status'] == 'interrupted'
            self.runner._recount(identifier)
            if was_interrupted and any(i['status'] == 'queued' for i in items):
                self.runner.batches[identifier]['status'] = 'interrupted'
            self.runner._persist(identifier)
            return self.snapshot(identifier)

    def wait(self, timeout=5):
        thread = self._thread
        if thread:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError('批次尚未结束。')
