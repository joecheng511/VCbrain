"""
VCbrain Layer 3 — Agent API

Thin FastAPI layer the UI calls. Wraps harness.solve() with harness versioning
and exposes evolution status from the PolyHarness workspace.

Endpoints:
  POST /agent/brief     { "company": str }  → { "brief": {...}, "harness_version": str, "score": float }
  GET  /agent/evolution                     → { "current_iter": int, "best_score": float, "improvement": str }
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="VCbrain Agent API", version="1.0.0")

WORKSPACE = Path(os.environ.get("PH_WORKSPACE", ".ph_workspace"))
HARNESS_DIR = Path(os.environ.get("HARNESS_DIR", "vcbrain_harness"))


# ── harness loader ───────────────────────────────────────────────────────────

def _load_solve():
    """Import solve() from the current best harness (applied or base)."""
    if str(HARNESS_DIR) not in sys.path:
        sys.path.insert(0, str(HARNESS_DIR))
    import importlib
    import harness as _h
    importlib.reload(_h)  # pick up ph apply changes without restart
    return _h.solve


def _current_harness_version() -> str:
    """Return the iteration label of the applied harness, or 'iter_0'."""
    applied_marker = WORKSPACE / "applied.json"
    if applied_marker.exists():
        data = json.loads(applied_marker.read_text())
        return data.get("iteration", "iter_0")
    return "iter_0"


# ── evolution status ─────────────────────────────────────────────────────────

def _parse_search_log() -> list[dict]:
    """Parse .ph_workspace/search.jsonl for iteration scores."""
    log_path = WORKSPACE / "search.jsonl"
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _evolution_status() -> dict:
    entries = _parse_search_log()
    if not entries:
        return {
            "current_iter": 0,
            "best_score": None,
            "baseline_score": None,
            "improvement": "No evolution runs yet",
        }

    scores = [e.get("score", 0) for e in entries if "score" in e]
    best = max(scores) if scores else 0.0
    baseline = scores[0] if scores else 0.0
    current_iter = len(entries)
    delta = best - baseline
    sign = "+" if delta >= 0 else ""

    return {
        "current_iter": current_iter,
        "best_score": round(best, 4),
        "baseline_score": round(baseline, 4),
        "improvement": f"{sign}{delta:.2f} since iter_0",
    }


# ── request / response models ────────────────────────────────────────────────

class BriefRequest(BaseModel):
    company: str


class BriefResponse(BaseModel):
    brief: dict
    harness_version: str
    score: float | None = None


class EvolutionResponse(BaseModel):
    current_iter: int
    best_score: float | None
    baseline_score: float | None
    improvement: str


# ── routes ───────────────────────────────────────────────────────────────────

@app.post("/agent/brief", response_model=BriefResponse)
async def agent_brief(req: BriefRequest):
    if not req.company.strip():
        raise HTTPException(status_code=400, detail="company name required")

    try:
        solve = _load_solve()
        raw = solve(req.company.strip())
        brief = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    version = _current_harness_version()
    entries = _parse_search_log()
    best_score = None
    if entries:
        scores = [e.get("score") for e in entries if "score" in e]
        best_score = max(scores) if scores else None

    return BriefResponse(brief=brief, harness_version=version, score=best_score)


@app.get("/agent/evolution", response_model=EvolutionResponse)
async def agent_evolution():
    status = _evolution_status()
    return EvolutionResponse(**status)


@app.get("/health")
async def health():
    return {"status": "ok", "workspace": str(WORKSPACE), "harness": str(HARNESS_DIR)}
