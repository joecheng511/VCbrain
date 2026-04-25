"""
VCbrain Layer 3 harness — v0 baseline.

solve(company_name) -> JSON string:
  Fetches facts from Layer 2 API, reasons with Claude, returns a VC analyst brief.
"""

import json
import os
import urllib.request
import urllib.error

import anthropic

LAYER2_BASE = os.environ.get("LAYER2_BASE_URL", "http://localhost:8000")
MODEL = "claude-sonnet-4-6"

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


def _fetch_entity(company_name: str) -> dict:
    url = f"{LAYER2_BASE}/entity/{urllib.parse.quote(company_name)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise RuntimeError(f"Layer 2 API unavailable: {exc}") from exc


def _build_facts_block(data: dict) -> str:
    lines = [f"Company: {data['entity']['name']} (type: {data['entity']['type']})"]
    lines.append("\nFacts:")
    for f in data.get("facts", []):
        flag = " [LOW CONFIDENCE]" if f["confidence"] < 0.7 else ""
        lines.append(
            f"  - {f['attribute']}: {f['value']} "
            f"(confidence={f['confidence']}, source={f['source']['type']}){flag}"
        )
    return "\n".join(lines)


def _build_conflicts_block(data: dict) -> str:
    conflicts = data.get("conflicts", [])
    if not conflicts:
        return ""
    lines = ["\nOpen Conflicts (require analyst judgment):"]
    for c in conflicts:
        if c["status"] == "open":
            lines.append(
                f"  - {c['attribute']}: '{c['value_a']}' vs '{c['value_b']}'"
            )
    return "\n".join(lines) if len(lines) > 1 else ""


def solve(input_data: str) -> str:
    """Entry point — receives company name, returns JSON brief string."""
    company_name = input_data.strip()

    # Fetch from Layer 2
    entity_data = _fetch_entity(company_name)

    facts_block = _build_facts_block(entity_data)
    conflicts_block = _build_conflicts_block(entity_data)

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
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    brief = json.loads(raw)
    return json.dumps(brief)


# Allow import fix for urllib.parse used inside _fetch_entity
import urllib.parse  # noqa: E402 — must be after stdlib import block
