"""
VCbrain Layer 3 harness — v1.

solve(company_name) -> JSON string:
  1. Fetches entity facts from GET /entity/{name}   (Layer 2)
  2. Fetches open conflicts from GET /conflicts?entity={name}  (Layer 2)
  3. Sends merged context to Claude, returns a structured VC investment brief.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import anthropic

LAYER2_BASE = os.environ.get("LAYER2_BASE_URL", "http://localhost:8000")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

ANALYST_PROMPT = """\
You are a senior VC analyst at a top-tier venture fund. You have been given structured data \
about a company pulled from the fund's internal fact graph. Your job is to produce a concise \
investment brief.

## Source Data
{facts_block}

{conflicts_block}

## Instructions
- Base every claim strictly on the source data above. Do not invent facts.
- If a fact has confidence < 0.7, flag it as uncertain.
- If there are open conflicts, reason over both values and state which you trust more and why.
- Assign a verdict: strong_pass | pass | borderline | fail
  - strong_pass: clear product-market fit, strong growth, clean data
  - pass: investable with normal diligence gaps
  - borderline: significant uncertainty or one red flag
  - fail: deal-breaker present (fraud signal, regulatory block, collapsing revenue)

## Required Output (valid JSON only, no markdown fences)
{{
  "company": "<name>",
  "verdict": "<strong_pass|pass|borderline|fail>",
  "key_facts": [
    {{"claim": "<fact>", "confidence": <0.0-1.0>, "source": "<source type>"}}
  ],
  "red_flags": ["<flag>"],
  "questions_for_founder": ["<question>"],
  "one_line_summary": "<one sentence>"
}}
"""


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

    prompt = ANALYST_PROMPT.format(
        facts_block=facts_block,
        conflicts_block=conflicts_block,
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    brief = json.loads(raw)
    return json.dumps(brief)
