"""
Yatra AI - FastAPI Route Handlers
High-performance trip planning, chat, and streaming endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import get_settings
from app.models.trip import (
    TripRequest, ReplanRequest, ChatRequest,
    PackingRequest, TripResponse, ChatResponse
)
from app.services import gemma_service, cache_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Yatra AI"])
settings = get_settings()

SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/health")
async def health_check():
    """API health check endpoint with cache metrics."""
    return {
        "status": "ok",
        "service": "Yatra AI",
        "model": settings.GEMINI_MODEL,
        "cache": cache_service.cache.get_stats(),
    }


# ──────────────────────────────────────────────
# 1. STREAMING TRIP GENERATION (SSE)
# ──────────────────────────────────────────────
@router.post("/trip/generate-stream")
@router.post("/generate-trip-stream")
async def generate_trip_stream_endpoint(request: TripRequest):
    """
    ⚡ Stream AI trip generation in real-time via Server-Sent Events (SSE).
    Provides instant Time-To-First-Token (TTFT) and seamless chunk delivery.
    """
    try:
        origin_val = request.get_origin
        days_val = request.get_num_days
        travelers_val = request.get_num_travelers
        food_val = request.get_food_preference
        special_val = request.get_special_requests
        lang_val = str(request.language.value if hasattr(request.language, "value") else (request.language or "english"))
        accom_val = str(request.accommodation.value if hasattr(request.accommodation, "value") else (request.accommodation or "mid_range"))

        logger.info(f"Stream generation: {origin_val} → {request.destination}, {days_val} days")

        return StreamingResponse(
            gemma_service.generate_itinerary_stream(
                destination=request.destination,
                origin=origin_val,
                num_days=days_val,
                budget=request.budget,
                num_travelers=travelers_val,
                interests=request.interests,
                accommodation=accom_val,
                food_preference=food_val,
                special_requests=special_val,
                language=lang_val,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    except Exception as e:
        logger.error(f"Stream setup error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


# ──────────────────────────────────────────────
# 2. STANDARD TRIP GENERATION (JSON)
# ──────────────────────────────────────────────
@router.post("/trip/generate", response_model=TripResponse)
@router.post("/generate-trip", response_model=TripResponse)
async def generate_trip(request: TripRequest):
    """
    🗺️ Generate complete travel itinerary (JSON).
    Backed by in-memory cache and fastest available Gemini model.
    """
    try:
        origin_val = request.get_origin
        days_val = request.get_num_days
        travelers_val = request.get_num_travelers
        food_val = request.get_food_preference
        special_val = request.get_special_requests
        lang_val = str(request.language.value if hasattr(request.language, "value") else (request.language or "english"))
        accom_val = str(request.accommodation.value if hasattr(request.accommodation, "value") else (request.accommodation or "mid_range"))

        logger.info(f"Generating trip: {origin_val} → {request.destination}, {days_val} days")

        result = gemma_service.generate_itinerary(
            destination=request.destination,
            origin=origin_val,
            num_days=days_val,
            budget=request.budget,
            num_travelers=travelers_val,
            interests=request.interests,
            accommodation=accom_val,
            food_preference=food_val,
            special_requests=special_val,
            language=lang_val,
        )

        return TripResponse(
            success=True,
            itinerary=result["itinerary"],
            interaction_id=result.get("interaction_id"),
        )

    except ValueError as e:
        err_msg = str(e)
        logger.warning(f"Trip validation / AI error: {err_msg}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": err_msg, "detail": err_msg},
        )
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Trip generation error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": err_msg, "detail": err_msg},
        )


# ──────────────────────────────────────────────
# 3. RE-PLANNER (STREAMING + JSON)
# ──────────────────────────────────────────────
@router.post("/trip/replan-stream")
async def replan_trip_stream_endpoint(request: ReplanRequest):
    """Stream modified trip itinerary."""
    return StreamingResponse(
        gemma_service.replan_trip_stream(
            original_plan=request.original_plan,
            change_request=request.change_request,
            destination=request.destination,
            num_days=request.num_days,
            new_budget=request.new_budget,
            language=request.language.value,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/trip/replan", response_model=TripResponse)
async def replan_trip(request: ReplanRequest):
    """Modify existing trip (JSON)."""
    try:
        logger.info(f"Replanning trip to {request.destination}")
        result = gemma_service.replan_trip(
            original_plan=request.original_plan,
            change_request=request.change_request,
            destination=request.destination,
            num_days=request.num_days,
            new_budget=request.new_budget,
            language=request.language.value,
        )
        return TripResponse(
            success=True,
            itinerary=result["itinerary"],
            interaction_id=result["interaction_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Replan error: {e}")
        raise HTTPException(status_code=500, detail=f"Re-planning failed: {str(e)}")


# ──────────────────────────────────────────────
# 4. CHAT ASSISTANT (STREAMING + JSON)
# ──────────────────────────────────────────────
@router.post("/chat-stream")
async def chat_stream_endpoint(request: ChatRequest):
    """Stream chat response word-by-word with conversation context."""
    return StreamingResponse(
        gemma_service.chat_with_assistant_stream(
            message=request.message,
            trip_context=request.trip_context,
            conversation_id=request.conversation_id,
            language=request.language.value,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Multi-turn Travel Chat Assistant (JSON)."""
    try:
        result = gemma_service.chat_with_assistant(
            message=request.message,
            trip_context=request.trip_context,
            conversation_id=request.conversation_id,
            language=request.language.value,
        )
        return ChatResponse(
            success=True,
            reply=result["reply"],
            interaction_id=result["interaction_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


# ──────────────────────────────────────────────
# 5. PACKING LIST (CACHED)
# ──────────────────────────────────────────────
@router.post("/trip/packing")
async def get_packing_list(request: PackingRequest):
    """Generate personalized packing checklist."""
    try:
        result = gemma_service.generate_packing_list(
            destination=request.destination,
            num_days=request.num_days,
            interests=request.interests,
            season=request.season,
            language=request.language.value,
        )
        return {
            "success": True,
            "packing_list": result["packing_list"],
            "interaction_id": result["interaction_id"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Packing list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# 6. BUDGET OPTIMIZER (CACHED)
# ──────────────────────────────────────────────
@router.post("/trip/optimize-budget")
async def optimize_budget(
    destination: str,
    num_days: int,
    budget: float,
    num_travelers: int,
    current_plan: str,
    language: str = "english",
):
    """Analyze and optimize trip budget."""
    try:
        result = gemma_service.optimize_budget(
            destination=destination,
            num_days=num_days,
            budget=budget,
            num_travelers=num_travelers,
            current_plan=current_plan,
            language=language,
        )
        return {
            "success": True,
            "optimization": result["optimization"],
            "interaction_id": result["interaction_id"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Budget optimization error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
