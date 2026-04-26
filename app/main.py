"""FastAPI entrypoint for VC Brain.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import logging
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .db import close_pool, init_pool
from .routes import chat as chat_router
from .routes import entities
from .routes import harness as harness_router

log = logging.getLogger(__name__)

_UI_FILE = Path(__file__).parent.parent / "vcbrain.html"

# ── Simple in-process TTL cache for /brief/{name} ─────────────────────────────
_brief_cache: dict[str, tuple[dict, float]] = {}
_brief_cache_lock = threading.Lock()
_BRIEF_TTL_S = 300  # 5 minutes


def _brief_cache_get(key: str) -> dict | None:
    with _brief_cache_lock:
        entry = _brief_cache.get(key)
        if entry and time.time() - entry[1] < _BRIEF_TTL_S:
            return entry[0]
        if entry:
            del _brief_cache[key]
    return None


def _brief_cache_set(key: str, value: dict) -> None:
    with _brief_cache_lock:
        _brief_cache[key] = (value, time.time())


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()

    if not settings.anthropic_api_key:
        log.warning(
            "ANTHROPIC_API_KEY is not set — /brief/{name} and harness evolution will fail. "
            "Add ANTHROPIC_API_KEY to your .env file and restart."
        )

    # Restore any previous evolution state from disk
    from vcbrain_harness.evolution import load_persisted_state
    load_persisted_state()

    # Auto-start evolution if configured and API key is present
    if settings.harness_auto_run and settings.anthropic_api_key:
        from vcbrain_harness.evolution import get_state, start_evolution_thread
        if get_state()["status"] not in ("running", "done"):
            start_evolution_thread(max_iterations=settings.harness_max_iterations)

    yield
    close_pool()


app = FastAPI(
    title="VC Brain",
    description="Eastcoast Fund — structured fact graph, briefs, chat, and harness evolution.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def serve_ui() -> FileResponse:
    return FileResponse(_UI_FILE, media_type="text/html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "vc-brain"}


app.include_router(entities.router, tags=["entities"])
app.include_router(harness_router.router)
app.include_router(chat_router.router)


@app.get("/brief/{name}", tags=["briefs"])
async def generate_brief(name: str) -> dict:
    """Generate a Claude investment brief for a named entity.

    Requires ANTHROPIC_API_KEY in the environment.
    Results are cached for 5 minutes to avoid redundant API calls.
    """
    cached = _brief_cache_get(name)
    if cached is not None:
        return cached

    def _run() -> dict:
        from vcbrain_harness.harness import solve  # lazy: avoids import-time API key check
        raw = solve(name)
        return json.loads(raw)

    try:
        result = await run_in_threadpool(_run)
        _brief_cache_set(name, result)
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Missing environment variable: {exc}. Set ANTHROPIC_API_KEY.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
