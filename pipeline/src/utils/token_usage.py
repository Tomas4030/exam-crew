from __future__ import annotations

from collections import defaultdict
from typing import Any


_usage: dict[str, int] = defaultdict(int)
_calls = 0
_models: set[str] = set()


def record_usage(response: dict[str, Any] | None, model: str | None = None) -> None:
    """Collect token usage from model responses when the provider returns it."""
    global _calls
    _calls += 1
    if model:
        _models.add(model)

    usage = (response or {}).get("usage") or {}
    if not isinstance(usage, dict):
        return

    for source_key, target_key in (
        ("prompt_tokens", "promptTokens"),
        ("completion_tokens", "completionTokens"),
        ("total_tokens", "totalTokens"),
        ("reasoning_tokens", "reasoningTokens"),
    ):
        value = usage.get(source_key)
        if isinstance(value, int):
            _usage[target_key] += value


def get_token_usage() -> dict[str, Any]:
    return {
        "calls": _calls,
        "models": sorted(_models),
        "promptTokens": _usage.get("promptTokens", 0),
        "completionTokens": _usage.get("completionTokens", 0),
        "reasoningTokens": _usage.get("reasoningTokens", 0),
        "totalTokens": _usage.get("totalTokens", 0),
    }
