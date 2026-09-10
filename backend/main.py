import logging
import json
import os
from time import perf_counter
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import Client, create_client

from analytics import router as analytics_router
from commons.routes import router as commons_router
from dice.routes import router as dice_router
from runtime_policy import initialize_runtime_policy
from request_telemetry import dice_live_request_tags
from service_health import router as health_router
from supabase_cache import CachedSupabaseClient, SupabaseTTLCacheStore

RUNTIME_POLICY = initialize_runtime_policy(
    os.environ,
    lambda: load_dotenv(dotenv_path=".env.local", override=True),
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
RUNTIME_POLICY.require_safe_supabase_url(SUPABASE_URL)
if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_SERVICE_KEY is required")

logger = logging.getLogger(__name__)


def _is_scheduler_enabled() -> bool:
    return RUNTIME_POLICY.scheduler_enabled


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:8080", "http://127.0.0.1:8080"]
    configured = [
        origin.strip()
        for origin in os.getenv("CORS_EXTRA_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return list(dict.fromkeys([*defaults, *configured]))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Dice API starting")
    yield


app = FastAPI(title="Cozy Commons Dice API", lifespan=lifespan)
app.state.runtime_policy = RUNTIME_POLICY
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache_store = SupabaseTTLCacheStore(ttl_seconds=120)
app.state.supabase: Client = CachedSupabaseClient(
    create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY), cache_store=cache_store
)
app.state.supabase_admin: Client = CachedSupabaseClient(
    create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY), cache_store=cache_store
)
app.state.analytics_supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
app.state.readiness_supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
# Commons scene reads must not use the generic 120-second cache. Every command
# is fenced by the database version and the next GET must observe it promptly.
app.state.commons_supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@app.middleware("http")
async def log_dice_live_commands(request, call_next):
    tags = dice_live_request_tags(request.url.path, request.headers)
    if not tags:
        return await call_next(request)
    started = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        logging.getLogger("uvicorn.error").info(json.dumps({
            "event": "dice_live_command", "status_code": status,
            "duration_ms": round((perf_counter() - started) * 1000, 2), **tags,
        }))


@app.get("/")
def root():
    return {"service": "cozy-commons-dice", "status": "ok"}


app.include_router(health_router)
app.include_router(commons_router, prefix="/commons")
app.include_router(dice_router, prefix="/dice")
app.include_router(analytics_router, prefix="/track")
