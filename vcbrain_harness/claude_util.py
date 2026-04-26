"""Shared Anthropic Claude client helpers for harness, evolution, and chat."""
from __future__ import annotations

import os

import anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL).strip()


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise KeyError("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key)


def chat_text(
    client: anthropic.Anthropic,
    *,
    system: str | None,
    user: str,
    max_tokens: int,
) -> str:
    """One Messages API call; returns assistant text or empty string."""
    kwargs: dict = {
        "model": anthropic_model(),
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    return ""
