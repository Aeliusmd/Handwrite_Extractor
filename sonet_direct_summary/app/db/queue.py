from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.config import get_settings
from app.db.mongo import get_collection

logger = logging.getLogger(__name__)


def queue_stats() -> dict:
    collection = get_collection()
    if collection is None:
        return {"unprocessed": 0, "processing": 0, "completed": 0, "failed": 0}
    return {
        "unprocessed": collection.count_documents({"status": "unprocessed"}),
        "processing": collection.count_documents({"status": "processing"}),
        "completed": collection.count_documents({"status": "completed"}),
        "failed": collection.count_documents({"status": "failed"}),
    }


def claim_next_job(worker_id: str) -> dict | None:
    collection = get_collection()
    if collection is None:
        return None
    settings = get_settings()
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(minutes=settings.worker_stale_minutes)).isoformat()
    now_iso = now.isoformat()
    doc = collection.find_one_and_update(
        {
            "$or": [
                {"status": "unprocessed"},
                {
                    "status": "processing",
                    "timestamps.updated_at": {"$lt": stale_before},
                },
            ]
        },
        {
            "$set": {
                "status": "processing",
                "pipeline_status": "queued",
                "claimed_by": worker_id,
                "claimed_at": now_iso,
                "message": f"Claimed by {worker_id}",
                "timestamps.updated_at": now_iso,
                "timestamps.started_at": now_iso,
            }
        },
        sort=[("timestamps.created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    if doc:
        logger.info("Claimed job %s", doc.get("job_id"))
    return doc
