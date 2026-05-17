"""
Tests for the Orchestrator's conflict detection and resolution logic.
All LLM calls are mocked. No file I/O during these tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ecom_ops.core.state import (
    empty_state,
    RestockDecision,
    PriceDecision,
    ProductIssue,
    CampaignDraft,
    Conflict,
)
from ecom_ops.agents.orchestrator import _detect_conflicts, _apply_resolutions


def _make_restock(sku, urgency="medium"):
    return RestockDecision(
        sku=sku, current_stock=5, reorder_point=20,
        recommended_qty=100, urgency=urgency, rationale="test"
    )

def _make_price(sku, old_price, new_price, driver="demand"):
    return PriceDecision(
        sku=sku, old_price=old_price, new_price=new_price,
        driver=driver, rationale="test"
    )

def _make_issue(sku, severity="high"):
    return ProductIssue(
        sku=sku, issue_type="quality", severity=severity, rationale="test"
    )

def _make_campaign(sku, reason="low_sales", channel="email"):
    return CampaignDraft(
        sku=sku, reason=reason, channel=channel,
        subject="Subject", body="Body."
    )

def _mock_llm(narrative="Resolution narrative."):
    mock = MagicMock()
    resp = MagicMock()
    resp.content = narrative
    mock.ainvoke = AsyncMock(return_value=resp)
    return mock


class TestConflictDetection:
    def test_no_conflicts_when_consistent(self):
        restocks = [_make_restock("SKU-A")]
        prices = [_make_price("SKU-B", 20.0, 18.0)]
        issues = []
        campaigns = [_make_campaign("SKU-C")]
        result = _detect_conflicts(restocks, prices, issues, campaigns)
        assert result == []

    def test_detects_promote_vs_broken(self):
        issues = [_make_issue("SKU-X", severity="high")]
        campaigns = [_make_campaign("SKU-X")]
        result = _detect_conflicts([], [], issues, campaigns)
        assert len(result) == 1
        assert result[0]["kind"] == "promote_vs_broken"
        assert result[0]["sku"] == "SKU-X"

    def test_promote_vs_broken_only_for_high_severity(self):
        issues = [_make_issue("SKU-X", severity="medium")]
        campaigns = [_make_campaign("SKU-X")]
        result = _detect_conflicts([], [], issues, campaigns)
        assert len(result) == 0

    def test_detects_price_up_vs_discount(self):
        prices = [_make_price("SKU-Y", 20.0, 25.0, driver="demand")]
        campaigns = [_make_campaign("SKU-Y")]
        result = _detect_conflicts([], prices, [], campaigns)
        assert len(result) == 1
        assert result[0]["kind"] == "price_up_vs_discount"

    def test_no_conflict_when_price_drops(self):
        prices = [_make_price("SKU-Y", 25.0, 20.0, driver="competitor")]
        campaigns = [_make_campaign("SKU-Y")]
        result = _detect_conflicts([], prices, [], campaigns)
        assert result == []

    def test_detects_restock_vs_clearance(self):
        restocks = [_make_restock("SKU-Z")]
        prices = [_make_price("SKU-Z", 30.0, 15.0, driver="clearance")]
        result = _detect_conflicts(restocks, prices, [], [])
        assert len(result) == 1
        assert result[0]["kind"] == "restock_vs_clearance"

    def test_detects_multiple_conflicts(self):
        issues = [_make_issue("SKU-A", severity="high")]
        campaigns = [_make_campaign("SKU-A"), _make_campaign("SKU-B")]
        prices = [_make_price("SKU-B", 10.0, 15.0)]
        restocks = [_make_restock("SKU-C")]
        clearance_prices = prices + [_make_price("SKU-C", 20.0, 8.0, driver="clearance")]
        result = _detect_conflicts(restocks, clearance_prices, issues, campaigns)
        kinds = {r["kind"] for r in result}
        assert "promote_vs_broken" in kinds
        assert "price_up_vs_discount" in kinds
        assert "restock_vs_clearance" in kinds

    def test_skips_already_suppressed_campaigns(self):
        issues = [_make_issue("SKU-X", severity="high")]
        campaign = CampaignDraft(
            sku="SKU-X", reason="low_sales", channel="email",
            subject="[SUPPRESSED]", body="[SUPPRESSED]",
            suppressed=True,
            suppression_reason="Already suppressed by marketing.",
        )
        result = _detect_conflicts([], [], issues, [campaign])
        assert result == []


class TestConflictResolution:
    @pytest.mark.asyncio
    async def test_promote_vs_broken_suppresses_campaign(self):
        raw = [{"kind": "promote_vs_broken", "sku": "SKU-X",
                "competing": ["marketing", "customer_insight"],
                "winning_action": "suppress_campaign"}]
        campaigns = [_make_campaign("SKU-X")]
        restocks = []
        llm = _mock_llm()
        resolved, updated_campaigns, _ = await _apply_resolutions(raw, campaigns, restocks, llm)
        assert len(resolved) == 1
        assert resolved[0].kind == "promote_vs_broken"
        skus = {d.sku: d for d in updated_campaigns}
        assert skus["SKU-X"].suppressed is True
        assert "Orchestrator suppressed" in skus["SKU-X"].suppression_reason

    @pytest.mark.asyncio
    async def test_price_up_vs_discount_suppresses_campaign(self):
        raw = [{"kind": "price_up_vs_discount", "sku": "SKU-Y",
                "competing": ["pricing", "marketing"],
                "winning_action": "keep_price_at_25.00_drop_campaign"}]
        campaigns = [_make_campaign("SKU-Y")]
        resolved, updated_campaigns, _ = await _apply_resolutions(raw, campaigns, [], _mock_llm())
        assert updated_campaigns[0].suppressed is True

    @pytest.mark.asyncio
    async def test_restock_vs_clearance_cancels_restock(self):
        raw = [{"kind": "restock_vs_clearance", "sku": "SKU-Z",
                "competing": ["inventory", "pricing"],
                "winning_action": "cancel_restock_proceed_with_clearance"}]
        restocks = [_make_restock("SKU-Z"), _make_restock("SKU-W")]
        campaigns = []
        resolved, _, updated_restocks = await _apply_resolutions(raw, campaigns, restocks, _mock_llm())
        sku_list = [d.sku for d in updated_restocks]
        assert "SKU-Z" not in sku_list
        assert "SKU-W" in sku_list

    @pytest.mark.asyncio
    async def test_resolution_narrative_is_set(self):
        raw = [{"kind": "promote_vs_broken", "sku": "SKU-X",
                "competing": ["marketing", "customer_insight"],
                "winning_action": "suppress_campaign"}]
        campaigns = [_make_campaign("SKU-X")]
        llm = _mock_llm("Campaign suppressed due to high-severity defect.")
        resolved, _, _ = await _apply_resolutions(raw, campaigns, [], llm)
        assert resolved[0].resolution == "Campaign suppressed due to high-severity defect."
