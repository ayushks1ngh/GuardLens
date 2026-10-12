"""Tiny in-process scheduler for periodic and daily jobs (retention, nightly reports, agents).

Jobs run on a single background thread, one at a time, each isolated so a failing job is logged
and retried on its next slot. Intervals are wall-clock seconds; ``daily_at`` uses local time.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger("guardlens.scheduler")


@dataclass
class Job:
    name: str
    fn: Callable[[], object]
    every: Optional[float] = None       # seconds between runs
    daily_at: Optional[str] = None      # "HH:MM" local time
    last_run: float = 0.0
    last_day: str = ""
    last_status: str = "never run"
    runs: int = 0
    extra: dict = field(default_factory=dict)

    def due(self, now: float, today: str, hhmm: str) -> bool:
        if self.every is not None:
            return now - self.last_run >= self.every
        if self.daily_at:
            return hhmm >= self.daily_at and self.last_day != today
        return False


class Scheduler:
    def __init__(self, tick_seconds: float = 20.0) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tick = tick_seconds

    def add_job(self, name: str, fn: Callable[[], object], *, every: Optional[float] = None,
                daily_at: Optional[str] = None) -> None:
        if (every is None) == (daily_at is None):
            raise ValueError("give exactly one of every= or daily_at=")
        now = time.time()
        job = Job(name, fn, every=every, daily_at=daily_at)
        if every is not None:
            job.last_run = now  # first run after one interval, not at startup
        elif daily_at and datetime.now().strftime("%H:%M") >= daily_at:
            job.last_day = datetime.now().strftime("%Y-%m-%d")  # don't fire a missed slot on boot
        with self._lock:
            self._jobs[name] = job

    def remove_job(self, name: str) -> None:
        with self._lock:
            self._jobs.pop(name, None)

    def remove_prefix(self, prefix: str) -> None:
        with self._lock:
            for name in [n for n in self._jobs if n.startswith(prefix)]:
                del self._jobs[name]

    def jobs(self) -> list[dict]:
        with self._lock:
            return [{"name": j.name, "every": j.every, "daily_at": j.daily_at,
                     "last_status": j.last_status, "runs": j.runs} for j in self._jobs.values()]

    def run_job(self, job: Job) -> None:
        started = time.time()
        try:
            job.fn()
            job.last_status = "ok"
        except Exception as exc:
            job.last_status = f"error: {type(exc).__name__}"
            logger.exception("scheduled job %s failed", job.name)
        job.last_run = started
        job.last_day = datetime.now().strftime("%Y-%m-%d")
        job.runs += 1

    def run_due(self) -> int:
        """Run every job that is due now; returns how many ran (also used by tests)."""
        now, today, hhmm = time.time(), datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M")
        with self._lock:
            due = [j for j in self._jobs.values() if j.due(now, today, hhmm)]
        for job in due:
            self.run_job(job)
        return len(due)

    def run_now(self, name: str) -> bool:
        with self._lock:
            job = self._jobs.get(name)
        if job is None:
            return False
        self.run_job(job)
        return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._tick):
            try:
                self.run_due()
            except Exception:
                logger.exception("scheduler tick failed")


scheduler = Scheduler()
