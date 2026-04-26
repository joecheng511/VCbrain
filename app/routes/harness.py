"""Harness evolution endpoints.

POST /harness/run?max_iterations=5   — start evolution (returns 409 if already running)
GET  /harness/status                 — current state + iteration history
POST /harness/reset                  — clear state and revert to baseline prompt
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/harness", tags=["harness"])


@router.post("/run")
def run_harness(
    max_iterations: int = Query(5, ge=1, le=20, description="Number of evolution iterations"),
) -> dict:
    """Start the harness evolution loop in a background thread."""
    from vcbrain_harness.evolution import get_state, start_evolution_thread

    state = get_state()
    if state["status"] == "running":
        raise HTTPException(status_code=409, detail="Evolution is already running.")

    try:
        start_evolution_thread(max_iterations=max_iterations)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"started": True, "max_iterations": max_iterations}


@router.get("/status")
def harness_status() -> dict:
    """Return the current evolution state and all iteration results."""
    from vcbrain_harness.evolution import get_state
    return get_state()


@router.post("/stop")
def stop_harness() -> dict:
    """Request the running evolution loop to stop after the current iteration."""
    from vcbrain_harness.evolution import request_stop

    stopped = request_stop()
    if not stopped:
        raise HTTPException(status_code=409, detail="Evolution is not currently running.")
    return {"stop_requested": True, "message": "Will stop after the current iteration completes."}


@router.post("/reset")
def reset_harness() -> dict:
    """Stop any running evolution and clear state (does not revert harness.py prompt)."""
    from vcbrain_harness.evolution import _state, _lock, _save_state
    import time

    with _lock:
        if _state.status == "running":
            raise HTTPException(
                status_code=409,
                detail="Evolution is running — wait for it to finish before resetting.",
            )
        _state.status            = "idle"
        _state.current_iteration = 0
        _state.best_score        = 0.0
        _state.best_prompt       = ""
        _state.iterations        = []
        _state.error             = ""
        _state.started_at        = 0.0
        _state.finished_at       = 0.0

    _save_state()
    return {"reset": True}
