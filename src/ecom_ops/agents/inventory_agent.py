"""
Inventory Agent — deterministic days-of-cover + LLM urgency/rationale.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.config.settings import (
    BATCH_LLM,
    DAYS_COVER_CRITICAL,
    DAYS_COVER_LOW,
    RESTOCK_TARGET_DAYS,
)
from ecom_ops.core.batch_llm import batch_llm_decisions
from ecom_ops.core.llm import get_llm
from ecom_ops.core.parsing import parse_llm_json
from ecom_ops.core.progress import progress
from ecom_ops.core.state import OpsState, RestockDecision

AGENT = "inventory_agent"

SYSTEM_PROMPT = """You are an inventory operations analyst.
You will be given data about a SKU that needs restocking: current stock, reorder point,
average daily sales, days of cover remaining, lead time, and velocity trend.

Your job is to:
1. Choose urgency: "critical" if stock will run out before replenishment arrives,
   "medium" if stock is below reorder point, "low" if stock is above reorder point
   but trending towards depletion.
2. Write a concise rationale (1-3 sentences) explaining the decision, referencing the
   velocity trend where relevant.

Respond ONLY with a JSON object:
{"urgency": "critical|medium|low", "rationale": "..."}
"""

BATCH_SYSTEM_PROMPT = """You are an inventory operations analyst.
You receive a JSON array of SKU restock candidates. For EACH candidate return urgency and rationale.

Respond ONLY with a JSON array (same order as input), no markdown:
[{"sku": "SKU-001", "urgency": "critical|medium|low", "rationale": "..."}, ...]
"""


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _velocity_trend(daily_units: list[float]) -> str:
    if len(daily_units) < 10:
        return "flat"
    first_half = _avg(daily_units[:15])
    second_half = _avg(daily_units[15:])
    if first_half == 0:
        return "accelerating" if second_half > 0 else "flat"
    change_pct = (second_half - first_half) / first_half
    if change_pct > 0.10:
        return "accelerating"
    if change_pct < -0.10:
        return "declining"
    return "flat"


def _collect_candidates(inventory: list[dict], sales_history: dict) -> list[dict]:
    candidates = []
    for record in inventory:
        sku = record["sku"]
        stock = record["stock_level"]
        reorder_point = record["reorder_point"]
        lead_time = record["lead_time_days"]
        daily_units = sales_history.get(sku, [])
        avg_sales = _avg(daily_units)
        if avg_sales == 0:
            continue
        days_of_cover = stock / avg_sales
        trend = _velocity_trend(daily_units)
        recommended_qty = max(0, int((RESTOCK_TARGET_DAYS - days_of_cover) * avg_sales))
        needs_attention = (
            stock < reorder_point or days_of_cover < lead_time or days_of_cover < DAYS_COVER_LOW
        )
        if not needs_attention:
            continue
        candidates.append({
            "sku": sku,
            "stock_level": stock,
            "reorder_point": reorder_point,
            "avg_daily_sales": round(avg_sales, 2),
            "days_of_cover": round(days_of_cover, 1),
            "lead_time_days": lead_time,
            "velocity_trend": trend,
            "recommended_restock_qty": recommended_qty,
            "_record": record,
            "_recommended_qty": recommended_qty,
        })
    return candidates


async def run_inventory_agent(state: OpsState) -> dict[str, Any]:
    llm = get_llm()
    inventory = state["inventory"]
    sales_history = state["sales_history"]
    progress("Checking stock levels…", agent=AGENT)

    candidates = _collect_candidates(inventory, sales_history)
    if not candidates:
        return {"restock_decisions": []}

    decisions: list[RestockDecision] = []

    if BATCH_LLM:
        batch_input = [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
        rows = await batch_llm_decisions(llm, BATCH_SYSTEM_PROMPT, batch_input, AGENT, "inventory")
        row_by_sku = {r["sku"]: r for r in rows}
        for c in candidates:
            sku = c["sku"]
            if sku not in row_by_sku:
                continue
            parsed = row_by_sku[sku]
            decisions.append(RestockDecision(
                sku=sku,
                current_stock=c["_record"]["stock_level"],
                reorder_point=c["_record"]["reorder_point"],
                recommended_qty=c["_recommended_qty"],
                urgency=parsed["urgency"],
                rationale=parsed["rationale"],
            ))
        return {"restock_decisions": decisions}

    for c in candidates:
        sku = c["sku"]
        progress(f"LLM restock decision: {sku}…", agent=AGENT)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(
                {k: v for k, v in c.items() if not k.startswith("_")}, indent=2
            )),
        ]
        response = await llm.ainvoke(messages)
        parsed = parse_llm_json(response.content)
        decisions.append(RestockDecision(
            sku=sku,
            current_stock=c["_record"]["stock_level"],
            reorder_point=c["_record"]["reorder_point"],
            recommended_qty=c["_recommended_qty"],
            urgency=parsed["urgency"],
            rationale=parsed["rationale"],
        ))

    return {"restock_decisions": decisions}
