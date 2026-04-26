"""POST /chat — Gemini-powered intent router.

Flow
----
1. Classify the user message with a cheap Gemini call (~80 tokens).
2. Fetch the relevant data from the database.
3. Return structured JSON; the frontend renders it as HTML.

Intents
-------
company   – facts about a named company
brief     – full Gemini investment brief for a named company
sector    – portfolio sector-exposure breakdown
conflicts – open conflict queue summary
harness   – evolution engine status
stats     – portfolio-wide counts
unknown   – fallback help message
"""
from __future__ import annotations

import json
import os
import time

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..db import get_dict_cursor

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Intent classifier ─────────────────────────────────────────────────────────

_CLASSIFIER_SYSTEM = """\
You are a routing classifier for a VC fund AI assistant called VCbrain.
Classify the user question into EXACTLY ONE intent.

Intents:
- company  : user is asking about facts, details, or information on a SPECIFIC named company
- brief    : user wants an investment analysis, verdict, or deep brief on a SPECIFIC company
- sector   : user is asking about sector exposure, portfolio breakdown, or industry data
- conflicts: user is asking about data conflicts, discrepancies, or items needing review
- harness  : user is asking about AI / harness evolution status or improvement scores
- stats    : user wants portfolio-wide counts (companies, facts, ARR, etc.)
- unknown  : anything else

Rules:
- Only use "company" or "brief" if the message contains a clearly identifiable company name.
- Generic phrases like "the fund", "our portfolio", "our investments" are NOT company names.
- If the question mentions a sector keyword (healthcare, fintech, SaaS, etc.) use "sector".

Reply with JSON only — no markdown, no explanation:
{"intent": "company|brief|sector|conflicts|harness|stats|unknown", "entity": "<company name or null>", "sector": "<sector keyword or null>"}
"""


def _classify(message: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"intent": "unknown", "entity": None, "sector": None}

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    model  = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    resp = client.models.generate_content(
        model=model,
        contents=f'User question: "{message}"',
        config=genai_types.GenerateContentConfig(
            system_instruction=_CLASSIFIER_SYSTEM,
            max_output_tokens=80,
        ),
    )
    raw = resp.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _fetch_company(entity_name: str) -> dict:
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT id, type, name FROM entities
            WHERE canonical_name = lower(%(name)s)
            ORDER BY created_at ASC LIMIT 1
        """, {"name": entity_name})
        ent = cur.fetchone()

    if ent is None:
        return {"intent": "not_found", "queried": entity_name}

    eid = ent["id"]
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT attribute, value, confidence
            FROM facts
            WHERE entity_id = %(eid)s
            ORDER BY confidence DESC, attribute ASC
        """, {"eid": eid})
        facts = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(DISTINCT c.id) AS n
            FROM conflicts c
            JOIN facts f ON c.fact_a_id = f.id OR c.fact_b_id = f.id
            WHERE f.entity_id = %(eid)s AND c.status = 'open'
        """, {"eid": eid})
        conflict_count = int(cur.fetchone()["n"])

    return {
        "intent":         "company",
        "entity":         dict(ent),
        "facts":          facts,
        "conflict_count": conflict_count,
    }


def _fetch_brief(entity_name: str) -> dict:
    """Generate a Gemini investment brief (re-uses harness.solve)."""
    try:
        from vcbrain_harness.harness import solve
        raw = solve(entity_name)
        brief = json.loads(raw)
        brief["intent"]  = "brief"
        brief["entity_name"] = entity_name
        return brief
    except LookupError:
        return {"intent": "not_found", "queried": entity_name}
    except Exception as exc:
        return {"intent": "error", "message": str(exc)}


def _fetch_sector(sector_filter: str | None) -> dict:
    with get_dict_cursor() as cur:
        cur.execute("""
            WITH sector_facts AS (
                SELECT entity_id,
                    MAX(CASE WHEN attribute='sector'  THEN value END) AS sector,
                    MAX(CASE WHEN attribute='arr_eur' THEN value::numeric END) AS arr_eur
                FROM facts GROUP BY entity_id
            ),
            conflict_counts AS (
                SELECT entity_id, COUNT(DISTINCT c.id) AS open_conflicts
                FROM (
                    SELECT f.entity_id, c.id FROM conflicts c
                    JOIN facts f ON c.fact_a_id = f.id WHERE c.status='open'
                    UNION ALL
                    SELECT f.entity_id, c.id FROM conflicts c
                    JOIN facts f ON c.fact_b_id = f.id WHERE c.status='open'
                ) s GROUP BY entity_id
            )
            SELECT COALESCE(sf.sector,'Unknown') AS sector,
                   COUNT(DISTINCT e.id)          AS company_count,
                   ROUND(SUM(sf.arr_eur)/1e6, 2) AS total_arr_m,
                   COALESCE(SUM(cc.open_conflicts),0) AS open_conflicts
            FROM entities e
            LEFT JOIN sector_facts    sf ON sf.entity_id = e.id
            LEFT JOIN conflict_counts cc ON cc.entity_id = e.id
            GROUP BY COALESCE(sf.sector,'Unknown')
            ORDER BY company_count DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]

    for r in rows:
        r["company_count"]  = int(r["company_count"])
        r["total_arr_m"]    = float(r["total_arr_m"]) if r["total_arr_m"] else 0.0
        r["open_conflicts"] = int(r["open_conflicts"])

    return {"intent": "sector", "sectors": rows, "filter": sector_filter}


def _fetch_conflicts() -> dict:
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT c.id::text AS conflict_id, e.name AS entity_name,
                   f1.attribute, f1.value AS value_a, f2.value AS value_b,
                   c.status::text AS status
            FROM conflicts c
            JOIN facts f1 ON c.fact_a_id = f1.id
            JOIN facts f2 ON c.fact_b_id = f2.id
            JOIN entities e ON f1.entity_id = e.id
            WHERE c.status = 'open'
            ORDER BY c.created_at DESC LIMIT 200
        """)
        rows = [dict(r) for r in cur.fetchall()]
    return {"intent": "conflicts", "conflicts": rows, "open_count": len(rows)}


def _fetch_harness() -> dict:
    from vcbrain_harness.evolution import get_state
    state = get_state()
    return {
        "intent":        "harness",
        "status":        state.get("status"),
        "best_score":    state.get("best_score", 0.0),
        "iterations":    len(state.get("iterations", [])),
        "max_iterations":state.get("max_iterations", 5),
        "current_iter":  state.get("current_iteration", 0),
    }


def _fetch_stats() -> dict:
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT (SELECT COUNT(*) FROM entities) AS entity_count,
                   (SELECT COUNT(*) FROM facts)    AS fact_count,
                   (SELECT COUNT(*) FROM conflicts WHERE status='open') AS open_conflicts
        """)
        row = dict(cur.fetchone())
    return {
        "intent":          "stats",
        "entity_count":    int(row["entity_count"]),
        "fact_count":      int(row["fact_count"]),
        "open_conflicts":  int(row["open_conflicts"]),
    }


# ── Route ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@router.post("")
async def chat(body: ChatRequest) -> dict:
    """Classify the user message and return structured data for the frontend to render."""
    msg = body.message.strip()

    def _handle() -> dict:
        try:
            clf = _classify(msg)
        except Exception:
            clf = {"intent": "unknown", "entity": None, "sector": None}

        intent = clf.get("intent", "unknown")
        entity = clf.get("entity")
        sector = clf.get("sector")

        if intent == "company" and entity:
            return _fetch_company(entity)
        if intent == "brief" and entity:
            return _fetch_brief(entity)
        if intent == "sector":
            return _fetch_sector(sector)
        if intent == "conflicts":
            return _fetch_conflicts()
        if intent == "harness":
            return _fetch_harness()
        if intent == "stats":
            return _fetch_stats()

        # unknown — return the classified intent so the frontend can show a help message
        return {"intent": "unknown"}

    return await run_in_threadpool(_handle)
