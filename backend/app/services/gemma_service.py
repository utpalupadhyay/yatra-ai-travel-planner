"""
Yatra AI - High-Performance AI Travel Intelligence Service
Optimized for ultra-low latency, streaming responses (SSE), and intelligent caching.
Primary engine: Fast Gemini Flash models with graceful fallbacks.
"""
import os
import json
import uuid
import asyncio
import logging
from typing import Optional, AsyncIterator, Any
from google import genai
from google.genai import types

from app.core.config import get_settings
from app.services import cache_service

logger = logging.getLogger(__name__)

# Global reusable client instance to avoid repeated TLS handshakes
_client_instance: Optional[genai.Client] = None
_last_api_key: Optional[str] = None


def _get_api_key() -> str:
    """Retrieve GEMMA_API_KEY, GEMINI_API_KEY, or GOOGLE_API_KEY from environment or settings."""
    for var_name in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMMA_API_KEY"]:
        key = os.environ.get(var_name, "").strip()
        if key:
            return key
    settings = get_settings()
    for attr in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMMA_API_KEY"]:
        key = (getattr(settings, attr, "") or "").strip()
        if key:
            return key
    return ""


def _get_client() -> genai.Client:
    """Return a cached, authenticated Gemini API client with connection pooling and timeouts."""
    global _client_instance, _last_api_key
    key = _get_api_key()
    if not key or key in ["your_actual_key", "your_new_key_here", "your_gemma_api_key_here"]:
        raise ValueError(
            "AI service is not configured. Please add GEMMA_API_KEY or GEMINI_API_KEY to the server environment."
        )

    if _client_instance is None or _last_api_key != key:
        # 25-second timeout to prevent hanging connections
        http_opts = types.HttpOptions(
            api_version="v1beta",
            timeout=25000,
        )
        _client_instance = genai.Client(api_key=key, http_options=http_opts)
        _last_api_key = key
        logger.info("Initialized high-speed Gemini API client.")

    return _client_instance


def _get_model_candidates() -> list[str]:
    """
    Return prioritized list of models for generation.
    Picks the fastest suitable model first, with fallbacks.
    """
    settings = get_settings()
    env_model = (
        os.environ.get("GEMINI_MODEL")
        or os.environ.get("GEMMA_MODEL")
        or getattr(settings, "GEMINI_MODEL", "")
    ).strip()

    candidates: list[str] = []
    # If a specific fast model was set in env (not the slow 31B gemma), honor it first
    if env_model and env_model not in ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]:
        candidates.append(env_model)
    elif os.environ.get("FORCE_GEMMA"):
        candidates.append("gemma-4-31b-it")
    else:
        # Default fastest suitable model
        candidates.append("gemini-2.5-flash")

    # Add standard fallbacks
    for m in settings.PREFERRED_MODELS:
        if m not in candidates:
            candidates.append(m)

    return candidates


def _build_system_prompt(language: str = "english") -> str:
    """Return a concise, high-impact system prompt for fast and structured travel planning."""
    if language == "hindi":
        return (
            "आप Yatra AI हैं — भारत के लिए एक उच्च-प्रदर्शन यात्रा योजनाकार। "
            "सटीक, सुव्यवस्थित और बजट-जागरूक यात्रा कार्यक्रम प्रदान करें। "
            "सभी कीमतें INR (₹) में दें। अनावश्यक प्रस्तावना के बिना सीधे योजना प्रस्तुत करें। "
            "स्पष्ट और सुंदर मार्कडाउन प्रारूप का उपयोग करें।"
        )
    return (
        "You are Yatra AI, an expert travel intelligence engine for Indian destinations. "
        "Provide accurate, structured, budget-conscious travel itineraries with exact place names, local food, and realistic INR (₹) costs. "
        "Deliver clear Markdown formatting with emojis. Start directly with the content without generic greetings."
    )


def _categorize_error(e: Exception) -> str:
    """Translate raw exceptions into clear, actionable error messages."""
    err_str = str(e).lower()
    if any(w in err_str for w in ["api_key_invalid", "api key not valid", "invalid api key", "unauthenticated", "401", "403", "permission_denied"]):
        return "The AI API key is invalid or expired."
    elif any(w in err_str for w in ["resource_exhausted", "quota", "rate limit", "busy", "429"]):
        return "The AI service is temporarily busy. Please try again."
    elif any(w in err_str for w in ["connect", "connecterror", "timeout", "timed out", "dns", "network", "offline"]):
        return "Unable to connect to the AI service. Please try again."
    return f"AI generation failed: {str(e)}"


# ──────────────────────────────────────────────
# CORE FEATURE 1: Trip Itinerary Generator (Streaming + Non-Streaming)
# ──────────────────────────────────────────────
def _build_trip_prompt(
    destination: str,
    origin: str,
    num_days: int,
    budget: float,
    num_travelers: int,
    interests: list[str],
    accommodation: str,
    food_preference: str,
    special_requests: Optional[str],
    language: str = "english",
) -> str:
    interests_str = ", ".join(interests) if interests else "Sightseeing, Local Culture"
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."

    return f"""{lang_instruction}
Create a high-quality, practical {num_days}-day travel itinerary for {destination} starting from {origin}.
Travelers: {num_travelers} | Total Budget: ₹{budget:,.0f} (INR) | Stay: {accommodation.replace('_', ' ').title()} | Food: {food_preference.replace('_', ' ').title()}
Interests: {interests_str}
Special Requests: {special_requests or 'None'}

Formatting Instructions:
- Jump straight into the itinerary; no conversational filler or preambles.
- Structure each day clearly:
  ### Day X: [Theme / Focus]
  - 🌅 **Morning:** [Specific places & activities]
  - ☀️ **Afternoon:** [Sightseeing & food recommendation with approximate ₹ cost]
  - 🌙 **Evening:** [Attraction / night market & dinner recommendation]
  - 💰 **Est. Daily Cost:** ₹[Amount]
- After all days, provide:
  ### 🏨 Recommended Stays
  - 2-3 specific hotel/homestay options matching {accommodation} budget.
  ### 🚌 Local Transit Tips
  - Best ways to get around affordably.
  ### 💰 Budget Breakdown
  - Stays, Food, Transit, Activities, Buffer. Total must align with ₹{budget:,.0f}.
  ### 💡 Pro Travel Tips
  - 3-4 essential local tips.
Use emojis and clean markdown tables where helpful.
"""


async def generate_itinerary_stream(
    destination: str,
    origin: str,
    num_days: int,
    budget: float,
    num_travelers: int,
    interests: list[str],
    accommodation: str,
    food_preference: str,
    special_requests: Optional[str],
    language: str = "english",
) -> AsyncIterator[str]:
    """
    Stream travel itinerary chunk by chunk using Server-Sent Events (SSE).
    Uses in-memory cache for instant replay if available.
    """
    settings = get_settings()

    # 1. Check in-memory cache
    cache_key = cache_service.make_trip_cache_key(
        destination=destination,
        origin=origin,
        num_days=num_days,
        budget=budget,
        num_travelers=num_travelers,
        interests=interests,
        accommodation=accommodation,
        food_preference=food_preference,
        language=language,
    )
    if settings.ENABLE_CACHE:
        cached = cache_service.cache.get(cache_key)
        if cached:
            logger.info(f"[CACHE HIT] Instant streaming for {destination}")
            cached_text = cached.get("itinerary", "")
            interaction_id = cached.get("interaction_id", f"cached-{uuid.uuid4().hex[:8]}")
            # Stream out cached content in fast bursts for smooth rendering
            chunk_size = 250
            for i in range(0, len(cached_text), chunk_size):
                part = cached_text[i : i + chunk_size]
                yield f"data: {json.dumps({'chunk': part, 'done': False})}\n\n"
                await asyncio.sleep(0.015)
            yield f"data: {json.dumps({'chunk': '', 'itinerary': cached_text, 'interaction_id': interaction_id, 'cached': True, 'done': True})}\n\n"
            return

    # 2. Setup client and candidates
    client = _get_client()
    system_prompt = _build_system_prompt(language)
    prompt = _build_trip_prompt(
        destination=destination,
        origin=origin,
        num_days=num_days,
        budget=budget,
        num_travelers=num_travelers,
        interests=interests,
        accommodation=accommodation,
        food_preference=food_preference,
        special_requests=special_requests,
        language=language,
    )

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None
    full_text = ""
    interaction_id = f"trip-{uuid.uuid4().hex[:12]}"

    for model_name in models_to_try:
        try:
            logger.info(f"Streaming trip generation with model: {model_name}")
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=settings.GEMMA_TEMPERATURE,
                max_output_tokens=settings.GEMMA_MAX_TOKENS,
            )

            # Use asynchronous streaming via client.aio
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=config,
            )

            async for chunk in stream:
                text_part = chunk.text or ""
                if text_part:
                    full_text += text_part
                    yield f"data: {json.dumps({'chunk': text_part, 'done': False})}\n\n"

            if full_text.strip():
                # Successfully streamed entire response
                if settings.ENABLE_CACHE:
                    cache_service.cache.set(
                        cache_key,
                        {"itinerary": full_text, "interaction_id": interaction_id},
                        ttl_seconds=settings.CACHE_TTL_SECONDS,
                    )
                yield f"data: {json.dumps({'chunk': '', 'itinerary': full_text, 'interaction_id': interaction_id, 'cached': False, 'done': True})}\n\n"
                return

        except Exception as e:
            logger.warning(f"Model {model_name} stream error: {e}. Trying fallback...")
            last_error = e
            full_text = ""
            continue

    # If all models failed
    err_message = _categorize_error(last_error or Exception("No AI model succeeded"))
    yield f"data: {json.dumps({'error': err_message, 'done': True})}\n\n"


def generate_itinerary(
    destination: str,
    origin: str,
    num_days: int,
    budget: float,
    num_travelers: int,
    interests: list[str],
    accommodation: str,
    food_preference: str,
    special_requests: Optional[str],
    language: str = "english",
) -> dict:
    """
    Synchronous / non-streaming generator with cache lookup and multi-model fallback.
    Maintains 100% backwards compatibility.
    """
    settings = get_settings()
    cache_key = cache_service.make_trip_cache_key(
        destination=destination,
        origin=origin,
        num_days=num_days,
        budget=budget,
        num_travelers=num_travelers,
        interests=interests,
        accommodation=accommodation,
        food_preference=food_preference,
        language=language,
    )

    if settings.ENABLE_CACHE:
        cached = cache_service.cache.get(cache_key)
        if cached:
            logger.info(f"[CACHE HIT] Returning cached itinerary for {destination}")
            return cached

    client = _get_client()
    system_prompt = _build_system_prompt(language)
    prompt = _build_trip_prompt(
        destination=destination,
        origin=origin,
        num_days=num_days,
        budget=budget,
        num_travelers=num_travelers,
        interests=interests,
        accommodation=accommodation,
        food_preference=food_preference,
        special_requests=special_requests,
        language=language,
    )

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None

    for model_name in models_to_try:
        try:
            logger.info(f"Generating trip itinerary with model: {model_name}")
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=settings.GEMMA_TEMPERATURE,
                max_output_tokens=settings.GEMMA_MAX_TOKENS,
            )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            output_text = getattr(response, "text", "") or ""
            if output_text.strip():
                interaction_id = f"trip-{uuid.uuid4().hex[:12]}"
                result = {
                    "itinerary": output_text,
                    "interaction_id": interaction_id,
                }
                if settings.ENABLE_CACHE:
                    cache_service.cache.set(cache_key, result, ttl_seconds=settings.CACHE_TTL_SECONDS)
                return result
        except Exception as e:
            logger.warning(f"Model {model_name} generation failed: {e}. Trying fallback...")
            last_error = e
            continue

    raise ValueError(_categorize_error(last_error or Exception("All AI models failed.")))


# ──────────────────────────────────────────────
# CORE FEATURE 2: Smart Re-planner
# ──────────────────────────────────────────────
async def replan_trip_stream(
    original_plan: str,
    change_request: str,
    destination: str,
    num_days: int,
    new_budget: Optional[float],
    language: str = "english",
) -> AsyncIterator[str]:
    """Stream modified trip itinerary based on user changes."""
    client = _get_client()
    settings = get_settings()
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."
    budget_note = f"New budget constraint: ₹{new_budget:,.0f}" if new_budget else "Budget remains the same."

    prompt = f"""{lang_instruction}
The user wants to modify their existing {num_days}-day trip to {destination}.
Original Trip Plan Summary:
{original_plan[:2500]}

User's Modification Request:
{change_request}
{budget_note}

Please provide:
1. **What Changed** — brief 2-3 bullet point summary of changes
2. **Updated Itinerary** — revised day-by-day plan with times and activities
3. **Updated Budget Table** — revised category costs and savings
4. **Local Tips** — why this adapted plan works best
Keep tone helpful and clear. Format cleanly in Markdown with emojis.
"""

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None
    full_text = ""
    interaction_id = f"replan-{uuid.uuid4().hex[:12]}"

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(language),
                temperature=settings.GEMMA_TEMPERATURE,
                max_output_tokens=settings.GEMMA_MAX_TOKENS,
            )
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                text_part = chunk.text or ""
                if text_part:
                    full_text += text_part
                    yield f"data: {json.dumps({'chunk': text_part, 'done': False})}\n\n"

            if full_text.strip():
                yield f"data: {json.dumps({'chunk': '', 'itinerary': full_text, 'interaction_id': interaction_id, 'done': True})}\n\n"
                return
        except Exception as e:
            logger.warning(f"Replan stream error on {model_name}: {e}")
            last_error = e
            continue

    err_msg = _categorize_error(last_error or Exception("Replan failed."))
    yield f"data: {json.dumps({'error': err_msg, 'done': True})}\n\n"


def replan_trip(
    original_plan: str,
    change_request: str,
    destination: str,
    num_days: int,
    new_budget: Optional[float],
    language: str = "english",
) -> dict:
    """Non-streaming trip modification with fallback."""
    client = _get_client()
    settings = get_settings()
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."
    budget_note = f"New budget constraint: ₹{new_budget:,.0f}" if new_budget else "Budget remains the same."

    prompt = f"""{lang_instruction}
Modify existing {num_days}-day trip to {destination}.
Original Plan:
{original_plan[:2500]}

Change Request:
{change_request}
{budget_note}

Provide:
1. **What Changed**
2. **Updated Itinerary**
3. **Updated Budget Table**
Format in clean Markdown with emojis.
"""

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(language),
                temperature=settings.GEMMA_TEMPERATURE,
                max_output_tokens=settings.GEMMA_MAX_TOKENS,
            )
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            text = resp.text or ""
            if text.strip():
                return {
                    "itinerary": text,
                    "interaction_id": f"replan-{uuid.uuid4().hex[:12]}",
                }
        except Exception as e:
            last_error = e
            continue

    raise ValueError(_categorize_error(last_error or Exception("Replan failed.")))


# ──────────────────────────────────────────────
# CORE FEATURE 3: Travel Chat Assistant
# ──────────────────────────────────────────────
async def chat_with_assistant_stream(
    message: str,
    trip_context: Optional[str],
    conversation_id: Optional[str],
    language: str = "english",
) -> AsyncIterator[str]:
    """Stream chat responses word-by-word with conversation context."""
    client = _get_client()
    settings = get_settings()
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."

    context_block = ""
    if trip_context:
        context_block = f"**Current Trip Context:**\n{trip_context[:1800]}\n\n"

    prompt = f"{lang_instruction}\n{context_block}**User Question:** {message}\nProvide a direct, helpful, concise answer in Markdown with emojis."

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None
    full_text = ""
    next_conv_id = conversation_id or f"chat-{uuid.uuid4().hex[:12]}"

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(language),
                temperature=0.7,
                max_output_tokens=2048,
            )
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                text_part = chunk.text or ""
                if text_part:
                    full_text += text_part
                    yield f"data: {json.dumps({'chunk': text_part, 'done': False})}\n\n"

            if full_text.strip():
                yield f"data: {json.dumps({'chunk': '', 'reply': full_text, 'interaction_id': next_conv_id, 'done': True})}\n\n"
                return
        except Exception as e:
            logger.warning(f"Chat stream error on {model_name}: {e}")
            last_error = e
            continue

    err_msg = _categorize_error(last_error or Exception("Chat failed."))
    yield f"data: {json.dumps({'error': err_msg, 'done': True})}\n\n"


def chat_with_assistant(
    message: str,
    trip_context: Optional[str],
    conversation_id: Optional[str],
    language: str = "english",
) -> dict:
    """Non-streaming chat response."""
    client = _get_client()
    settings = get_settings()
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."

    context_block = f"**Current Trip Context:**\n{trip_context[:1800]}\n\n" if trip_context else ""
    prompt = f"{lang_instruction}\n{context_block}**User Question:** {message}\nProvide a direct, helpful answer in Markdown."

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(language),
                temperature=0.7,
                max_output_tokens=2048,
            )
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            text = resp.text or ""
            if text.strip():
                return {
                    "reply": text,
                    "interaction_id": conversation_id or f"chat-{uuid.uuid4().hex[:12]}",
                }
        except Exception as e:
            last_error = e
            continue

    raise ValueError(_categorize_error(last_error or Exception("Chat failed.")))


# ──────────────────────────────────────────────
# CORE FEATURE 4: Packing Assistant
# ──────────────────────────────────────────────
def generate_packing_list(
    destination: str,
    num_days: int,
    interests: list[str],
    season: Optional[str],
    language: str = "english",
) -> dict:
    """Generate a personalized packing checklist with caching."""
    settings = get_settings()
    cache_key = cache_service.make_packing_cache_key(
        destination=destination,
        num_days=num_days,
        interests=interests,
        language=language,
    )
    if settings.ENABLE_CACHE:
        cached = cache_service.cache.get(cache_key)
        if cached:
            logger.info(f"[CACHE HIT] Packing list for {destination}")
            return cached

    client = _get_client()
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."
    interests_str = ", ".join(interests) if interests else "General sightseeing"
    season_note = f"Season: {season}" if season else ""

    prompt = f"""{lang_instruction}
Create a concise, smart packing checklist for:
📍 Destination: {destination} | 📅 Duration: {num_days} days | 🎯 Interests: {interests_str} {season_note}

Organize with checkboxes:
### 👔 Clothing & Footwear
### 🔌 Electronics & Cables
### 💊 Health & Medications
### 📄 Documents & Cash
### 🧴 Toiletries & Sun Protection
### 🎒 Backpack Daypack Items
### 💡 Don't Forget (3 India Travel Essentials)
"""

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(language),
                temperature=0.7,
                max_output_tokens=2048,
            )
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            text = resp.text or ""
            if text.strip():
                result = {
                    "packing_list": text,
                    "interaction_id": f"pack-{uuid.uuid4().hex[:12]}",
                }
                if settings.ENABLE_CACHE:
                    cache_service.cache.set(cache_key, result, ttl_seconds=settings.CACHE_TTL_SECONDS)
                return result
        except Exception as e:
            last_error = e
            continue

    raise ValueError(_categorize_error(last_error or Exception("Packing list generation failed.")))


# ──────────────────────────────────────────────
# CORE FEATURE 5: Budget Optimizer
# ──────────────────────────────────────────────
def optimize_budget(
    destination: str,
    num_days: int,
    budget: float,
    num_travelers: int,
    current_plan: str,
    language: str = "english",
) -> dict:
    """Analyze and optimize the trip budget with caching."""
    settings = get_settings()
    cache_key = cache_service.make_budget_cache_key(
        destination=destination,
        num_days=num_days,
        budget=budget,
        num_travelers=num_travelers,
        language=language,
    )
    if settings.ENABLE_CACHE:
        cached = cache_service.cache.get(cache_key)
        if cached:
            logger.info(f"[CACHE HIT] Budget optimization for {destination}")
            return cached

    client = _get_client()
    lang_instruction = "Respond in Hindi." if language == "hindi" else "Respond in English."
    per_person = budget / max(1, num_travelers)

    prompt = f"""{lang_instruction}
Analyze and optimize the budget for this trip:
- Destination: {destination}
- Duration: {num_days} days
- Budget: ₹{budget:,.0f} total for {num_travelers} traveler(s) (₹{per_person:,.0f}/person)
Current plan context:
{current_plan[:1500]}

Provide:
### 💰 Top 5 Cost-Saving Opportunities
### 🏷️ Best Value Experiences (High impact, low cost)
### 🍜 Authentic Budget Dining Guide
### 🚌 Smart Transportation Hacks
### 📊 Optimized Budget Allocation Table
| Category | Original Est. | Optimized | Potential Savings |
|---|---|---|---|
"""

    models_to_try = _get_model_candidates()
    last_error: Optional[Exception] = None

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_build_system_prompt(language),
                temperature=0.7,
                max_output_tokens=2048,
            )
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            text = resp.text or ""
            if text.strip():
                result = {
                    "optimization": text,
                    "interaction_id": f"budget-{uuid.uuid4().hex[:12]}",
                }
                if settings.ENABLE_CACHE:
                    cache_service.cache.set(cache_key, result, ttl_seconds=settings.CACHE_TTL_SECONDS)
                return result
        except Exception as e:
            last_error = e
            continue

    raise ValueError(_categorize_error(last_error or Exception("Budget optimization failed.")))
