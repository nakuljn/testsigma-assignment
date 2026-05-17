"""
Provider-agnostic LLM factory.

Usage:
    from core.llm import get_llm
    llm = get_llm()          # uses MODEL_PROVIDER env var
    llm = get_llm("openai")  # force provider
"""

from __future__ import annotations
from typing import Optional
from langchain_core.language_models import BaseChatModel


def get_llm(provider: Optional[str] = None, temperature: float = 0.2) -> BaseChatModel:
    """Return a configured chat model for the given provider.

    Falls back to the MODEL_PROVIDER env var if provider is not specified.
    Raises ValueError for unknown providers so the failure is explicit.
    """
    from ecom_ops.config.settings import (
        MODEL_PROVIDER,
        OPENAI_API_KEY,
        OPENAI_MODEL,
        ANTHROPIC_API_KEY,
        ANTHROPIC_MODEL,
    )

    resolved = (provider or MODEL_PROVIDER).lower()

    if resolved == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=OPENAI_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY or None,
        )

    if resolved == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=ANTHROPIC_MODEL,
            temperature=temperature,
            api_key=ANTHROPIC_API_KEY or None,
        )

    raise ValueError(
        f"Unknown MODEL_PROVIDER '{resolved}'. "
        "Set MODEL_PROVIDER to 'openai' or 'anthropic'."
    )
