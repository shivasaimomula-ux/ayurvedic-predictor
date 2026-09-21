"""In-process async job store for Stage A predict (Task T18 / Finding #20).

Pattern: submit → job_id → poll progress/result. Each stage UI polls its own
jobs — this is not a mega job dashboard.
"""
from __future__ import annotations

import hashlib
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from . import config

ProgressCb = Callable[[str, int, str, Optional[Dict[str, Any]]], None]


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: str  # queued | running | succeeded | failed | timed_out
    created_at: float
    updated_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress_stage: str = "queued"
    progress_percent: int = 0
    progress_message: str = "Queued"
    progress_detail: Dict[str, Any] = field(default_factory=dict)
    request: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    idempotency_key: Optional[str] = None
    timeout_s: float = 0.0


class JobStore:
    """Thread-safe in-memory jobs with bounded concurrency and TTL prune."""

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        default_timeout_s: float | None = None,
        retention_s: float | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, JobRecord] = {}
        self._by_idem: Dict[str, str] = {}
        self.max_workers = int(
            max_workers
            if max_workers is not None
            else getattr(config, "PREDICT_MAX_CONCURRENT_JOBS", 2)
        )
        self.default_timeout_s = float(
            default_timeout_s
            if default_timeout_s is not None
            else getattr(config, "PREDICT_JOB_TIMEOUT_S", 540)
        )
        self.retention_s = float(
            retention_s
            if retention_s is not None
            else getattr(config, "PREDICT_JOB_RETENTION_S", 3600)
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self.max_workers),
            thread_name_prefix="a-predict-job",
        )

    def submit_predict(
        self,
        *,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        timeout_s: Optional[float] = None,
        runner: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> JobRecord:
        """Enqueue a predict job. Same Idempotency-Key returns the existing job."""
        from . import pipeline as _pipeline

        run_fn = runner or _pipeline.predict
        key = (idempotency_key or "").strip() or None
        if key:
            # Fingerprint request so a reused key with different body is rejected.
            body_fp = hashlib.sha256(
                f"{query}\n{context!r}".encode("utf-8")
            ).hexdigest()[:16]
            composite = f"{key}:{body_fp}"
        else:
            composite = None

        with self._lock:
            self._prune_locked()
            if composite and composite in self._by_idem:
                existing = self._jobs.get(self._by_idem[composite])
                if existing and existing.status in (
                    "queued",
                    "running",
                    "succeeded",
                ):
                    return existing
                # Failed/timed_out: allow retry under same key.
                self._by_idem.pop(composite, None)

            job_id = str(uuid.uuid4())
            now = time.time()
            rec = JobRecord(
                job_id=job_id,
                kind="predict",
                status="queued",
                created_at=now,
                updated_at=now,
                request={"query": query, "context": context},
                idempotency_key=key,
                timeout_s=float(timeout_s if timeout_s is not None else self.default_timeout_s),
            )
            self._jobs[job_id] = rec
            if composite:
                self._by_idem[composite] = job_id

        self._executor.submit(self._run_predict, job_id, run_fn, query, context)
        return rec

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            self._prune_locked()
            return self._jobs.get(job_id)

    def public_view(self, rec: JobRecord) -> Dict[str, Any]:
        view: Dict[str, Any] = {
            "job_id": rec.job_id,
            "kind": rec.kind,
            "status": rec.status,
            "created_at": _iso(rec.created_at),
            "updated_at": _iso(rec.updated_at),
            "started_at": _iso(rec.started_at) if rec.started_at else None,
            "finished_at": _iso(rec.finished_at) if rec.finished_at else None,
            "timeout_s": rec.timeout_s,
            "progress": {
                "stage": rec.progress_stage,
                "percent": rec.progress_percent,
                "message": rec.progress_message,
                "detail": dict(rec.progress_detail),
            },
            "poll_url": f"/jobs/{rec.job_id}",
            "result_url": f"/jobs/{rec.job_id}/result",
        }
        if rec.status == "succeeded" and rec.result is not None:
            view["result"] = rec.result
        if rec.status in ("failed", "timed_out") and rec.error:
            view["error"] = rec.error
        return view

    def _set_progress(
        self,
        job_id: str,
        stage: str,
        percent: int,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec or rec.status not in ("queued", "running"):
                return
            rec.progress_stage = stage
            rec.progress_percent = max(0, min(100, int(percent)))
            rec.progress_message = message
            if detail is not None:
                rec.progress_detail = dict(detail)
            rec.updated_at = time.time()

    def _run_predict(
        self,
        job_id: str,
        run_fn: Callable[..., Dict[str, Any]],
        query: str,
        context: Optional[Dict[str, Any]],
    ) -> None:
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec:
                return
            rec.status = "running"
            rec.started_at = time.time()
            rec.updated_at = rec.started_at
            timeout_s = rec.timeout_s

        def on_progress(
            stage: str,
            percent: int,
            message: str,
            detail: Optional[Dict[str, Any]] = None,
        ) -> None:
            self._set_progress(job_id, stage, percent, message, detail)

        deadline = time.time() + timeout_s
        try:
            # Soft wall-clock: check via progress wrapper; hard stop after join wait.
            result_box: Dict[str, Any] = {}
            error_box: Dict[str, Any] = {}

            def _target() -> None:
                try:
                    kwargs: Dict[str, Any] = {"on_progress": on_progress}
                    try:
                        result_box["value"] = run_fn(query, context, **kwargs)
                    except TypeError:
                        # Sync runners without progress hook still work.
                        result_box["value"] = run_fn(query, context)
                except Exception as exc:  # noqa: BLE001
                    error_box["exc"] = exc
                    error_box["tb"] = traceback.format_exc()

            worker = threading.Thread(
                target=_target, name=f"a-predict-{job_id[:8]}", daemon=True
            )
            worker.start()
            remaining = max(0.1, deadline - time.time())
            worker.join(timeout=remaining)
            if worker.is_alive():
                self._finish(
                    job_id,
                    status="timed_out",
                    error=f"Predict job exceeded wall-clock budget ({timeout_s:.0f}s)",
                    progress=("timed_out", 100, "Timed out"),
                )
                return
            if "exc" in error_box:
                self._finish(
                    job_id,
                    status="failed",
                    error=str(error_box["exc"]),
                    progress=("failed", 100, "Failed"),
                )
                return
            self._finish(
                job_id,
                status="succeeded",
                result=result_box.get("value"),
                progress=("done", 100, "Complete"),
            )
        except Exception as exc:  # noqa: BLE001
            self._finish(
                job_id,
                status="failed",
                error=str(exc),
                progress=("failed", 100, "Failed"),
            )

    def _finish(
        self,
        job_id: str,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: tuple[str, int, str] = ("done", 100, "Complete"),
    ) -> None:
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec:
                return
            now = time.time()
            rec.status = status
            rec.result = result
            rec.error = error
            rec.finished_at = now
            rec.updated_at = now
            rec.progress_stage, rec.progress_percent, rec.progress_message = progress

    def _prune_locked(self) -> None:
        cutoff = time.time() - self.retention_s
        dead = [
            jid
            for jid, rec in self._jobs.items()
            if rec.finished_at and rec.finished_at < cutoff
        ]
        for jid in dead:
            rec = self._jobs.pop(jid, None)
            if rec and rec.idempotency_key:
                # Drop idem map entries that pointed here.
                drop = [k for k, v in self._by_idem.items() if v == jid]
                for k in drop:
                    self._by_idem.pop(k, None)


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


# Process-wide store (one per uvicorn worker).
STORE = JobStore()
