"""Background scrape job manager — survives frontend disconnect, supports cancel/reconnect."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

MAX_EVENTS = 3500
TERMINAL = frozenset({"complete", "error", "cancelled"})


class ScrapeCancelled(Exception):
    """User requested stop."""


@dataclass
class ScrapeJob:
    id: str
    kind: str
    label: str
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    result: Optional[Dict[str, Any]] = None
    _subscribers: List[asyncio.Queue] = field(default_factory=list)

    def should_cancel(self) -> bool:
        return self.cancel_event.is_set()


class JobManager:
    def __init__(self) -> None:
        self._job: Optional[ScrapeJob] = None
        self._lock = asyncio.Lock()

    def _snapshot(self, job: ScrapeJob) -> Dict[str, Any]:
        last = job.events[-1] if job.events else {}
        snap = {
            "id": job.id,
            "kind": job.kind,
            "label": job.label,
            "status": job.status,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "event_count": len(job.events),
            "step": last.get("step"),
            "total_steps": last.get("total_steps"),
            "message": last.get("message"),
            "detail_index": last.get("detail_index"),
            "detail_total": last.get("detail_total"),
            "place_name": last.get("place_name"),
            "place_kind": last.get("place_kind"),
            "links_found": last.get("links_found"),
            "save_totals": last.get("save_totals"),
        }
        return snap

    def status(self) -> Dict[str, Any]:
        if not self._job:
            return {"status": "idle", "running": False}
        snap = self._snapshot(self._job)
        snap["running"] = self._job.status == "running"
        return snap

    def events_since(self, after: int = 0) -> Dict[str, Any]:
        if not self._job:
            return {**self.status(), "events": [], "total": 0}
        job = self._job
        after = max(0, min(after, len(job.events)))
        return {
            **self._snapshot(job),
            "running": job.status == "running",
            "events": job.events[after:],
            "total": len(job.events),
        }

    def _emit(self, job: ScrapeJob, event: Dict[str, Any]) -> None:
        payload = {**event, "job_id": job.id, "ts": time.time()}
        job.events.append(payload)
        if len(job.events) > MAX_EVENTS:
            job.events = job.events[-MAX_EVENTS:]
        for q in list(job._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def _subscribe(self, job: ScrapeJob) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        job._subscribers.append(q)
        return q

    def _unsubscribe(self, job: ScrapeJob, q: asyncio.Queue) -> None:
        try:
            job._subscribers.remove(q)
        except ValueError:
            pass

    async def _stop_running(self) -> None:
        job = self._job
        if not job or job.status != "running":
            return
        job.cancel_event.set()
        self._emit(job, {"type": "progress", "message": "جاري إيقاف العملية…"})
        if job.task and not job.task.done():
            job.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(job.task), timeout=45)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        if job.status == "running":
            job.status = "cancelled"
            job.finished_at = time.time()
            self._emit(job, {"type": "cancelled", "message": "تم إيقاف العملية"})
            self._emit(job, {"type": "_end"})

    async def stop(self) -> Dict[str, Any]:
        async with self._lock:
            await self._stop_running()
            return self.status()

    async def start(self, kind: str, label: str, runner: Callable[[ScrapeJob], Any]) -> Dict[str, Any]:
        async with self._lock:
            await self._stop_running()
            job = ScrapeJob(id=uuid.uuid4().hex[:12], kind=kind, label=label)
            self._job = job

            async def _wrap() -> None:
                try:
                    await runner(job)
                except ScrapeCancelled:
                    if job.status == "running":
                        job.status = "cancelled"
                        job.finished_at = time.time()
                        self._emit(job, {"type": "cancelled", "message": "تم إيقاف العملية"})
                except asyncio.TimeoutError:
                    job.status = "error"
                    job.finished_at = time.time()
                    self._emit(job, {"type": "error", "message": "انتهت المهلة بعد 5 دقائق"})
                except asyncio.CancelledError:
                    if job.status == "running":
                        job.status = "cancelled"
                        job.finished_at = time.time()
                        self._emit(job, {"type": "cancelled", "message": "تم إيقاف العملية"})
                except Exception as exc:
                    job.status = "error"
                    job.finished_at = time.time()
                    self._emit(job, {"type": "error", "message": str(exc)})
                finally:
                    if job.status == "running":
                        job.status = "error"
                        job.finished_at = time.time()
                        self._emit(job, {"type": "error", "message": "انتهت العملية بشكل غير متوقع"})
                    self._emit(job, {"type": "_end"})

            job.task = asyncio.create_task(_wrap())
            return self._snapshot(job)

    def emit(self, job: ScrapeJob, event: Dict[str, Any]) -> None:
        if job.should_cancel() and event.get("type") not in TERMINAL | {"cancelled", "_end"}:
            raise ScrapeCancelled()
        self._emit(job, event)
        if event.get("type") in TERMINAL:
            job.status = event["type"] if event["type"] != "complete" else "complete"
            job.finished_at = time.time()
            job.result = event

    async def stream(self) -> AsyncIterator[str]:
        import json

        job = self._job
        if not job:
            yield json.dumps({"type": "idle", "message": "لا توجد عملية"}, ensure_ascii=False) + "\n"
            return

        for event in job.events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

        if job.status != "running":
            return

        q = self._subscribe(job)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "heartbeat"}, ensure_ascii=False) + "\n"
                    if job.status != "running":
                        break
                    continue
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event.get("type") == "_end":
                    break
        finally:
            self._unsubscribe(job, q)


job_manager = JobManager()
