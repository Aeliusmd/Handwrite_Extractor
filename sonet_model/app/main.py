from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.extract import router as extract_router
from app.config import get_settings
from app.db.mongo import ping
from app.db.queue import queue_stats
from app.db.repository import startup_mongo


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_mongo()
    yield


app = FastAPI(
    title="Handwrite Extractor (Claude Sonnet 5)",
    version="1.0.0",
    description="Extract printed text, handwriting, checkboxes, and notes from medical/legal PDFs using Claude Sonnet 5.",
    lifespan=lifespan,
)
app.include_router(extract_router)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "extractor": "claude-sonnet-5",
        "model": settings.anthropic_model,
        "api_key_configured": settings.credentials_ok,
        "chunk_pages": settings.effective_chunk_pages(),
        "max_chunk_pages": min(100, settings.max_chunk_pages),
        "mongodb_enabled": settings.mongodb_enabled,
        "mongodb_connected": ping() if settings.mongodb_enabled else False,
        "mongodb_collection": settings.mongodb_collection,
        "inline_extract": settings.inline_extract,
        "summarization": settings.enable_summarization,
        "queue": queue_stats() if settings.mongodb_enabled else {},
    }
