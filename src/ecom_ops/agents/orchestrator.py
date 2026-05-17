"""
Orchestrator Agent

The ONLY writer of committed_changes, conflicts, and report_markdown.

Step 1 — Detect conflicts (deterministic):
  - price_up_vs_discount: Pricing raised price while Marketing drafted a campaign for same SKU.
  - promote_vs_broken: Marketing campaign for a SKU with a high-severity ProductIssue.
  - restock_vs_clearance: Inventory wants to restock a SKU that Pricing marked clearance.

Step 2 — Resolve (fixed precedence; LLM writes narrative only):
  - promote_vs_broken → suppress campaign (customer-impact safety beats revenue).
  - price_up_vs_discount → pricing wins (demand truth beats stale plans).
  - restock_vs_clearance → clearance wins (don't restock what you're winding down).

Step 3 — Commit + report.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.core.llm import get_llm
from ecom_ops.core.progress import progress
from ecom_ops.core.state import (
    OpsState,
    Conflict,
    CampaignDraft,
    PriceDecision,
    RestockDecision,
    ProductIssue,
)
from ecom_ops.data.store import MockStore


RESOLUTION_PROMPT = """You are an operations coordinator writing a one-sentence human-readable
resolution summary for a detected conflict between two agents' decisions.
Be concise, factual, and reference the SKU and the winning action.
Return ONLY the sentence — no JSON, no markdown.
"""


async def _write_resolution_narrative(
    llm, conflict_kind: str, sku: str, winning_action: str
) -> str:
    msg = (
        f"Conflict type: {conflict_kind}\n"
        f"SKU: {sku}\n"
        f"Winning action: {winning_action}\n"
        "Write the resolution narrative."
    )
    response = await llm.ainvoke([
        SystemMessage(content=RESOLUTION_PROMPT),
        HumanMessage(content=msg),
    ])
    return response.content.strip()


# ---------------------------------------------------------------------------
# Step 1: Conflict detection
# ---------------------------------------------------------------------------

def _detect_conflicts(
    restock_decisions: list[RestockDecision],
    price_decisions: list[PriceDecision],
    product_issues: list[ProductIssue],
    campaign_drafts: list[CampaignDraft],
) -> list[dict]:
    """
    Returns a list of raw conflict dicts (kind, sku, competing, winning_action).
    No LLM call here — pure deterministic detection.
    """
    raw_conflicts: list[dict] = []

    price_map = {d.sku: d for d in price_decisions}
    restock_map = {d.sku: d for d in restock_decisions}
    high_issue_skus = {i.sku for i in product_issues if i.severity == "high"}
    clearance_skus = {d.sku for d in price_decisions if d.driver == "clearance"}

    for draft in campaign_drafts:
        if draft.suppressed:
            continue
        sku = draft.sku

        # promote_vs_broken: marketing campaign for a high-severity issue SKU
        if sku in high_issue_skus:
            raw_conflicts.append({
                "kind": "promote_vs_broken",
                "sku": sku,
                "competing": ["marketing", "customer_insight"],
                "winning_action": "suppress_campaign",
            })
            continue

        # price_up_vs_discount: pricing raised price AND marketing drafted campaign
        if sku in price_map and price_map[sku].new_price > price_map[sku].old_price:
            raw_conflicts.append({
                "kind": "price_up_vs_discount",
                "sku": sku,
                "competing": ["pricing", "marketing"],
                "winning_action": f"keep_price_at_{price_map[sku].new_price:.2f}_drop_campaign",
            })

    # restock_vs_clearance: inventory restock AND pricing clearance for same SKU
    for sku in clearance_skus:
        if sku in restock_map:
            raw_conflicts.append({
                "kind": "restock_vs_clearance",
                "sku": sku,
                "competing": ["inventory", "pricing"],
                "winning_action": "cancel_restock_proceed_with_clearance",
            })

    return raw_conflicts


# ---------------------------------------------------------------------------
# Step 2: Resolve (apply fixed-precedence rules; LLM writes narrative)
# ---------------------------------------------------------------------------

async def _apply_resolutions(
    raw_conflicts: list[dict],
    campaign_drafts: list[CampaignDraft],
    restock_decisions: list[RestockDecision],
    llm,
) -> tuple[list[Conflict], list[CampaignDraft], list[RestockDecision]]:
    """
    Mutates campaign_drafts and restock_decisions in-place based on winning actions.
    Returns resolved Conflict objects.
    """
    campaign_map = {d.sku: d for d in campaign_drafts}
    restock_map = {d.sku: d for d in restock_decisions}
    resolved: list[Conflict] = []

    for raw in raw_conflicts:
        kind = raw["kind"]
        sku = raw["sku"]
        winning_action = raw["winning_action"]

        narrative = await _write_resolution_narrative(llm, kind, sku, winning_action)

        if kind == "promote_vs_broken":
            if sku in campaign_map:
                campaign_map[sku].suppressed = True
                campaign_map[sku].suppression_reason = (
                    "Orchestrator suppressed: high-severity product issue detected."
                )

        elif kind == "price_up_vs_discount":
            if sku in campaign_map:
                campaign_map[sku].suppressed = True
                campaign_map[sku].suppression_reason = (
                    "Orchestrator suppressed: price was raised — discount campaign conflicts with pricing signal."
                )

        elif kind == "restock_vs_clearance":
            if sku in restock_map:
                restock_decisions = [d for d in restock_decisions if d.sku != sku]

        resolved.append(Conflict(
            sku=sku,
            kind=kind,
            competing=raw["competing"],
            resolution=narrative,
            winning_action=winning_action,
        ))

    return resolved, campaign_drafts, restock_decisions


# ---------------------------------------------------------------------------
# Step 3: Commit to MockStore
# ---------------------------------------------------------------------------

def _commit_decisions(
    store: MockStore,
    restock_decisions: list[RestockDecision],
    price_decisions: list[PriceDecision],
    campaign_drafts: list[CampaignDraft],
) -> list[dict]:
    committed: list[dict] = []

    for d in restock_decisions:
        committed.append(store.commit_restock(d.sku, d.recommended_qty, d.urgency))

    for d in price_decisions:
        committed.append(store.commit_price_change(d.sku, d.old_price, d.new_price, d.driver))

    for d in campaign_drafts:
        if not d.suppressed:
            committed.append(store.commit_campaign(d.sku, d.channel, d.subject))

    return committed


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _generate_report(
    run_date: str,
    restock_decisions: list[RestockDecision],
    price_decisions: list[PriceDecision],
    product_issues: list[ProductIssue],
    campaign_drafts: list[CampaignDraft],
    conflicts: list[Conflict],
    committed_changes: list[dict],
) -> str:
    lines: list[str] = []
    lines.append(f"# Daily Ops Report — {run_date}\n")
    lines.append(f"*Generated by Agentic E-Commerce Ops Manager*\n")

    # --- Restocking ---
    lines.append("## Restocking Orders\n")
    active_restocks = restock_decisions
    if active_restocks:
        cancelled_skus = {
            c.sku for c in conflicts if c.kind == "restock_vs_clearance"
        }
        for d in active_restocks:
            if d.sku in cancelled_skus:
                continue
            badge = {"critical": "🔴", "medium": "🟡", "low": "🟢"}.get(d.urgency, "")
            lines.append(f"- **{d.sku}** {badge} `{d.urgency.upper()}` — "
                         f"order **{d.recommended_qty} units** "
                         f"(stock: {d.current_stock}, reorder point: {d.reorder_point})")
            lines.append(f"  > {d.rationale}\n")
    else:
        lines.append("*No restocking required today.*\n")

    # --- Pricing ---
    lines.append("## Pricing Changes\n")
    if price_decisions:
        for d in price_decisions:
            arrow = "▲" if d.new_price > d.old_price else "▼"
            lines.append(f"- **{d.sku}** {arrow} `${d.old_price:.2f}` → `${d.new_price:.2f}` "
                         f"[driver: {d.driver}]")
            lines.append(f"  > {d.rationale}")
            if d.competitor_refs:
                refs = ", ".join(f"[source]({url})" for url in d.competitor_refs[:3])
                lines.append(f"  > Sources: {refs}")
            lines.append("")
    else:
        lines.append("*No pricing changes today.*\n")

    # --- Product Issues ---
    lines.append("## Product Issues\n")
    if product_issues:
        for issue in product_issues:
            badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(issue.severity, "")
            lines.append(f"- **{issue.sku}** {badge} `{issue.severity.upper()}` — "
                         f"type: `{issue.issue_type}`  "
                         f"return rate: {(issue.return_rate or 0):.1%}")
            lines.append(f"  > {issue.rationale}")
            for ev in (issue.evidence or [])[:3]:
                lines.append(f"  - *\"{ev}\"*")
            lines.append("")
    else:
        lines.append("*No product issues surfaced today.*\n")

    # --- Campaigns ---
    lines.append("## Marketing Campaigns\n")
    active_campaigns = [d for d in campaign_drafts if not d.suppressed]
    suppressed_campaigns = [d for d in campaign_drafts if d.suppressed]
    if active_campaigns:
        lines.append("### Active\n")
        for d in active_campaigns:
            lines.append(f"- **{d.sku}** [{d.channel}] reason: `{d.reason}`")
            lines.append(f"  **Subject:** {d.subject}")
            lines.append(f"  > {d.body}\n")
    if suppressed_campaigns:
        lines.append("### Suppressed\n")
        for d in suppressed_campaigns:
            lines.append(f"- **{d.sku}** — {d.suppression_reason}")
        lines.append("")
    if not active_campaigns and not suppressed_campaigns:
        lines.append("*No campaigns today.*\n")

    # --- Conflict Ledger ---
    lines.append("## Conflict Ledger\n")
    if conflicts:
        lines.append(
            "| SKU | Conflict Type | Agents | Resolution | Winning Action |\n"
            "|-----|--------------|--------|------------|----------------|\n"
        )
        for c in conflicts:
            agents = " vs ".join(c.competing)
            lines.append(
                f"| {c.sku} | `{c.kind}` | {agents} | {c.resolution} | `{c.winning_action}` |"
            )
        lines.append("")
    else:
        lines.append("*No conflicts detected today. All agent decisions were consistent.*\n")

    # --- Summary ---
    lines.append("## Summary\n")
    lines.append(f"- Restock orders: {len([d for d in restock_decisions if d.sku not in {c.sku for c in conflicts if c.kind == 'restock_vs_clearance'}])}")
    lines.append(f"- Price changes: {len(price_decisions)}")
    lines.append(f"- Product issues surfaced: {len(product_issues)}")
    lines.append(f"- Campaigns launched: {len(active_campaigns)}")
    lines.append(f"- Campaigns suppressed: {len(suppressed_campaigns)}")
    lines.append(f"- Conflicts resolved: {len(conflicts)}")
    lines.append(f"- Total committed changes: {len(committed_changes)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------

async def run_orchestrator(state: OpsState, store: MockStore | None = None) -> dict[str, Any]:
    """
    LangGraph node. Reads all agent outputs, detects + resolves conflicts,
    commits to MockStore, generates report.
    """
    if store is None:
        store = MockStore()

    progress("Detecting conflicts…", agent="orchestrator")
    llm = get_llm()

    restock_decisions = list(state.get("restock_decisions", []))
    price_decisions = list(state.get("price_decisions", []))
    product_issues = list(state.get("product_issues", []))
    campaign_drafts = list(state.get("campaign_drafts", []))

    # Step 1: Detect
    raw_conflicts = _detect_conflicts(
        restock_decisions, price_decisions, product_issues, campaign_drafts
    )

    # Step 2: Resolve
    if raw_conflicts:
        progress(f"Resolving {len(raw_conflicts)} conflict(s)…", agent="orchestrator")
    conflicts, campaign_drafts, restock_decisions = await _apply_resolutions(
        raw_conflicts, campaign_drafts, restock_decisions, llm
    )

    # Step 3: Commit
    progress("Committing changes and writing report…", agent="orchestrator")
    committed_changes = _commit_decisions(store, restock_decisions, price_decisions, campaign_drafts)

    # Generate report
    run_date = state.get("run_date", str(date.today()))
    report_md = _generate_report(
        run_date,
        restock_decisions,
        price_decisions,
        product_issues,
        campaign_drafts,
        conflicts,
        committed_changes,
    )

    # Persist report to disk (read REPORTS_DIR at call time so tests can patch it)
    from ecom_ops.config import settings as _settings
    _settings.OUTPUT_DIR.mkdir(exist_ok=True)
    report_path = _settings.OUTPUT_DIR / f"daily_ops_{run_date}.md"
    report_path.write_text(report_md, encoding="utf-8")

    return {
        "conflicts": conflicts,
        "committed_changes": committed_changes,
        "report_markdown": report_md,
    }
