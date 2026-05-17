"""Shared helpers for parsing LLM JSON responses."""

from __future__ import annotations

import json


class LLMParsingError(ValueError):
    """Raised when an LLM response cannot be parsed as JSON."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def parse_llm_json(raw: str) -> dict:
    """
    Parse JSON from an LLM response, stripping optional markdown code fences.

    Raises LLMParsingError with the raw text on failure.
    """
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = raw[:200] + ("..." if len(raw) > 200 else "")
        raise LLMParsingError(
            f"LLM returned invalid JSON: {exc}. Raw preview: {preview!r}",
            raw=raw,
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMParsingError(
            f"Expected JSON object, got {type(parsed).__name__}",
            raw=raw,
        )
    return parsed


def parse_llm_json_array(raw: str) -> list[dict]:
    """Parse a JSON array from an LLM response (batch mode)."""
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = raw[:200] + ("..." if len(raw) > 200 else "")
        raise LLMParsingError(
            f"LLM returned invalid JSON: {exc}. Raw preview: {preview!r}",
            raw=raw,
        ) from exc

    if isinstance(parsed, dict) and "decisions" in parsed:
        parsed = parsed["decisions"]
    if not isinstance(parsed, list):
        raise LLMParsingError(
            f"Expected JSON array, got {type(parsed).__name__}",
            raw=raw,
        )
    return parsed
