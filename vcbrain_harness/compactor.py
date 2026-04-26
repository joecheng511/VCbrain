"""
LLM-powered context compactor for VCbrain.

Pre-processes raw entity facts and conflicts before they are sent to Gemini.
Uses Pioneer.ai's /v1/chat/completions API to summarize the full entity record
(facts + conflicts) into a concise plain-text summary.

Returns a compact text string that replaces the verbose JSON block in the
analyst prompt — same signal, fewer tokens.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests
import urllib3

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

PIONEER_BASE_URL = "https://api.pioneer.ai"
# Override via PIONEER_MODEL_ID env var.
DEFAULT_MODEL_ID = "43b5e386-e995-4847-afb4-9e9556e0a368"

SYSTEM_PROMPT = (
    "You are a context compactor. Given a structured JSON record, extract and summarize "
    "only the key fields and most important information into a concise plain-text summary. "
    "Strip redundant nested 'raw' fields, verbose descriptions, and non-essential metadata. "
    "Focus on: entity identity, core metrics, status, relationships, and any flags or "
    "conflicts. Be brief but complete — one to four sentences maximum."
)

_SESSION: requests.Session | None = None
_API_DISABLED: bool = False  # session-level circuit breaker


# ── Session ───────────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    api_key = os.environ.get("PIONEER_API_KEY", "")
    if not api_key:
        raise RuntimeError("PIONEER_API_KEY not set")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})
    if os.environ.get("PIONEER_INSECURE_SSL", "").lower() in ("1", "true", "yes"):
        logger.warning(
            "PIONEER_INSECURE_SSL=true — skipping TLS verification on Pioneer API. "
            "Use only as a temporary workaround for expired server certs."
        )
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return session


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _make_session()
    return _SESSION


def reset_model_cache() -> None:
    """Reset the HTTP session and circuit breaker (e.g. after updating PIONEER_API_KEY)."""
    global _SESSION, _API_DISABLED
    _SESSION = None
    _API_DISABLED = False


# ── Pioneer API ───────────────────────────────────────────────────────────────

def _pioneer_chat(user_content: str) -> str:
    """POST to Pioneer /v1/chat/completions. Returns the assistant message text."""
    model_id = os.environ.get("PIONEER_MODEL_ID", DEFAULT_MODEL_ID)
    url = f"{PIONEER_BASE_URL}/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    resp = _get_session().post(url, json=payload, timeout=30)
    if not resp.ok:
        raise RuntimeError(
            f"Request failed with status {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ── Error helpers ─────────────────────────────────────────────────────────────

def _is_ssl_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "certificate" in msg or "ssl" in msg or "certificate_verify_failed" in msg


def _trip_circuit_breaker(reason: str, exc: BaseException) -> None:
    global _API_DISABLED
    if _API_DISABLED:
        return
    _API_DISABLED = True
    logger.warning(
        "Disabling Pioneer.ai compaction for the rest of this session — %s: %s. "
        "Compaction will be skipped and facts passed through unfiltered. "
        "Set PIONEER_INSECURE_SSL=true for a temporary workaround if this is a "
        "server-side cert issue.",
        reason, exc,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def compact_context(entity_data: dict, conflicts: list[dict]) -> str | None:
    """
    Summarize entity facts and conflicts into a compact plain-text string.

    Sends the full entity record (facts + open conflicts) to Pioneer's LLM
    and returns a one-to-four sentence summary. Returns None if compaction
    is disabled, the API key is missing, or the call fails — the caller
    should fall back to raw fact rendering.
    """
    if _API_DISABLED or not os.environ.get("PIONEER_API_KEY"):
        if not _API_DISABLED:
            logger.warning("PIONEER_API_KEY not set; skipping compaction")
        return None

    record: dict[str, Any] = {
        "entity": entity_data.get("entity", {}),
        "facts": entity_data.get("facts", []),
    }
    open_conflicts = [c for c in conflicts if c.get("status") == "open"]
    if open_conflicts:
        record["conflicts"] = open_conflicts

    try:
        summary = _pioneer_chat(json.dumps(record, default=str))
        company = (entity_data.get("entity") or {}).get("name", "unknown")
        logger.info("Compacted context for %s via Pioneer LLM", company)
        return summary.strip()
    except Exception as exc:
        if _is_ssl_error(exc):
            _trip_circuit_breaker("TLS verification failed", exc)
        else:
            logger.warning("Pioneer compaction failed (%s); falling back to raw facts", exc)
        return None
