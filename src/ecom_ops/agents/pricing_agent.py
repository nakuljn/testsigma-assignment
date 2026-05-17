"""Pricing Agent — demand signal + optional web search + LLM price synthesis."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.config.settings import (
    BATCH_LLM,
    MAX_PRICING_WEB_SEARCHES,
    MIN_MARGIN_PCT,
    SKIP_WEB_SEARCH,
)
from ecom_ops.core.batch_llm import batch_llm_decisions
from ecom_ops.core.llm import get_llm
from ecom_ops.core.parsing import parse_llm_json
from ecom_ops.core.progress import progress
from ecom_ops.core.state import OpsState, PriceDecision, ProductIssue
from ecom_ops.core.tools import web_search_async

AGENT = "pricing_agent"

SYSTEM_PROMPT = """You are a pricing strategist for an e-commerce store.
You receive a SKU's cost, current price, demand trend, competitor data (may be empty),
price floor (cost × margin policy), and any product quality issues.

Respond ONLY with valid JSON (no markdown fences):
{
  "new_price": 0.00,
  "driver": "competitor|demand|clearance",
  "rationale": "..."
}
"""

BATCH_SYSTEM_PROMPT = """You are a pricing strategist.
You receive a JSON array of SKU pricing candidates. For EACH propose new_price, driver, rationale.
new_price MUST be >= price_floor. Do NOT raise price if has_high_severity_issue is true.

Respond ONLY with a JSON array:
[{"sku": "...", "new_price": 0.00, "driver": "competitor|demand|clearance", "rationale": "..."}, ...]
"""


def _demand_signal(daily_units: list[float]) -> dict:
    if len(daily_units) < 20:
        return {"trend": "insufficient_data", "recent_avg": 0, "prior_avg": 0, "change_pct": 0}
    recent = sum(daily_units[-10:]) / 10
    prior = sum(daily_units[:10]) / 10
    change_pct = ((recent - prior) / prior * 100) if prior > 0 else 0
    trend = "flat"
    if change_pct > 10:
        trend = "growing"
    elif change_pct < -10:
        trend = "declining"
    return {
        "trend": trend,
        "recent_avg": round(recent, 2),
        "prior_avg": round(prior, 2),
        "change_pct": round(change_pct, 1),
    }


def _collect_candidates(
    catalog: list[dict],
    sales_history: dict,
    high_severity_skus: set[str],
) -> list[dict]:
    candidates = []
    for product in catalog:
        sku = product["id"]
        daily_units = sales_history.get(sku, [])
        demand = _demand_signal(daily_units)
        if demand["trend"] == "insufficient_data":
            continue
        if demand["trend"] == "flat" and sku not in high_severity_skus:
            continue
        price_floor = round(product["cost"] * (1 + MIN_MARGIN_PCT), 2)
        candidates.append({
            "sku": sku,
            "product_name": product["name"],
            "cost": product["cost"],
            "current_price": product["current_price"],
            "price_floor": price_floor,
            "demand_signal": demand,
            "has_high_severity_issue": sku in high_severity_skus,
            "_product": product,
            "_price_floor": price_floor,
            "_competitor_refs": [],
        })
    return candidates


async def run_pricing_agent(state: OpsState) -> dict[str, Any]:
    llm = get_llm()
    catalog = state["catalog"]
    sales_history = state["sales_history"]
    product_issues: list[ProductIssue] = state.get("product_issues", [])
    high_severity_skus = {i.sku for i in product_issues if i.severity == "high"}

    progress("Analysing catalog for price changes…", agent=AGENT)
    candidates = _collect_candidates(catalog, sales_history, high_severity_skus)
    if not candidates:
        return {"price_decisions": []}

    web_searches_done = 0
    if not SKIP_WEB_SEARCH and not BATCH_LLM:
        for c in candidates:
            if web_searches_done >= MAX_PRICING_WEB_SEARCHES:
                break
            sku = c["sku"]
            progress(
                f"Web search ({web_searches_done + 1}/{MAX_PRICING_WEB_SEARCHES}): {sku}…",
                agent=AGENT,
            )
            try:
                results = await web_search_async(
                    f"{c['product_name']} price buy online", max_results=4
                )
                c["_competitor_refs"] = [r["url"] for r in results if r.get("url")]
                c["competitor_search_results"] = [
                    {"title": r["title"], "snippet": r["snippet"][:300], "url": r["url"]}
                    for r in results
                ]
            except Exception:
                c["competitor_search_results"] = "no_results_available"
            web_searches_done += 1
    else:
        for c in candidates:
            c["competitor_search_results"] = "no_results_available"

    decisions: list[PriceDecision] = []

    if BATCH_LLM:
        batch_input = []
        for c in candidates:
            batch_input.append({
                "sku": c["sku"],
                "product_name": c["product_name"],
                "cost": c["cost"],
                "current_price": c["current_price"],
                "price_floor": c["price_floor"],
                "demand_signal": c["demand_signal"],
                "has_high_severity_issue": c["has_high_severity_issue"],
                "competitor_search_results": c.get("competitor_search_results", "no_results_available"),
            })
        rows = await batch_llm_decisions(llm, BATCH_SYSTEM_PROMPT, batch_input, AGENT, "pricing")
        meta = {c["sku"]: c for c in candidates}
        for parsed in rows:
            sku = parsed.get("sku")
            if sku not in meta:
                continue
            c = meta[sku]
            current_price = c["current_price"]
            new_price = max(round(float(parsed["new_price"]), 2), c["_price_floor"])
            if sku in high_severity_skus and new_price > current_price:
                continue
            if abs(new_price - current_price) < 0.01:
                continue
            decisions.append(PriceDecision(
                sku=sku,
                old_price=current_price,
                new_price=new_price,
                driver=parsed["driver"],
                competitor_refs=c["_competitor_refs"],
                rationale=parsed["rationale"],
            ))
        return {"price_decisions": decisions}

    for c in candidates:
        sku = c["sku"]
        progress(f"LLM pricing decision: {sku}…", agent=AGENT)
        payload = {
            k: v for k, v in c.items()
            if not k.startswith("_") and k != "competitor_search_results"
        }
        payload["competitor_search_results"] = c.get(
            "competitor_search_results", "no_results_available"
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, indent=2)),
        ]
        response = await llm.ainvoke(messages)
        parsed = parse_llm_json(response.content)
        current_price = c["current_price"]
        new_price = max(round(float(parsed["new_price"]), 2), c["_price_floor"])
        if sku in high_severity_skus and new_price > current_price:
            continue
        if abs(new_price - current_price) < 0.01:
            continue
        decisions.append(PriceDecision(
            sku=sku,
            old_price=current_price,
            new_price=new_price,
            driver=parsed["driver"],
            competitor_refs=c["_competitor_refs"],
            rationale=parsed["rationale"],
        ))

    return {"price_decisions": decisions}
