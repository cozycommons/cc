import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import Client, create_client

from analytics import router as analytics_router
from dice.routes import router as dice_router
from runtime_policy import initialize_runtime_policy
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


@app.get("/")
def root():
    return {"service": "cozy-commons-dice", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(dice_router, prefix="/dice")
app.include_router(analytics_router, prefix="/track")
