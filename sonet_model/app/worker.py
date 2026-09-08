"""Poll MongoDB for unprocessed Sonnet jobs.

    python -m app.worker
"""

from __future__ import annotations

import logging
import socket
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app.config import get_settings
from app.db.mongo import ping
from app.db.queue import claim_next_job, queue_stats
from app.db.repository import startup_mongo
from app.pipeline.job_store import JobStore
from app.pipeline.runner import run_extraction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("worker")


def _worker_id() -> str:
    return f"{socket.gethostname()}-sonnet-{time.time_ns()}"


def _process(job_id: str) -> None:
    store = JobStore()
    record = store.load(job_id)
    if record is None:
        logger.error("Claimed %s but job files are missing", job_id)
        return
    logger.info("Processing %s (%s)", job_id, record.source_file)
    try:
        run_extraction(job_id)
    except Exception:  # noqa: BLE001
        logger.exception("Job %s failed", job_id)
        try:
            store.update(
                job_id,
                status="error",
                error=traceback.format_exc()[-2000:],
                message="Extraction failed",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Could not mark job %s failed", job_id)


def main() -> None:
    settings = get_settings()
    startup_mongo()
    if not ping():
        raise SystemExit("MongoDB is not reachable. Worker cannot claim jobs.")
    if not settings.credentials_ok:
        raise SystemExit("ANTHROPIC_API_KEY is not set in sonet_model/.env")

    worker_id = _worker_id()
    max_jobs = max(1, settings.worker_max_jobs)
    poll = max(0.5, settings.worker_poll_seconds)
    logger.info(
        "Sonnet worker %s started (max_jobs=%s poll=%ss model=%s concurrent=%s chunk_pages=%s)",
        worker_id,
        max_jobs,
        poll,
        settings.anthropic_model,
        settings.sonnet_max_concurrent,
        settings.effective_chunk_pages(),
    )

    inflight: set = set()
    with ThreadPoolExecutor(max_workers=max_jobs) as pool:
        while True:
            done, inflight = wait(inflight, timeout=0, return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    future.result()
                except Exception:  # noqa: BLE001
                    logger.exception("Worker future failed")

            while len(inflight) < max_jobs:
                claimed = claim_next_job(worker_id)
                if not claimed:
                    break
                job_id = claimed.get("job_id")
                if not job_id:
                    break
                inflight.add(pool.submit(_process, job_id))

            if not inflight:
                stats = queue_stats()
                logger.info("Idle queue=%s", stats)
                time.sleep(poll)
            else:
                wait(inflight, timeout=poll, return_when=FIRST_COMPLETED)


if __name__ == "__main__":
    main()
