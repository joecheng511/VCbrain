"""FastAPI entrypoint for the DealBrain context base.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .db import close_pool, init_pool
from .routes import entities
from .routes import harness as harness_router

_UI_FILE = Path(__file__).parent.parent / "vcbrain.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()

    # Restore any previous evolution state from disk
    from vcbrain_harness.evolution import load_persisted_state
    load_persisted_state()

    # Auto-start evolution if configured and API key is present
    if settings.harness_auto_run and settings.gemini_api_key:
        from vcbrain_harness.evolution import get_state, start_evolution_thread
        if get_state()["status"] not in ("running", "done"):
            start_evolution_thread(max_iterations=settings.harness_max_iterations)

    yield
    close_pool()


app = FastAPI(
    title="DealBrain Context Base",
    description="Layer 2: structured fact graph with provenance.",
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
    return {"status": "ok", "service": "dealbrain"}


app.include_router(entities.router, tags=["entities"])
app.include_router(harness_router.router)


@app.get("/brief/{name}", tags=["briefs"])
async def generate_brief(name: str) -> dict:
    """Generate a Gemini investment brief for a named entity.

    Requires GEMINI_API_KEY in the environment.
    Calls GET /entity/{name} internally via the harness, then Gemini.
    """
    def _run() -> dict:
        from vcbrain_harness.harness import solve  # lazy: avoids import-time API key check
        raw = solve(name)
        return json.loads(raw)

    try:
        return await run_in_threadpool(_run)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Missing environment variable: {exc}. Set GEMINI_API_KEY.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
