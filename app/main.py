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

from .db import close_pool, init_pool
from .routes import entities

_UI_FILE = Path(__file__).parent.parent / "vcbrain.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    yield
    close_pool()


app = FastAPI(
    title="DealBrain Context Base",
    description="Layer 2: structured fact graph with provenance.",
    version="0.1.0",
    lifespan=lifespan,
)

from .config import settings as _settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
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


@app.get("/brief/{name}", tags=["briefs"])
async def generate_brief(name: str) -> dict:
    """Generate a Claude investment brief for a named entity.

    Requires ANTHROPIC_API_KEY in the environment.
    Calls GET /entity/{name} internally via the harness, then Claude.
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
            detail=f"Missing environment variable: {exc}. Set ANTHROPIC_API_KEY.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
