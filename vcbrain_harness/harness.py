"""
VCbrain Layer 3 harness — v1.

solve(company_name) -> JSON string:
  1. Fetches entity facts from GET /entity/{name}   (Layer 2)
  2. Fetches open conflicts from GET /conflicts?entity={name}  (Layer 2)
  3. Sends merged context to Gemini, returns a structured VC investment brief.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from google import genai

LAYER2_BASE = os.environ.get("LAYER2_BASE_URL", "http://localhost:8000")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

_BASE_PROMPT = """\
You are a senior VC analyst at a top-tier venture fund. You have been given structured \
data about a company pulled from the fund's internal fact graph. Your job is to produce \
a concise investment brief and a clear investment verdict with supporting reasons.

## Source Data
{facts_block}

{conflicts_block}

## Instructions
- Base every claim strictly on the source data provided above.
- Do NOT hallucinate metrics, names, or events not present in the data.
- If data is sparse, say so and still provide a best-effort assessment.
- For the verdict, use ONLY one of: strong_pass, pass, borderline, fail.

## Response Format
Reply with ONLY a JSON object — no markdown, no explanation outside the JSON:

{{
  "verdict": "<strong_pass|pass|borderline|fail>",
  "one_line_summary": "<one sentence summary of the investment opportunity>",
  "key_strengths": ["<strength 1>", "<strength 2>"],
  "red_flags": ["<flag 1>", "<flag 2>"],
  "questions_for_founder": ["<question 1>", "<question 2>", "<question 3>"],
  "confidence": <0.0-1.0 float reflecting data completeness>
}}"""


def _load_prompt() -> str:
    """Return the evolved prompt if saved and valid, otherwise the base prompt."""
    try:
        import pathlib, json as _json
        state_file = pathlib.Path(__file__).parent.parent / "vcbrain_tasks" / "evolution_state.json"
        if state_file.exists():
            state = _json.loads(state_file.read_text(encoding="utf-8"))
            evolved = state.get("best_prompt", "").strip()
            if evolved and "{facts_block}" in evolved and "{conflicts_block}" in evolved:
                # Validate that .format() won't throw KeyError on stray { } characters
                evolved.format(facts_block="", conflicts_block="")
                return evolved
    except Exception:
        pass
    return _BASE_PROMPT


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError(f"Entity not found at {url}") from exc
        raise RuntimeError(f"Layer 2 HTTP {exc.code}: {url}") from exc
    except Exception as exc:
        raise RuntimeError(f"Layer 2 API unavailable ({url}): {exc}") from exc


def _fetch_entity(company_name: str) -> dict:
    url = f"{LAYER2_BASE}/entity/{urllib.parse.quote(company_name)}"
    return _get_json(url)  # type: ignore[return-value]


def _fetch_conflicts(company_name: str) -> list[dict]:
    """Call GET /conflicts?entity={name} to get richer, deduplicated conflict records."""
    url = f"{LAYER2_BASE}/conflicts?entity={urllib.parse.quote(company_name)}"
    try:
        result = _get_json(url)
        return result if isinstance(result, list) else []
    except Exception:
        # /conflicts is an enhancement; fall back gracefully if endpoint unreachable
        return []


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_facts_block(data: dict) -> str:
    lines = [f"Company: {data['entity']['name']} (type: {data['entity']['type']})"]
    lines.append("\nFacts:")
    for f in data.get("facts", []):
        src = f.get("source")
        src_label = src["type"] if src else "unknown"
        flag = " [LOW CONFIDENCE]" if f["confidence"] < 0.7 else ""
        lines.append(
            f"  - {f['attribute']}: {f['value']} "
            f"(confidence={f['confidence']}, source={src_label}){flag}"
        )
    return "\n".join(lines)


def _build_conflicts_block(entity_conflicts: list[dict], api_conflicts: list[dict]) -> str:
    """
    Merge conflicts from two sources:
      - entity_conflicts: inline [{attribute, value_a, value_b, status}] from /entity/{name}
      - api_conflicts:    [{conflict_id, entity_name, attribute, value_a, value_b, status}]
                          from /conflicts?entity={name}

    Deduplicate by (attribute, value_a, value_b) and keep open ones.
    """
    seen: set[tuple] = set()
    open_conflicts: list[dict] = []

    for src in (entity_conflicts, api_conflicts):
        for c in src:
            if c.get("status") != "open":
                continue
            key = (c["attribute"], str(c["value_a"]), str(c["value_b"]))
            rev = (c["attribute"], str(c["value_b"]), str(c["value_a"]))
            if key in seen or rev in seen:
                continue
            seen.add(key)
            open_conflicts.append(c)

    if not open_conflicts:
        return ""

    lines = ["\nOpen Conflicts (require analyst judgment):"]
    for c in open_conflicts:
        src_a = c.get("source_a") or "crm"
        src_b = c.get("source_b") or "email"
        lines.append(
            f"  - {c['attribute']}: '{c['value_a']}' ({src_a}) vs '{c['value_b']}' ({src_b})"
        )
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def solve(input_data: str) -> str:
    """Receive company name, return JSON brief string."""
    company_name = input_data.strip()

    entity_data = _fetch_entity(company_name)
    api_conflicts = _fetch_conflicts(company_name)

    facts_block = _build_facts_block(entity_data)
    conflicts_block = _build_conflicts_block(
        entity_data.get("conflicts", []),
        api_conflicts,
    )

    # Reload each call so an evolved prompt from evolution_state.json is picked up
    # without requiring a server restart.
    prompt = _load_prompt().format(
        facts_block=facts_block,
        conflicts_block=conflicts_block,
    )

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    raw = response.text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    brief = json.loads(raw)
    return json.dumps(brief)
