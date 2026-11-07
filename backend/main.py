"""
Yatra AI - FastAPI Application Entry Point
Production-ready with streaming responses, in-memory caching, and GZip compression.
"""
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

from app.core.config import get_settings
from app.api.routes.trip import router as trip_router
from app.api.routes.trip import (
    generate_trip,
    generate_trip_stream_endpoint,
    chat_stream_endpoint,
    replan_trip_stream_endpoint,
)
from app.models.trip import TripRequest, ChatRequest, ReplanRequest
from app.services import cache_service

# ── Logging ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# ── FastAPI App ───────────────────────────────
app = FastAPI(
    title="Yatra AI",
    description="High-performance AI travel planner powered by Gemini & Gemma. Plan smarter. Travel better.",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────
# 1. GZip Compression for smaller payloads & faster transfer
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 2. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static / Frontend Files ───────────────────
BASE_DIR = Path(__file__).resolve().parent
candidates = [
    BASE_DIR / "frontend",
    BASE_DIR / "static",
    BASE_DIR.parent / "frontend",
]
frontend_dir = None
for c in candidates:
    if (c / "index.html").exists():
        frontend_dir = c
        break


class CachedStaticFiles(StaticFiles):
    """StaticFiles with browser caching headers (1 day cache)."""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


if frontend_dir and (frontend_dir / "assets").exists():
    app.mount("/assets", CachedStaticFiles(directory=str(frontend_dir / "assets")), name="assets")

# ── Include Router ────────────────────────────
app.include_router(trip_router)


# ── Direct Convenience Routes ─────────────────
@app.post("/api/generate-trip-stream")
@app.post("/api/trip/generate-stream")
async def api_generate_trip_stream(request: TripRequest):
    """Direct route for streaming trip generation."""
    return await generate_trip_stream_endpoint(request)


@app.post("/api/generate-trip")
async def api_generate_trip(request: TripRequest):
    """Direct route for /api/generate-trip JSON endpoint."""
    return await generate_trip(request)


@app.post("/api/chat-stream")
async def api_chat_stream(request: ChatRequest):
    """Direct route for streaming chat."""
    return await chat_stream_endpoint(request)


@app.post("/api/trip/replan-stream")
async def api_replan_trip_stream(request: ReplanRequest):
    """Direct route for streaming replan."""
    return await replan_trip_stream_endpoint(request)


# ── Root & Info Routes ────────────────────────
@app.get("/")
async def root():
    if frontend_dir and (frontend_dir / "index.html").exists():
        return FileResponse(
            str(frontend_dir / "index.html"),
            headers={"Cache-Control": "public, max-age=300"},
        )
    return {
        "app": "Yatra AI",
        "tagline": "Plan smarter. Travel better.",
        "model": settings.GEMINI_MODEL,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


@app.get("/api/info")
async def api_info():
    return {
        "app": "Yatra AI",
        "tagline": "Plan smarter. Travel better.",
        "model": settings.GEMINI_MODEL,
        "version": settings.APP_VERSION,
        "features": ["streaming_sse", "in_memory_cache", "gemini_flash_acceleration"],
        "cache_stats": cache_service.cache.get_stats(),
        "docs": "/docs",
    }


@app.get("/favicon.ico")
async def favicon():
    if frontend_dir:
        fav = frontend_dir / "assets" / "images" / "favicon.svg"
        if fav.exists():
            return FileResponse(
                str(fav),
                media_type="image/svg+xml",
                headers={"Cache-Control": "public, max-age=86400"},
            )
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "An unexpected error occurred. Please try again."},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
