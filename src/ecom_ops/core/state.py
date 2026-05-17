"""
The state & decision contract for the agentic ops system.

OpsState is the single shared object flowing through the LangGraph graph.
Decision models are what agents PRODUCE; committed_changes is what the
Orchestrator alone writes after conflict resolution.

Contract rules (enforced in tests/test_state_contract.py):
  1. Agents only append to their own decision list.
  2. Every decision carries a `rationale` field.
  3. Only the Orchestrator writes conflicts, committed_changes, report_markdown.
"""

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Decision models — what agents PRODUCE (never commit themselves)
# ---------------------------------------------------------------------------

class RestockDecision(BaseModel):
    sku: str
    current_stock: int
    reorder_point: int
    recommended_qty: int
    urgency: Literal["low", "medium", "critical"]
    rationale: str


class PriceDecision(BaseModel):
    sku: str
    old_price: float
    new_price: float
    driver: Literal["competitor", "demand", "clearance"]
    competitor_refs: list[str] = Field(default_factory=list)
    rationale: str


class ProductIssue(BaseModel):
    sku: str
    issue_type: Literal[
        "quality", "sizing", "shipping", "description_mismatch", "other"
    ]
    severity: Literal["low", "medium", "high"]
    evidence: list[str] = Field(default_factory=list)
    return_rate: Optional[float] = None
    rationale: str = ""


class CampaignDraft(BaseModel):
    sku: str
    reason: Literal["low_sales", "overstock", "seasonal"]
    channel: Literal["email", "social"]
    subject: str
    body: str
    suppressed: bool = False
    suppression_reason: str = ""


# ---------------------------------------------------------------------------
# Orchestrator outputs
# ---------------------------------------------------------------------------

class Conflict(BaseModel):
    sku: str
    kind: Literal["price_up_vs_discount", "promote_vs_broken", "restock_vs_clearance"]
    competing: list[str]
    resolution: str
    winning_action: str


# ---------------------------------------------------------------------------
# The shared graph state
# ---------------------------------------------------------------------------

class OpsState(TypedDict):
    run_date: str

    # Raw inputs — read-only snapshots loaded at graph start
    catalog: list[dict]
    inventory: list[dict]
    sales_history: dict          # {sku: [units_day0, units_day1, ...]}
    reviews: list[dict]

    # Agent outputs — decisions, not commits
    restock_decisions: list[RestockDecision]
    product_issues: list[ProductIssue]
    price_decisions: list[PriceDecision]
    campaign_drafts: list[CampaignDraft]

    # Orchestrator outputs — written only by the Orchestrator node
    conflicts: list[Conflict]
    committed_changes: list[dict]
    report_markdown: str


def empty_state(run_date: str = "") -> OpsState:
    """Return a zeroed-out OpsState for testing or graph initialisation."""
    return OpsState(
        run_date=run_date,
        catalog=[],
        inventory=[],
        sales_history={},
        reviews=[],
        restock_decisions=[],
        product_issues=[],
        price_decisions=[],
        campaign_drafts=[],
        conflicts=[],
        committed_changes=[],
        report_markdown="",
    )
