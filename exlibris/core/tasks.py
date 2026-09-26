"""Background work inside the container (no cron): covers, series, genres (if AI
is set up) and the nightly backup. One failing job never stops the others."""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable
from exlibris.core import ai, backup, covers, openlibrary

log = logging.getLogger("exlibris.tasks")


@dataclass
class Job:
    name: str
    every: float                 # seconds between runs
    fn: Callable[[], object]
    next_at: float = field(default=0.0)


def default_jobs():
    jobs = [Job("cover files", 1800, covers.download_missing_files),
            Job("covers", 6 * 3600, covers.fill_missing),
            Job("series", 3600, openlibrary.backfill_series),
            Job("years", 3600, openlibrary.backfill_years),
            Job("backup", 24 * 3600, backup.snapshot)]
    if ai.enabled():
        jobs.append(Job("genres", 2 * 3600, ai.fill_genres))
        jobs.append(Job("fun facts", 24 * 3600, ai.refresh_fun_facts))       # writes a new card weekly
    return jobs


def run_forever(stop, jobs=None, tick=30.0):
    jobs = default_jobs() if jobs is None else jobs
    while not stop.is_set():
        now = time.monotonic()
        for job in jobs:
            if now >= job.next_at:
                try:
                    result = job.fn()
                    log.info("%s: %s", job.name, result)
                except Exception:
                    log.exception("%s failed", job.name)
                job.next_at = now + job.every
        stop.wait(tick)
