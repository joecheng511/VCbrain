"""POST /chat — Claude-powered intent router with fund-context synthesis.

Flow
----
1. Classify user message with a small Claude call.
2. Fetch structured data from PostgreSQL (pre-aggregated, not raw rows).
3. For company / comparison / conflict / general intents: synthesize with Claude
   using enriched context + fund profile.
4. For sector / stats / harness: build the HTML response in Python.

Every handler returns {"intent": "...", "text": "<HTML>", ...extra}
so the frontend only needs to render data.text.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..db import get_dict_cursor
from vcbrain_harness.claude_util import chat_text, make_client

router = APIRouter(prefix="/chat", tags=["chat"])

# ── Fund context — prepended to every synthesis prompt ────────────────────────

_FUND_CONTEXT = """\
## Eastcoast Fund — Context
- Stage: Pre-Seed and Seed
- Ticket size: €150,000 – €250,000
- Geography mandate: East Germany (Berlin, Leipzig, Dresden, Erfurt region)
- Team: Johannes (Senior Partner), Franz (Senior Partner), Claire (Investment Manager)
- Thesis: Impact-focused; aligned with UN SDGs 3 (Health), 11 (Sustainable Cities), 15 (Ecosystems)
- Model preference: B2B or B2B2C; €50K–€2M ARR at entry; strong founding team required
"""

# ── Claude helpers ────────────────────────────────────────────────────────────

def _claude(client, system_instruction: str, user_content: str, max_tokens: int = 400) -> str:
    """Single Claude Messages API call."""
    return chat_text(client, system=system_instruction, user=user_content, max_tokens=max_tokens)


_SYNTHESIS_SYSTEM = f"""\
{_FUND_CONTEXT}
You are an investment analyst assistant for Eastcoast Fund.
Answer concisely and specifically using the provided data.
Format: plain sentences with <strong> for key numbers/names, <br><br> between paragraphs.
No markdown. Max 150 words. Never make up data not in the provided context.
"""

# ── Intent classifier ─────────────────────────────────────────────────────────

_CLASSIFIER_SYSTEM = """\
You are a routing classifier for VC Brain, a VC fund AI assistant.
Classify the user question into EXACTLY ONE intent.

Intents:
- company    : asking about facts or details of ONE specific named company
- brief      : asking for investment analysis, verdict, or deep dive on ONE company
- comparison : asking to compare or contrast TWO specific named companies
- sector     : asking about sector/industry exposure, portfolio breakdown, or vertical analysis
- conflicts  : asking about data conflicts, discrepancies, or items needing review
- harness    : asking about AI/harness evolution status or improvement scores
- stats      : asking for portfolio-wide counts, overall fund status/health/overview, or general "state of the fund" questions
- general    : any other analytical question about the fund, founders, rankings, trends, best/worst performers, team, strategy — anything that requires reasoning over fund data but doesn't fit the above
- unknown    : completely off-topic questions unrelated to the fund or portfolio

Rules:
- Only use "company", "brief", or "comparison" when a SPECIFIC company name appears.
- "the fund", "our portfolio", "our investments" are NOT company names.
- Sector keywords (healthcare, fintech, SaaS, B2B, etc.) → "sector".
- For "comparison", extract BOTH company names into entity and entity2.
- Prefer "general" over "unknown" whenever the question is fund-related.

Reply with JSON only — no markdown:
{"intent": "...", "entity": "<name or null>", "entity2": "<second name or null>", "sector": "<keyword or null>"}
"""


_EMPTY_CLASSIFY = {"intent": "unknown", "entity": None, "entity2": None, "sector": None}


def _classify(client, message: str) -> dict:
    raw = _claude(
        client,
        _CLASSIFIER_SYSTEM,
        f"User question: {message!r}",
        max_tokens=256,
    )
    if not raw:
        return _EMPTY_CLASSIFY
    # Strip optional ```json ... ``` fences the model sometimes adds
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Truncated JSON: extract intent field with regex as fallback
        m = re.search(r'"intent"\s*:\s*"([^"]+)"', raw)
        if not m:
            return _EMPTY_CLASSIFY
        intent = m.group(1)
        entity  = (re.search(r'"entity"\s*:\s*"([^"]+)"', raw) or [None, None])[1]
        entity2 = (re.search(r'"entity2"\s*:\s*"([^"]+)"', raw) or [None, None])[1]
        sector  = (re.search(r'"sector"\s*:\s*"([^"]+)"', raw) or [None, None])[1]
        return {"intent": intent, "entity": entity, "entity2": entity2, "sector": sector}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_entity(name: str) -> tuple[dict | None, list[dict], list[dict]]:
    """Return (entity_row, facts, conflicts) or (None, [], [])."""
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT id, type, name FROM entities
            WHERE canonical_name = lower(%(name)s)
            ORDER BY created_at ASC LIMIT 1
        """, {"name": name})
        ent = cur.fetchone()

    if ent is None:
        return None, [], []

    eid = ent["id"]
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT f.attribute, f.value, f.confidence,
                   COALESCE(s.type::text, 'unknown') AS source_type
            FROM facts f
            LEFT JOIN sources s ON f.source_id = s.id
            WHERE f.entity_id = %(eid)s
            ORDER BY f.confidence DESC, f.attribute ASC
        """, {"eid": eid})
        facts = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT f1.attribute,
                   f1.value AS value_a, f2.value AS value_b,
                   COALESCE(s1.type::text,'unknown') AS source_a,
                   COALESCE(s2.type::text,'unknown') AS source_b,
                   c.status::text AS status
            FROM conflicts c
            JOIN facts f1 ON c.fact_a_id = f1.id
            JOIN facts f2 ON c.fact_b_id = f2.id
            LEFT JOIN sources s1 ON f1.source_id = s1.id
            LEFT JOIN sources s2 ON f2.source_id = s2.id
            WHERE (f1.entity_id = %(eid)s OR f2.entity_id = %(eid)s)
              AND c.status = 'open'
            ORDER BY c.created_at DESC
        """, {"eid": eid})
        conflicts = [dict(r) for r in cur.fetchall()]

    return dict(ent), facts, conflicts


def _facts_to_briefing(facts: list[dict]) -> str:
    """Group facts by source type so Gemini sees 'CRM says X, email says Y'."""
    by_source: dict[str, list[str]] = defaultdict(list)
    for f in facts:
        val = f["value"]
        attr = f["attribute"].replace("_", " ")
        conf = f["confidence"]
        flag = " [LOW CONFIDENCE]" if conf < 0.7 else ""
        by_source[f["source_type"]].append(f"{attr}: {val}{flag}")

    lines = []
    for src, items in sorted(by_source.items()):
        lines.append(f"Source — {src}:")
        lines.extend(f"  • {item}" for item in items)
    return "\n".join(lines) if lines else "No facts on record."


def _conflicts_to_briefing(conflicts: list[dict]) -> str:
    """Annotate conflicts with ARR delta % where relevant."""
    if not conflicts:
        return "No open conflicts."

    lines = ["Open conflicts requiring analyst review:"]
    for c in conflicts:
        attr = c["attribute"].replace("_", " ")
        delta = ""
        # For numeric attributes compute percentage delta
        try:
            a, b = float(c["value_a"]), float(c["value_b"])
            if b != 0:
                pct = abs(a - b) / max(a, b) * 100
                delta = f" ({pct:.0f}% delta)"
        except (ValueError, TypeError):
            pass
        lines.append(
            f"  • {attr}: {c['source_a']} says '{c['value_a']}'"
            f" vs {c['source_b']} says '{c['value_b']}'{delta}"
        )
    return "\n".join(lines)


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_company(client, entity_name: str, user_message: str) -> dict:
    ent, facts, conflicts = _load_entity(entity_name)
    if ent is None:
        return {
            "intent": "not_found",
            "text": f"I don't have <strong>{entity_name}</strong> in the fact graph. "
                    "Try the exact company name.",
        }

    facts_block     = _facts_to_briefing(facts)
    conflicts_block = _conflicts_to_briefing(conflicts)

    user_prompt = f"""\
Company: {ent['name']} (type: {ent['type']})

{facts_block}

{conflicts_block}

User question: "{user_message}"
"""
    text = _claude(client, _SYNTHESIS_SYSTEM, user_prompt)
    return {"intent": "company", "entity": ent["name"], "text": text}


def _handle_brief(entity_name: str) -> dict:
    """Full investment brief — re-uses harness.solve for consistency."""
    try:
        from vcbrain_harness.harness import solve
        brief = json.loads(solve(entity_name))
        verdict = brief.get("verdict", "")
        col_map = {"strong_pass": "var(--green)", "pass": "var(--green)",
                   "borderline": "var(--amber)", "fail": "var(--red)"}
        col = col_map.get(verdict, "var(--muted2)")
        label = verdict.replace("_", " ").upper()
        red_flags = "".join(
            f'<div style="color:var(--red);margin-top:4px">⚑ {f}</div>'
            for f in (brief.get("red_flags") or [])
        )
        questions = "".join(
            f'<div style="color:var(--muted);margin-top:4px">? {q}</div>'
            for q in (brief.get("questions_for_founder") or [])[:2]
        )
        text = (
            f'<strong>{entity_name}</strong> — '
            f'<span style="font-family:var(--mono);font-size:10px;color:{col}">{label}</span>'
            f'<br><br>{brief.get("one_line_summary","")}'
            f'{red_flags}{questions}'
        )
        return {"intent": "brief", "text": text}
    except LookupError:
        return {"intent": "not_found",
                "text": f"<strong>{entity_name}</strong> not found in the fact graph."}
    except Exception as exc:
        return {"intent": "error",
                "text": f"Brief generation failed: {exc}. Check ANTHROPIC_API_KEY."}


def _handle_comparison(client, entity_a: str, entity_b: str, user_message: str) -> dict:
    ent_a, facts_a, conf_a = _load_entity(entity_a)
    ent_b, facts_b, conf_b = _load_entity(entity_b)

    if ent_a is None and ent_b is None:
        return {"intent": "not_found",
                "text": f"Neither <strong>{entity_a}</strong> nor <strong>{entity_b}</strong> found."}
    if ent_a is None:
        return {"intent": "not_found",
                "text": f"<strong>{entity_a}</strong> not found in the fact graph."}
    if ent_b is None:
        return {"intent": "not_found",
                "text": f"<strong>{entity_b}</strong> not found in the fact graph."}

    user_prompt = f"""\
Compare these two companies for Eastcoast Fund investment decision.

## {ent_a['name']}
{_facts_to_briefing(facts_a)}
{_conflicts_to_briefing(conf_a)}

## {ent_b['name']}
{_facts_to_briefing(facts_b)}
{_conflicts_to_briefing(conf_b)}

User question: "{user_message}"

Structure your answer: brief on each company, then a clear recommendation for which is the stronger fit for Eastcoast Fund and why.
"""
    system = f"""\
{_FUND_CONTEXT}
You are a senior investment analyst comparing two portfolio candidates for Eastcoast Fund.
Be specific, reference actual numbers, and give a clear recommendation.
Format: <strong> for company names and key numbers, <br><br> between sections. Max 200 words.
"""
    text = _claude(client, system, user_prompt, max_tokens=500)
    return {"intent": "comparison", "entity": ent_a["name"], "entity2": ent_b["name"], "text": text}


def _sector_bar_row(r: dict, total_cos: int) -> str:
    pct     = f'{r["company_count"] / total_cos * 100:.0f}%' if total_cos else '0%'
    bar     = '▓' * max(1, round(r['company_count'] / total_cos * 20))
    arr_str = f' · \u20ac{r["total_arr_m"]:.1f}M ARR' if r['total_arr_m'] > 0 else ''
    flag    = f'  \u26a0 {r["open_conflicts"]}' if r['open_conflicts'] > 0 else ''
    return (
        f'<div style="margin:4px 0;font-size:12px">'
        f'<span style="display:inline-block;width:120px;font-family:var(--mono)">{r["sector"]}</span> '
        f'<span style="color:var(--purple2)">{bar}</span> '
        f'<span style="color:var(--muted)">{r["company_count"]} cos · {pct}{arr_str}{flag}</span>'
        f'</div>'
    )


def _handle_sector(sector_filter: str | None) -> dict:
    """SQL-aggregated sector breakdown — no Gemini needed."""
    with get_dict_cursor() as cur:
        cur.execute("""
            WITH sector_facts AS (
                SELECT entity_id,
                    MAX(CASE WHEN attribute='sector'  THEN value END)         AS sector,
                    MAX(CASE WHEN attribute='arr_eur' THEN value::numeric END) AS arr_eur
                FROM facts GROUP BY entity_id
            ),
            conflict_counts AS (
                SELECT entity_id, COUNT(DISTINCT id) AS open_conflicts
                FROM (
                    SELECT f.entity_id, c.id FROM conflicts c
                    JOIN facts f ON c.fact_a_id = f.id WHERE c.status='open'
                    UNION ALL
                    SELECT f.entity_id, c.id FROM conflicts c
                    JOIN facts f ON c.fact_b_id = f.id WHERE c.status='open'
                ) sub GROUP BY entity_id
            )
            SELECT COALESCE(sf.sector,'Unknown')        AS sector,
                   COUNT(DISTINCT e.id)                 AS company_count,
                   ROUND(SUM(sf.arr_eur)/1e6, 2)        AS total_arr_m,
                   COALESCE(SUM(cc.open_conflicts), 0)  AS open_conflicts
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

    total_cos = sum(r["company_count"] for r in rows)
    total_arr = sum(r["total_arr_m"]   for r in rows)

    if sector_filter:
        row = next((r for r in rows
                    if sector_filter.lower() in r["sector"].lower()), None)
        if row:
            pct      = f"{row['company_count']/total_cos*100:.1f}%" if total_cos else "—"
            arr_str  = f" — <strong>€{row['total_arr_m']:.1f}M ARR</strong>" if row["total_arr_m"] > 0 else ""
            flag_str = (f' · <strong style="color:var(--amber)">'
                        f'{row["open_conflicts"]} open conflict'
                        f'{"s" if row["open_conflicts"]!=1 else ""}</strong>'
                        if row["open_conflicts"] > 0 else "")
            text = (f'<strong>{row["sector"]}</strong>: <strong>{row["company_count"]} companies</strong>'
                    f' ({pct} of portfolio){arr_str}{flag_str}.')
        else:
            top5 = " ".join(f'<span class="fact-tag">{r["sector"]}</span>' for r in rows[:5])
            text = f'No companies tagged as <strong>{sector_filter}</strong>. Sectors present: {top5}'
    else:
        bar_rows = "".join(
            _sector_bar_row(r, total_cos)
            for r in rows[:12]
        )
        text = (f'Portfolio: <strong>{total_cos} companies</strong> · '
                f'<strong>€{total_arr:.1f}M total ARR</strong><br><br>{bar_rows}')

    return {"intent": "sector", "text": text, "sectors": rows}


def _handle_conflicts(client, user_message: str) -> dict:
    """Fetch open conflicts, annotate with delta %, ask Gemini for top-3 triage."""
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT c.id::text AS conflict_id, e.name AS entity_name,
                   f1.attribute, f1.value AS value_a, f2.value AS value_b,
                   COALESCE(s1.type::text,'unknown') AS source_a,
                   COALESCE(s2.type::text,'unknown') AS source_b,
                   c.status::text AS status
            FROM conflicts c
            JOIN facts f1 ON c.fact_a_id = f1.id
            JOIN facts f2 ON c.fact_b_id = f2.id
            JOIN entities e ON f1.entity_id = e.id
            LEFT JOIN sources s1 ON f1.source_id = s1.id
            LEFT JOIN sources s2 ON f2.source_id = s2.id
            WHERE c.status = 'open'
            ORDER BY
                CASE WHEN f1.attribute IN ('arr_eur','mrr_eur','valuation') THEN 0 ELSE 1 END,
                c.created_at DESC
            LIMIT 100
        """)
        raw = [dict(r) for r in cur.fetchall()]

    # Annotate with ARR delta %
    annotated = []
    for c in raw:
        entry = dict(c)
        try:
            a, b = float(c["value_a"]), float(c["value_b"])
            if max(a, b) > 0:
                entry["delta_pct"] = round(abs(a - b) / max(a, b) * 100, 1)
        except (ValueError, TypeError):
            pass
        annotated.append(entry)

    # Build conflict briefing for Gemini
    lines = [f"Total open conflicts: {len(annotated)}\n"]
    for c in annotated[:20]:
        delta = f" (delta {c['delta_pct']:.0f}%)" if "delta_pct" in c else ""
        lines.append(
            f"• {c['entity_name']} — {c['attribute'].replace('_',' ')}: "
            f"{c['source_a']} '{c['value_a']}' vs {c['source_b']} '{c['value_b']}'{delta}"
        )
    conflict_briefing = "\n".join(lines)

    user_prompt = f"""\
{conflict_briefing}

User question: "{user_message}"

Identify the top 3 most urgent conflicts requiring human attention. For each:
- Why it matters (financial impact or data integrity risk)
- What the delta reveals
- Recommended action (call founder, check CRM, request docs)
"""
    system = f"""\
{_FUND_CONTEXT}
You are a VC data analyst triaging conflicts in the fund's fact graph.
Be specific and actionable. Format each conflict as a short numbered point.
Use <strong> for company names and numbers. Max 200 words.
"""
    top3_text = _claude(client, system, user_prompt, max_tokens=400)
    open_count = len(annotated)
    header = (f'<strong style="color:var(--amber)">{open_count} open conflicts</strong> '
              f'in the fact graph.<br><br>')
    return {"intent": "conflicts", "open_count": open_count,
            "text": header + top3_text, "conflicts": annotated[:20]}


def _handle_harness() -> dict:
    from vcbrain_harness.evolution import get_state
    s = get_state()
    status = s.get("status", "idle")
    best   = s.get("best_score", 0.0)
    iters  = len(s.get("iterations", []))
    max_i  = s.get("max_iterations", 5)
    col_map = {"running": "var(--green)", "done": "var(--purple2)",
               "stopped": "var(--amber)", "error": "var(--red)", "idle": "var(--muted)"}
    col  = col_map.get(status, "var(--muted)")
    pct  = f'<strong style="color:var(--green)">{best*100:.0f}%</strong>' if best > 0 else "not yet scored"
    text = (f'Harness evolution is <strong style="color:{col}">{status}</strong> · '
            f'{pct} best score · {iters}/{max_i} iterations complete.<br><br>'
            f'Open the <strong>Harness evolution</strong> panel to run or monitor progress.')
    return {"intent": "harness", "text": text}


def _handle_stats() -> dict:
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT (SELECT COUNT(*) FROM entities)                   AS entity_count,
                   (SELECT COUNT(*) FROM facts)                      AS fact_count,
                   (SELECT COUNT(*) FROM conflicts WHERE status='open') AS open_conflicts
        """)
        row = dict(cur.fetchone())
    text = (f'VC Brain tracks '
            f'<strong>{int(row["entity_count"]):,} companies</strong> with '
            f'<strong>{int(row["fact_count"]):,} facts</strong> and '
            f'<strong style="color:var(--amber)">{int(row["open_conflicts"])} open conflicts</strong>.')
    return {"intent": "stats", "text": text}


def _handle_general(client, user_message: str) -> dict:
    """Catch-all: fetch a rich portfolio summary and let Claude answer freely."""
    with get_dict_cursor() as cur:
        # Top 20 companies by ARR with key facts
        cur.execute("""
            SELECT e.name, e.type,
                   MAX(CASE WHEN f.attribute='sector'    THEN f.value END) AS sector,
                   MAX(CASE WHEN f.attribute='arr_eur'   THEN f.value END) AS arr_eur,
                   MAX(CASE WHEN f.attribute='stage'     THEN f.value END) AS stage,
                   MAX(CASE WHEN f.attribute='founder'   THEN f.value END) AS founder,
                   MAX(CASE WHEN f.attribute='employees' THEN f.value END) AS employees,
                   COUNT(DISTINCT f.id) AS fact_count
            FROM entities e
            LEFT JOIN facts f ON f.entity_id = e.id
            GROUP BY e.id, e.name, e.type
            ORDER BY MAX(CASE WHEN f.attribute='arr_eur' THEN f.value::numeric ELSE 0 END) DESC NULLS LAST
            LIMIT 30
        """)
        top_cos = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT (SELECT COUNT(*) FROM entities) AS entity_count,
                   (SELECT COUNT(*) FROM facts)    AS fact_count,
                   (SELECT COUNT(*) FROM conflicts WHERE status='open') AS open_conflicts
        """)
        totals = dict(cur.fetchone())

    lines = [
        f"Portfolio: {int(totals['entity_count'])} companies, "
        f"{int(totals['fact_count'])} facts, "
        f"{int(totals['open_conflicts'])} open conflicts.\n",
        "Top 30 companies by ARR (name | sector | ARR € | stage | founder | employees):",
    ]
    for c in top_cos:
        arr = f"€{float(c['arr_eur']):,.0f}" if c['arr_eur'] else "—"
        lines.append(
            f"  {c['name']} | {c['sector'] or '—'} | {arr} | "
            f"{c['stage'] or '—'} | {c['founder'] or '—'} | {c['employees'] or '—'}"
        )

    portfolio_summary = "\n".join(lines)

    system = f"""\
{_FUND_CONTEXT}
You are a senior VC analyst for Eastcoast Fund with access to the fund's full portfolio data.
Answer the question specifically using the data provided. If data is incomplete, say so.
Use <strong> for key names and numbers. Keep the answer under 200 words. No markdown, no bullet lists — use short sentences or <br><br> between paragraphs.
"""
    user_prompt = f"""{portfolio_summary}

User question: "{user_message}"
"""
    text = _claude(client, system, user_prompt, max_tokens=400)
    return {"intent": "general", "text": text}


# ── Route ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@router.post("")
async def chat(body: ChatRequest) -> dict:
    """Classify the user message, fetch enriched data, synthesize with Claude where needed."""
    msg = body.message.strip()

    def _handle() -> dict:
        import anthropic
        import logging

        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            return {
                "intent": "error",
                "text": "ANTHROPIC_API_KEY is not configured. Add it to your .env and restart.",
            }

        try:
            client = make_client()
        except KeyError:
            return {
                "intent": "error",
                "text": "ANTHROPIC_API_KEY is not configured. Add it to your .env and restart.",
            }

        try:
            clf = _classify(client, msg)
        except anthropic.RateLimitError as exc:
            logging.getLogger("vcbrain.chat").warning("Claude rate limit: %s", exc)
            return {
                "intent": "error",
                "text": (
                    "Anthropic API rate limit reached — wait a moment and try again. "
                    "See your plan limits in the Anthropic console."
                ),
            }
        except Exception as exc:
            logging.getLogger("vcbrain.chat").error("_classify failed: %s", exc, exc_info=True)
            exc_str = str(exc)
            if "429" in exc_str or "rate_limit" in exc_str.lower():
                return {
                    "intent": "error",
                    "text": (
                        "Anthropic API rate limit reached — wait a moment and try again."
                    ),
                }
            clf = {"intent": "unknown", "entity": None, "entity2": None, "sector": None}

        intent  = clf.get("intent", "unknown")
        entity  = clf.get("entity")
        entity2 = clf.get("entity2")
        sector  = clf.get("sector")

        try:
            if intent == "company"    and entity:  return _handle_company(client, entity, msg)
            if intent == "brief"      and entity:  return _handle_brief(entity)
            if intent == "comparison" and entity and entity2:
                                                   return _handle_comparison(client, entity, entity2, msg)
            if intent == "sector":                 return _handle_sector(sector)
            if intent == "conflicts":              return _handle_conflicts(client, msg)
            if intent == "harness":                return _handle_harness()
            if intent == "stats":                  return _handle_stats()
            if intent == "general":                return _handle_general(client, msg)
        except Exception as exc:
            return {
                "intent": "error",
                "text": (f'Something went wrong: <strong>{str(exc)[:120]}</strong>. '
                         f'Check the server logs.'),
            }

        return {
            "intent": "unknown",
            "text": (
                'I can answer questions about companies, sector exposure, conflicts, and harness evolution. Try:<br><br>'
                '<span class="fact-tag" style="cursor:pointer" onclick="sendSugg(\'What do you know about Hogan PLC?\')">Hogan PLC</span> '
                '<span class="fact-tag" style="cursor:pointer" onclick="sendSugg(\'What is our healthcare exposure?\')">Healthcare exposure</span> '
                '<span class="fact-tag" style="cursor:pointer" onclick="sendSugg(\'What conflicts need attention?\')">Conflicts</span> '
                '<span class="fact-tag" style="cursor:pointer" onclick="sendSugg(\'Compare Hogan PLC and Parker Group\')">Compare two companies</span> '
                '<span class="fact-tag" style="cursor:pointer" onclick="sendSugg(\'How many companies are tracked?\')">Portfolio stats</span>'
            ),
        }

    return await run_in_threadpool(_handle)
