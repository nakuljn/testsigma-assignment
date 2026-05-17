"""
Unit tests for CustomerInsight, Pricing, and Marketing agents.
All LLM calls are mocked.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ecom_ops.core.state import empty_state, ProductIssue, PriceDecision


def _mock_llm(content: dict):
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = json.dumps(content)
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
    return mock_llm


class TestCustomerInsightAgent:
    def _make_state(self, reviews):
        state = empty_state("2026-05-17")
        state["reviews"] = reviews
        return state

    @pytest.mark.asyncio
    async def test_skips_good_skus(self):
        reviews = [{
            "sku": "SKU-GOOD",
            "reviews": [{"rating": 5, "text": "Great!"}] * 5,
            "returns": [],
            "total_units_sold": 100,
        }]
        state = self._make_state(reviews)
        llm_response = {"issue_type": "other", "severity": "low", "evidence": [], "rationale": "x"}
        with patch("ecom_ops.agents.customer_insight_agent.get_llm", return_value=_mock_llm(llm_response)):
            from ecom_ops.agents.customer_insight_agent import run_customer_insight_agent
            result = await run_customer_insight_agent(state)
        assert result["product_issues"] == []

    @pytest.mark.asyncio
    async def test_flags_high_return_rate(self):
        reviews = [{
            "sku": "SKU-BAD",
            "reviews": [{"rating": 2, "text": "Defective."}, {"rating": 1, "text": "Broke immediately."}],
            "returns": [{"reason": "product_defect"}] * 15,
            "total_units_sold": 100,
        }]
        state = self._make_state(reviews)
        llm_response = {
            "issue_type": "quality",
            "severity": "high",
            "evidence": ["Defective on arrival", "Broke immediately"],
            "rationale": "Multiple defect reports.",
        }
        with patch("ecom_ops.agents.customer_insight_agent.get_llm", return_value=_mock_llm(llm_response)):
            from ecom_ops.agents.customer_insight_agent import run_customer_insight_agent
            result = await run_customer_insight_agent(state)
        assert len(result["product_issues"]) == 1
        assert result["product_issues"][0].severity == "high"

    @pytest.mark.asyncio
    async def test_flags_low_avg_rating(self):
        reviews = [{
            "sku": "SKU-LOW",
            "reviews": [{"rating": 2, "text": "Bad."}, {"rating": 2, "text": "Terrible."}],
            "returns": [],
            "total_units_sold": 200,
        }]
        state = self._make_state(reviews)
        llm_response = {"issue_type": "quality", "severity": "medium", "evidence": [], "rationale": "x"}
        with patch("ecom_ops.agents.customer_insight_agent.get_llm", return_value=_mock_llm(llm_response)):
            from ecom_ops.agents.customer_insight_agent import run_customer_insight_agent
            result = await run_customer_insight_agent(state)
        assert len(result["product_issues"]) == 1


class TestPricingAgent:
    def _make_state(self, catalog, sales_history, product_issues=None):
        state = empty_state("2026-05-17")
        state["catalog"] = catalog
        state["sales_history"] = sales_history
        state["product_issues"] = product_issues or []
        return state

    def _growing_sales(self):
        return [10.0] * 10 + [11.0] * 10 + [14.0] * 10

    @pytest.mark.asyncio
    async def test_price_floor_enforced(self):
        catalog = [{"id": "SKU-X", "name": "Widget", "category": "Test", "cost": 10.0, "current_price": 15.0}]
        state = self._make_state(catalog, {"SKU-X": self._growing_sales()})
        llm_response = {"new_price": 9.0, "driver": "demand", "rationale": "Underprice test."}
        with patch("ecom_ops.agents.pricing_agent.get_llm", return_value=_mock_llm(llm_response)):
            with patch("ecom_ops.agents.pricing_agent.web_search_async", new_callable=AsyncMock, return_value=[]):
                from ecom_ops.agents.pricing_agent import run_pricing_agent
                result = await run_pricing_agent(state)
        for d in result["price_decisions"]:
            assert d.new_price >= 10.0 * 1.2

    @pytest.mark.asyncio
    async def test_no_price_hike_on_high_severity_issue(self):
        catalog = [{"id": "SKU-Y", "name": "Broken Gadget", "category": "Test", "cost": 10.0, "current_price": 20.0}]
        issues = [ProductIssue(sku="SKU-Y", issue_type="quality", severity="high", rationale="Defects.")]
        state = self._make_state(catalog, {"SKU-Y": self._growing_sales()}, issues)
        llm_response = {"new_price": 25.0, "driver": "demand", "rationale": "Raise price."}
        with patch("ecom_ops.agents.pricing_agent.get_llm", return_value=_mock_llm(llm_response)):
            with patch("ecom_ops.agents.pricing_agent.web_search_async", new_callable=AsyncMock, return_value=[]):
                from ecom_ops.agents.pricing_agent import run_pricing_agent
                result = await run_pricing_agent(state)
        assert result["price_decisions"] == []

    @pytest.mark.asyncio
    async def test_web_search_failure_doesnt_crash(self):
        catalog = [{"id": "SKU-Z", "name": "Thing", "category": "Test", "cost": 5.0, "current_price": 12.0}]
        state = self._make_state(catalog, {"SKU-Z": self._growing_sales()})
        llm_response = {"new_price": 13.0, "driver": "demand", "rationale": "Demand-only."}

        async def bad_search(*a, **kw):
            raise RuntimeError("Network error")

        with patch("ecom_ops.agents.pricing_agent.get_llm", return_value=_mock_llm(llm_response)):
            with patch("ecom_ops.agents.pricing_agent.web_search_async", side_effect=bad_search):
                from ecom_ops.agents.pricing_agent import run_pricing_agent
                result = await run_pricing_agent(state)
        assert "price_decisions" in result


class TestMarketingAgent:
    def _make_state(self, catalog, inventory, sales_history, product_issues=None):
        state = empty_state("2026-05-17")
        state["catalog"] = catalog
        state["inventory"] = inventory
        state["sales_history"] = sales_history
        state["product_issues"] = product_issues or []
        return state

    @pytest.mark.asyncio
    async def test_suppresses_high_severity_sku(self):
        catalog = [
            {"id": "SKU-A", "name": "Bad Product", "category": "X", "cost": 5.0, "current_price": 10.0},
            {"id": "SKU-B", "name": "Good But Slow", "category": "X", "cost": 5.0, "current_price": 10.0},
        ]
        inventory = [
            {"sku": "SKU-A", "stock_level": 50, "reorder_point": 10, "lead_time_days": 5},
            {"sku": "SKU-B", "stock_level": 50, "reorder_point": 10, "lead_time_days": 5},
        ]
        sales = {"SKU-A": [0.5] * 30, "SKU-B": [0.5] * 30}
        issues = [ProductIssue(sku="SKU-A", issue_type="quality", severity="high", rationale="Defects.")]
        state = self._make_state(catalog, inventory, sales, issues)

        llm_response = {"subject": "Check this out", "body": "Great deal."}
        with patch("ecom_ops.agents.marketing_agent.get_llm", return_value=_mock_llm(llm_response)):
            from ecom_ops.agents.marketing_agent import run_marketing_agent
            result = await run_marketing_agent(state)

        skus = {d.sku: d for d in result["campaign_drafts"]}
        assert skus["SKU-A"].suppressed is True
        assert skus["SKU-A"].suppression_reason != ""
        assert skus["SKU-B"].suppressed is False

    @pytest.mark.asyncio
    async def test_overstock_triggers_campaign(self):
        catalog = [{"id": "SKU-C", "name": "Overloaded Item", "category": "Y", "cost": 5.0, "current_price": 15.0}]
        inventory = [{"sku": "SKU-C", "stock_level": 500, "reorder_point": 50, "lead_time_days": 5}]
        sales = {"SKU-C": [10.0] * 30}
        state = self._make_state(catalog, inventory, sales)

        llm_response = {"subject": "Stock up now", "body": "We have plenty."}
        with patch("ecom_ops.agents.marketing_agent.get_llm", return_value=_mock_llm(llm_response)):
            from ecom_ops.agents.marketing_agent import run_marketing_agent
            result = await run_marketing_agent(state)

        assert any(d.sku == "SKU-C" and d.reason == "overstock"
                   for d in result["campaign_drafts"])

    @pytest.mark.asyncio
    async def test_overstock_uses_social_channel(self):
        catalog = [{"id": "SKU-C", "name": "Overloaded Item", "category": "Y", "cost": 5.0, "current_price": 15.0}]
        inventory = [{"sku": "SKU-C", "stock_level": 500, "reorder_point": 50, "lead_time_days": 5}]
        sales = {"SKU-C": [10.0] * 30}
        state = self._make_state(catalog, inventory, sales)

        llm_response = {"subject": "Stock up now", "body": "We have plenty."}
        with patch("ecom_ops.agents.marketing_agent.get_llm", return_value=_mock_llm(llm_response)):
            from ecom_ops.agents.marketing_agent import run_marketing_agent
            result = await run_marketing_agent(state)

        overstock = next(d for d in result["campaign_drafts"] if d.sku == "SKU-C")
        assert overstock.channel == "social"
