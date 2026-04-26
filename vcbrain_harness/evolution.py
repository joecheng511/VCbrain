"""
VCbrain native evolution engine — replaces PolyHarness.

How it works
------------
1. Load test cases from vcbrain_tasks/test_cases.json
2. Run solve() on every input using the current ANALYST_PROMPT
3. Score each result:
     - 0.40 pts  — verdict matches expected
     - 0.40 pts  — fraction of must_mention keywords found in the output
     - 0.20 pts  — fraction of must_not_hallucinate keywords NOT found
4. Send failures to Gemini asking it to rewrite the analyst prompt
5. Validate the new prompt and keep it in memory for the next iteration
6. Repeat for max_iterations; always keep the best-scoring prompt
7. Persist best prompt + state to vcbrain_tasks/evolution_state.json after each iteration
   (harness.py loads the saved prompt on startup — never written directly)

Usage
-----
    from vcbrain_harness.evolution import run_evolution
    run_evolution(max_iterations=5)            # blocking
    asyncio.create_task(run_evolution_async(5)) # non-blocking
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types as genai_types

# ── Paths ─────────────────────────────────────────────────────────────────────

_ROOT        = Path(__file__).parent.parent
_TEST_CASES  = _ROOT / "vcbrain_tasks" / "test_cases.json"
_STATE_FILE  = _ROOT / "vcbrain_tasks" / "evolution_state.json"

# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class IterationResult:
    iteration: int
    score: float
    case_scores: list[dict]
    failures: list[dict]
    prompt_used: str
    is_best: bool = False
    summary: str = ""
    elapsed_s: float = 0.0


@dataclass
class EvolutionState:
    status: str = "idle"           # idle | running | stopped | done | error
    current_iteration: int = 0
    max_iterations: int = 5
    best_score: float = 0.0
    best_prompt: str = ""
    iterations: list[IterationResult] = field(default_factory=list)
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    stop_requested: bool = False


# Singleton — shared between the FastAPI route and the background thread
_state = EvolutionState()
_lock  = threading.Lock()


def get_state() -> dict:
    with _lock:
        d = asdict(_state)
    # Drop the full prompt text from iterations to keep the response small
    for it in d.get("iterations", []):
        it.pop("prompt_used", None)
    return d


def request_stop() -> bool:
    """Ask the running loop to stop after the current iteration. Returns False if not running."""
    with _lock:
        if _state.status != "running":
            return False
        _state.stop_requested = True
    return True


def reset_state() -> None:
    """Clear evolution state. Raises RuntimeError if evolution is currently running."""
    with _lock:
        if _state.status == "running":
            raise RuntimeError("Evolution is running — wait for it to finish before resetting.")
        _state.status            = "idle"
        _state.current_iteration = 0
        _state.best_score        = 0.0
        _state.best_prompt       = ""
        _state.iterations        = []
        _state.error             = ""
        _state.started_at        = 0.0
        _state.finished_at       = 0.0
        _state.stop_requested    = False
    _save_state()


# ── Scoring ───────────────────────────────────────────────────────────────────

_VERDICT_WEIGHT      = 0.40
_MENTION_WEIGHT      = 0.40
_HALLUCINATE_WEIGHT  = 0.20

VERDICT_ORDER = ["fail", "borderline", "pass", "strong_pass"]


def _verdict_score(actual: str, expected: str) -> float:
    """Full credit for exact match; partial credit for one step off."""
    if actual == expected:
        return 1.0
    ai = VERDICT_ORDER.index(actual)   if actual   in VERDICT_ORDER else -1
    ei = VERDICT_ORDER.index(expected) if expected in VERDICT_ORDER else -1
    if ai >= 0 and ei >= 0 and abs(ai - ei) == 1:
        return 0.5
    return 0.0


def score_result(brief: dict, expected: dict) -> tuple[float, list[str]]:
    """Return (0-1 score, list of failure reasons)."""
    failures: list[str] = []
    total = 0.0

    # ── Verdict ──────────────────────────────────────────────────────────────
    actual_verdict   = brief.get("verdict", "")
    expected_verdict = expected.get("verdict", "")
    v_score = _verdict_score(actual_verdict, expected_verdict)
    total  += v_score * _VERDICT_WEIGHT
    if v_score < 1.0:
        failures.append(
            f"verdict '{actual_verdict}' ≠ expected '{expected_verdict}'"
        )

    # ── Must-mention ─────────────────────────────────────────────────────────
    brief_text = json.dumps(brief).lower()
    must_mention = expected.get("must_mention", [])
    if must_mention:
        hits = sum(1 for kw in must_mention if kw.lower() in brief_text)
        m_score = hits / len(must_mention)
        total  += m_score * _MENTION_WEIGHT
        missed  = [kw for kw in must_mention if kw.lower() not in brief_text]
        if missed:
            failures.append(f"missing keywords: {missed}")
    else:
        total += _MENTION_WEIGHT  # full credit if no requirement

    # ── Must-not-hallucinate ──────────────────────────────────────────────────
    must_not = expected.get("must_not_hallucinate", [])
    if must_not:
        clean   = sum(1 for kw in must_not if kw.lower() not in brief_text)
        h_score = clean / len(must_not)
        total  += h_score * _HALLUCINATE_WEIGHT
        found   = [kw for kw in must_not if kw.lower() in brief_text]
        if found:
            failures.append(f"hallucinated: {found}")
    else:
        total += _HALLUCINATE_WEIGHT

    return round(total, 4), failures


def _read_current_prompt() -> str:
    """Return the current best prompt from the harness module."""
    from vcbrain_harness.harness import _load_prompt  # avoid circular at module level
    return _load_prompt()




# ── Claude prompt-improvement call ────────────────────────────────────────────

_IMPROVER_SYSTEM = """\
You are an expert AI prompt engineer. You will receive:
- The current prompt used by a VC analyst AI agent
- The test cases it failed, with expected vs actual output

Your job: rewrite the prompt so it fixes the failures while preserving what already works.

Rules:
- Keep the same JSON output format requirement exactly
- Keep the verdict definitions (strong_pass | pass | borderline | fail) exactly
- Keep the placeholder variables {facts_block} and {conflicts_block} exactly as-is
- The prompt must end with the JSON template block unchanged
- Return ONLY the new prompt text — no explanation, no markdown fences
"""


def _improve_prompt(current_prompt: str, failures: list[dict], client: genai.Client) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    failure_text = "\n".join(
        f"Company: {f['input']}\n"
        f"  Expected verdict: {f['expected_verdict']}\n"
        f"  Got verdict:      {f['actual_verdict']}\n"
        f"  Reasons:          {'; '.join(f['reasons'])}\n"
        for f in failures
    )

    user_msg = f"""\
Current prompt:
\"\"\"
{current_prompt}
\"\"\"

Failed test cases:
{failure_text}

Rewrite the prompt to fix these failures.
"""

    response = client.models.generate_content(
        model=model,
        contents=user_msg,
        config=genai_types.GenerateContentConfig(
            system_instruction=_IMPROVER_SYSTEM,
            max_output_tokens=2048,
        ),
    )
    return response.text.strip()


# ── Single iteration ──────────────────────────────────────────────────────────

def _run_one_iteration(
    iteration: int,
    prompt: str,
    test_cases: list[dict],
    client: genai.Client,
) -> IterationResult:
    from vcbrain_harness.harness import solve  # reimport each iteration so prompt change is live

    t0 = time.time()
    case_scores: list[dict] = []
    failures:    list[dict] = []

    for tc in test_cases:
        company = tc["input"]
        expected = tc["expected"]
        try:
            raw  = solve(company)
            brief = json.loads(raw)
            score, reasons = score_result(brief, expected)
        except Exception as exc:
            score   = 0.0
            reasons = [f"exception: {exc}"]
            brief   = {}

        case_scores.append({"input": company, "score": score})

        if score < 1.0:
            failures.append({
                "input":            company,
                "expected_verdict": expected.get("verdict", ""),
                "actual_verdict":   brief.get("verdict", "ERROR"),
                "reasons":          reasons,
            })

    overall = round(sum(c["score"] for c in case_scores) / len(case_scores), 4) if case_scores else 0.0
    summary = (
        f"{len(test_cases) - len(failures)}/{len(test_cases)} passed"
        f" · {len(failures)} failure{'s' if len(failures) != 1 else ''}"
    )

    return IterationResult(
        iteration   = iteration,
        score       = overall,
        case_scores = case_scores,
        failures    = failures,
        prompt_used = prompt,
        summary     = summary,
        elapsed_s   = round(time.time() - t0, 1),
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_state() -> None:
    with _lock:
        data = asdict(_state)
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_persisted_state() -> None:
    """On server start, restore the last evolution state if it exists."""
    global _state
    if not _STATE_FILE.exists():
        return
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        with _lock:
            _state.status            = data.get("status", "idle")
            _state.current_iteration = data.get("current_iteration", 0)
            _state.max_iterations    = data.get("max_iterations", 5)
            _state.best_score        = data.get("best_score", 0.0)
            _state.best_prompt       = data.get("best_prompt", "")
            _state.error             = data.get("error", "")
            _state.started_at        = data.get("started_at", 0.0)
            _state.finished_at       = data.get("finished_at", 0.0)
            _state.iterations        = [IterationResult(**it) for it in data.get("iterations", [])]
            # If it was "running" when server died, mark it idle
            if _state.status == "running":
                _state.status = "idle"
    except Exception:
        pass  # corrupted state — start fresh


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_evolution(max_iterations: int = 5) -> None:
    """Blocking evolution loop. Call from a thread."""
    global _state

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        with _lock:
            _state.status = "error"
            _state.error  = "GEMINI_API_KEY is not set"
        _save_state()
        return

    if not _TEST_CASES.exists():
        with _lock:
            _state.status = "error"
            _state.error  = f"Test cases not found at {_TEST_CASES}"
        _save_state()
        return

    test_cases = json.loads(_TEST_CASES.read_text(encoding="utf-8"))
    client     = genai.Client(api_key=api_key)

    with _lock:
        _state.status            = "running"
        _state.max_iterations    = max_iterations
        _state.current_iteration = 0
        _state.best_score        = 0.0
        _state.iterations        = []
        _state.error             = ""
        _state.started_at        = time.time()
        _state.finished_at       = 0.0
        _state.stop_requested    = False

    current_prompt = _read_current_prompt()
    best_prompt    = current_prompt
    best_score     = 0.0

    try:
        for i in range(max_iterations):
            with _lock:
                _state.current_iteration = i + 1
            _save_state()

            result = _run_one_iteration(i, current_prompt, test_cases, client)

            if result.score >= best_score:
                best_score  = result.score
                best_prompt = current_prompt
                result.is_best = True

            with _lock:
                _state.best_score  = best_score
                _state.best_prompt = best_prompt
                _state.iterations.append(result)
            _save_state()

            # Stop early if perfect score or user requested stop
            with _lock:
                should_stop = _state.stop_requested
            if result.score >= 1.0 or should_stop:
                if should_stop:
                    with _lock:
                        _state.status = "stopped"
                break

            # Ask Gemini to improve the prompt for the next iteration
            if result.failures and i < max_iterations - 1:
                try:
                    improved = _improve_prompt(current_prompt, result.failures, client)
                    # Validate it still contains the required placeholders
                    if "{facts_block}" in improved and "{conflicts_block}" in improved:
                        current_prompt = improved
                except Exception as exc:
                    # If improvement fails, keep current prompt and continue
                    with _lock:
                        _state.iterations[-1].summary += f" (improve failed: {exc})"

        with _lock:
            if _state.status != "stopped":
                _state.status = "done"
            _state.best_score  = best_score
            _state.best_prompt = best_prompt
            _state.finished_at = time.time()

    except Exception as exc:
        with _lock:
            _state.status = "error"
            _state.error  = str(exc)

    _save_state()


def start_evolution_thread(max_iterations: int = 5) -> threading.Thread:
    """Launch the evolution loop in a daemon thread and return it."""
    with _lock:
        if _state.status == "running":
            raise RuntimeError("Evolution is already running")

    t = threading.Thread(
        target=run_evolution,
        args=(max_iterations,),
        daemon=True,
        name="vcbrain-evolution",
    )
    t.start()
    return t
