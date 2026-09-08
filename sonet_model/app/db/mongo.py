from __future__ import annotations

import logging
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None


def get_client() -> MongoClient | None:
    global _client
    settings = get_settings()
    if not settings.mongodb_enabled:
        return None
    if _client is None:
        _client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
        )
    return _client


def get_collection() -> Collection | None:
    settings = get_settings()
    client = get_client()
    if client is None:
        return None
    return client[settings.mongodb_db][settings.mongodb_collection]


def ping() -> bool:
    try:
        client = get_client()
        if client is None:
            return False
        client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_indexes() -> None:
    collection = get_collection()
    if collection is None:
        return
    collection.create_index("job_id", unique=True)
    collection.create_index("user_id")
    collection.create_index("status")
    collection.create_index([("timestamps.created_at", ASCENDING)])
    collection.create_index([("status", ASCENDING), ("timestamps.created_at", ASCENDING)])


def upsert_document(job_id: str, payload: dict[str, Any]) -> bool:
    try:
        collection = get_collection()
        if collection is None:
            return False
        collection.update_one({"job_id": job_id}, {"$set": payload}, upsert=True)
        return True
    except PyMongoError:
        logger.exception("MongoDB upsert failed for job %s", job_id)
        return False
