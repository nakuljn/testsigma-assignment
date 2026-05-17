"""Customer Insight Agent — return-rate aggregation + LLM issue classification."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.config.settings import BATCH_LLM
from ecom_ops.core.batch_llm import batch_llm_decisions
from ecom_ops.core.llm import get_llm
from ecom_ops.core.parsing import parse_llm_json
from ecom_ops.core.progress import progress
from ecom_ops.core.state import OpsState, ProductIssue

AGENT = "customer_insight_agent"

RETURN_RATE_THRESHOLD = 0.08
AVG_RATING_THRESHOLD = 3.2

SYSTEM_PROMPT = """You are a customer experience analyst for an e-commerce store.
You will receive data about a product SKU: its reviews and return reasons.

Your job is to:
1. Identify the primary issue_type. Choose ONE from:
   quality | sizing | shipping | description_mismatch | other
2. Assess severity: "high" if it is a recurring, serious defect that hurts customers;
   "medium" if it is a notable but manageable issue; "low" if it is minor or isolated.
3. Extract 2-4 short evidence quotes (paraphrase, max 15 words each) from the reviews.
4. Write a concise rationale (1-2 sentences).

Respond ONLY with a JSON object (no markdown fences):
{
  "issue_type": "...",
  "severity": "high|medium|low",
  "evidence": ["...", "..."],
  "rationale": "..."
}
"""

BATCH_SYSTEM_PROMPT = """You are a customer experience analyst.
You receive a JSON array of SKUs with reviews and return data. For EACH SKU classify the issue.

Respond ONLY with a JSON array (same order as input):
[{"sku": "...", "issue_type": "quality|sizing|shipping|description_mismatch|other",
  "severity": "high|medium|low", "evidence": ["..."], "rationale": "..."}, ...]
"""


def _collect_candidates(reviews_data: list[dict]) -> list[dict]:
    candidates = []
    for record in reviews_data:
        sku = record["sku"]
        reviews = record.get("reviews", [])
        returns = record.get("returns", [])
        total_sold = record.get("total_units_sold", 1) or 1
        if not reviews:
            continue
        return_rate = len(returns) / total_sold
        avg_rating = sum(r["rating"] for r in reviews) / len(reviews)
        if return_rate < RETURN_RATE_THRESHOLD and avg_rating >= AVG_RATING_THRESHOLD:
            continue
        candidates.append({
            "sku": sku,
            "avg_rating": round(avg_rating, 2),
            "return_rate_pct": round(return_rate * 100, 1),
            "return_reasons": [r["reason"] for r in returns],
            "reviews": [{"rating": r["rating"], "text": r["text"]} for r in reviews],
            "_return_rate": round(return_rate, 4),
        })
    return candidates


async def run_customer_insight_agent(state: OpsState) -> dict[str, Any]:
    llm = get_llm()
    reviews_data = state["reviews"]
    progress("Scanning reviews and returns…", agent=AGENT)

    candidates = _collect_candidates(reviews_data)
    if not candidates:
        return {"product_issues": []}

    issues: list[ProductIssue] = []

    if BATCH_LLM:
        batch_input = [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
        rows = await batch_llm_decisions(
            llm, BATCH_SYSTEM_PROMPT, batch_input, AGENT, "customer_insight"
        )
        meta = {c["sku"]: c for c in candidates}
        for parsed in rows:
            sku = parsed.get("sku")
            if sku not in meta:
                continue
            issues.append(ProductIssue(
                sku=sku,
                issue_type=parsed["issue_type"],
                severity=parsed["severity"],
                evidence=parsed.get("evidence", []),
                return_rate=meta[sku]["_return_rate"],
                rationale=parsed["rationale"],
            ))
        return {"product_issues": issues}

    for c in candidates:
        sku = c["sku"]
        progress(f"LLM issue analysis: {sku}…", agent=AGENT)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(
                {k: v for k, v in c.items() if not k.startswith("_")}, indent=2
            )),
        ]
        response = await llm.ainvoke(messages)
        parsed = parse_llm_json(response.content)
        issues.append(ProductIssue(
            sku=sku,
            issue_type=parsed["issue_type"],
            severity=parsed["severity"],
            evidence=parsed.get("evidence", []),
            return_rate=c["_return_rate"],
            rationale=parsed["rationale"],
        ))

    return {"product_issues": issues}
