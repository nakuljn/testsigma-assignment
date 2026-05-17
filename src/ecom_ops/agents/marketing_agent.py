"""Marketing Agent — low-seller/overstock campaigns with high-severity suppression."""

from __future__ import annotations

import json
import statistics
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.config.settings import BATCH_LLM, LOW_SALES_QUARTILE
from ecom_ops.core.batch_llm import batch_llm_decisions
from ecom_ops.core.llm import get_llm
from ecom_ops.core.parsing import parse_llm_json
from ecom_ops.core.progress import progress
from ecom_ops.core.state import OpsState, CampaignDraft, ProductIssue

AGENT = "marketing_agent"

SYSTEM_PROMPT = """You are a creative e-commerce marketing copywriter.
Write a short campaign. Respond ONLY with JSON: {"subject": "...", "body": "..."}
"""

BATCH_SYSTEM_PROMPT = """You are a marketing copywriter.
You receive campaign targets. For EACH write subject and body matching the channel.

Respond ONLY with a JSON array:
[{"sku": "...", "subject": "...", "body": "..."}, ...]
"""


def _total_sales(daily_units: list[float]) -> float:
    return sum(daily_units)


def _build_targets(state: OpsState) -> tuple[list[dict], list[CampaignDraft]]:
    catalog = state["catalog"]
    inventory = state["inventory"]
    sales_history = state["sales_history"]
    product_issues: list[ProductIssue] = state.get("product_issues", [])

    high_severity_skus = {i.sku for i in product_issues if i.severity == "high"}
    inv_map = {r["sku"]: r for r in inventory}
    totals = {p["id"]: _total_sales(sales_history.get(p["id"], [])) for p in catalog}
    all_totals = [v for v in totals.values() if v > 0]
    if not all_totals:
        return [], []

    quartile_cutoff = (
        statistics.quantiles(all_totals, n=4)[0]
        if len(all_totals) >= 2
        else all_totals[0] * LOW_SALES_QUARTILE
    )

    suppressed_drafts: list[CampaignDraft] = []
    llm_targets: list[dict] = []

    for product in catalog:
        sku = product["id"]
        total = totals.get(sku, 0)
        inv_record = inv_map.get(sku, {})
        stock = inv_record.get("stock_level", 0)
        reorder_point = inv_record.get("reorder_point", 1)

        reason = None
        if total <= quartile_cutoff:
            reason = "low_sales"
        elif stock > reorder_point * 3:
            reason = "overstock"

        if reason is None:
            continue

        if sku in high_severity_skus:
            suppressed_drafts.append(CampaignDraft(
                sku=sku,
                reason=reason,
                channel="email",
                subject="[SUPPRESSED]",
                body="[SUPPRESSED]",
                suppressed=True,
                suppression_reason=(
                    "SKU has an open high-severity product issue. "
                    "Promoting a known-defective product would harm customer trust."
                ),
            ))
            continue

        channel = "social" if reason == "overstock" else "email"
        llm_targets.append({
            "sku": sku,
            "product_name": product["name"],
            "category": product["category"],
            "current_price": product["current_price"],
            "campaign_reason": reason,
            "channel": channel,
            "_reason": reason,
            "_channel": channel,
        })

    return llm_targets, suppressed_drafts


async def run_marketing_agent(state: OpsState) -> dict[str, Any]:
    llm = get_llm()
    llm_targets, suppressed_drafts = _build_targets(state)
    progress(f"Drafting {len(llm_targets) + len(suppressed_drafts)} campaign(s)…", agent=AGENT)

    drafts: list[CampaignDraft] = list(suppressed_drafts)

    if not llm_targets:
        return {"campaign_drafts": drafts}

    if BATCH_LLM:
        batch_input = [{k: v for k, v in t.items() if not k.startswith("_")} for t in llm_targets]
        rows = await batch_llm_decisions(
            llm, BATCH_SYSTEM_PROMPT, batch_input, AGENT, "marketing"
        )
        meta = {t["sku"]: t for t in llm_targets}
        for parsed in rows:
            sku = parsed.get("sku")
            if sku not in meta:
                continue
            t = meta[sku]
            drafts.append(CampaignDraft(
                sku=sku,
                reason=t["_reason"],
                channel=t["_channel"],
                subject=parsed["subject"],
                body=parsed["body"],
            ))
        return {"campaign_drafts": drafts}

    for t in llm_targets:
        sku = t["sku"]
        progress(f"LLM campaign copy: {sku}…", agent=AGENT)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(
                {k: v for k, v in t.items() if not k.startswith("_")}, indent=2
            )),
        ]
        response = await llm.ainvoke(messages)
        parsed = parse_llm_json(response.content)
        drafts.append(CampaignDraft(
            sku=sku,
            reason=t["_reason"],
            channel=t["_channel"],
            subject=parsed["subject"],
            body=parsed["body"],
        ))

    return {"campaign_drafts": drafts}
