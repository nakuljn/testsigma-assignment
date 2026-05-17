"""Single-call batch LLM helper for --fast / BATCH_LLM mode."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.core.parsing import parse_llm_json_array
from ecom_ops.core.progress import progress


async def batch_llm_decisions(
    llm,
    system_prompt: str,
    candidates: list[dict],
    agent: str,
    label: str,
) -> list[dict]:
    """One API round-trip for all candidates. Returns parsed decision dicts in SKU order."""
    if not candidates:
        return []
    progress(f"1 batched LLM call for {len(candidates)} SKU(s)…", agent=agent)
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps({"candidates": candidates}, indent=2)),
    ])
    rows = parse_llm_json_array(response.content)
    by_sku = {str(r.get("sku", "")): r for r in rows if r.get("sku")}
    return [by_sku[c["sku"]] for c in candidates if c["sku"] in by_sku]
