from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.summarize import router as summarize_router
from app.config import get_settings
from app.db.mongo import ping
from app.db.queue import queue_stats
from app.db.repository import startup_mongo


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_mongo()
    yield


app = FastAPI(
    title="Handwrite Direct Summary (Claude Sonnet 5)",
    version="1.0.0",
    description="Send a medical/legal PDF to Claude Sonnet 5 and get summary.txt only. No extracted.txt.",
    lifespan=lifespan,
)
app.include_router(summarize_router)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "mode": "direct_pdf_summary",
        "extractor": "claude-sonnet-5-direct-summary",
        "model": settings.anthropic_model,
        "api_key_configured": settings.credentials_ok,
        "chunk_pages": settings.effective_chunk_pages(),
        "mongodb_enabled": settings.mongodb_enabled,
        "mongodb_connected": ping() if settings.mongodb_enabled else False,
        "mongodb_collection": settings.mongodb_collection,
        "inline_extract": settings.inline_extract,
        "queue": queue_stats() if settings.mongodb_enabled else {},
    }
