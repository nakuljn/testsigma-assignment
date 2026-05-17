"""
LangChain tools used by agents.

web_search: tries Tavily first, falls back to DuckDuckGo, degrades gracefully on failure.
All searches are wrapped in a timeout so the demo never hangs indefinitely.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger(__name__)


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web for competitor prices or market context.

    Returns a list of {"title": ..., "url": ..., "snippet": ...} dicts.
    Returns an empty list (never raises) so agents can always fall back gracefully.
    """
    from ecom_ops.config.settings import (
        SEARCH_PROVIDER,
        TAVILY_API_KEY,
        SKIP_WEB_SEARCH,
        SEARCH_TIMEOUT_SECONDS,
    )

    if SKIP_WEB_SEARCH:
        return []

    provider = SEARCH_PROVIDER.lower()
    timeout = SEARCH_TIMEOUT_SECONDS

    def _run_search() -> list[dict]:
        if provider == "tavily" and TAVILY_API_KEY:
            try:
                return _tavily_search(query, max_results)
            except Exception as exc:
                logger.warning("Tavily search failed (%s), trying DuckDuckGo fallback.", exc)
        return _ddg_search(query, max_results)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_search)
            return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning("Web search timed out after %ss for query: %s", timeout, query[:80])
        return []
    except Exception as exc:
        logger.warning("Web search failed (%s). Returning empty results.", exc)
        return []


def _tavily_search(query: str, max_results: int) -> list[dict]:
    from tavily import TavilyClient
    from ecom_ops.config.settings import TAVILY_API_KEY
    client = TavilyClient(api_key=TAVILY_API_KEY)
    resp = client.search(query, max_results=max_results)
    results = []
    for r in resp.get("results", []):
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        })
    return results


async def web_search_async(query: str, max_results: int = 5) -> list[dict]:
    """Async wrapper around sync web_search (runs in a thread pool)."""
    return await asyncio.to_thread(web_search, query, max_results)


def _ddg_search(query: str, max_results: int) -> list[dict]:
    from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
    return results
