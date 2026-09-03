from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.extract import router as extract_router
from app.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings().apply_prediction_endpoint()
    get_settings().apply_google_credentials()
    yield


app = FastAPI(
    title="Handwrite Extractor",
    version="1.0.0",
    description="Extract printed text, handwriting, checkboxes, and notes from medical/legal PDFs.",
    lifespan=lifespan,
)
app.include_router(extract_router)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    creds = settings.apply_google_credentials()
    return {
        "status": "ok",
        "gcp_project_configured": bool(settings.gcp_project_id),
        "processor_configured": bool(settings.docai_processor_id),
        "credentials_file_present": bool(creds and creds.exists()),
        "vision_rescue": settings.enable_vision_rescue,
        "chunk_size": settings.chunk_size,
    }
