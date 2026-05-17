"""
Unit tests for Inventory Agent deterministic logic.
No LLM calls are made — we mock the LLM response.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ecom_ops.core.state import empty_state, RestockDecision
from ecom_ops.agents.inventory_agent import run_inventory_agent, _avg, _velocity_trend


class TestHelpers:
    def test_avg_empty(self):
        assert _avg([]) == 0.0

    def test_avg_values(self):
        assert _avg([2.0, 4.0, 6.0]) == pytest.approx(4.0)

    def test_velocity_trend_accelerating(self):
        data = [1.0] * 15 + [3.0] * 15
        assert _velocity_trend(data) == "accelerating"

    def test_velocity_trend_declining(self):
        data = [3.0] * 15 + [1.0] * 15
        assert _velocity_trend(data) == "declining"

    def test_velocity_trend_flat(self):
        data = [2.0] * 30
        assert _velocity_trend(data) == "flat"

    def test_velocity_trend_insufficient(self):
        data = [1.0] * 5
        assert _velocity_trend(data) == "flat"


class TestInventoryAgent:
    def _make_state(self, inventory, sales_history):
        state = empty_state("2026-05-17")
        state["inventory"] = inventory
        state["sales_history"] = sales_history
        return state

    def _mock_llm_response(self, urgency="medium", rationale="Test rationale."):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({"urgency": urgency, "rationale": rationale})
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        return mock_llm

    @pytest.mark.asyncio
    async def test_skips_sku_zero_sales(self):
        state = self._make_state(
            inventory=[{"sku": "SKU-ZZ", "stock_level": 5, "reorder_point": 10, "lead_time_days": 5}],
            sales_history={"SKU-ZZ": [0.0] * 30},
        )
        with patch("ecom_ops.agents.inventory_agent.get_llm", return_value=self._mock_llm_response()):
            result = await run_inventory_agent(state)
        assert result["restock_decisions"] == []

    @pytest.mark.asyncio
    async def test_flags_below_reorder_point(self):
        state = self._make_state(
            inventory=[{"sku": "SKU-AA", "stock_level": 5, "reorder_point": 20, "lead_time_days": 7}],
            sales_history={"SKU-AA": [2.0] * 30},
        )
        with patch("ecom_ops.agents.inventory_agent.get_llm", return_value=self._mock_llm_response("critical")):
            result = await run_inventory_agent(state)
        assert len(result["restock_decisions"]) == 1
        d = result["restock_decisions"][0]
        assert d.sku == "SKU-AA"
        assert d.urgency == "critical"

    @pytest.mark.asyncio
    async def test_skips_healthy_stock(self):
        state = self._make_state(
            inventory=[{"sku": "SKU-BB", "stock_level": 200, "reorder_point": 20, "lead_time_days": 5}],
            sales_history={"SKU-BB": [2.0] * 30},
        )
        with patch("ecom_ops.agents.inventory_agent.get_llm", return_value=self._mock_llm_response()):
            result = await run_inventory_agent(state)
        assert result["restock_decisions"] == []

    @pytest.mark.asyncio
    async def test_decision_has_rationale(self):
        state = self._make_state(
            inventory=[{"sku": "SKU-CC", "stock_level": 3, "reorder_point": 25, "lead_time_days": 10}],
            sales_history={"SKU-CC": [3.0] * 30},
        )
        with patch("ecom_ops.agents.inventory_agent.get_llm",
                   return_value=self._mock_llm_response("critical", "Stock out in 1 day.")):
            result = await run_inventory_agent(state)
        d = result["restock_decisions"][0]
        assert d.rationale == "Stock out in 1 day."

    @pytest.mark.asyncio
    async def test_recommended_qty_positive(self):
        state = self._make_state(
            inventory=[{"sku": "SKU-DD", "stock_level": 5, "reorder_point": 20, "lead_time_days": 7}],
            sales_history={"SKU-DD": [2.0] * 30},
        )
        with patch("ecom_ops.agents.inventory_agent.get_llm", return_value=self._mock_llm_response("medium")):
            result = await run_inventory_agent(state)
        d = result["restock_decisions"][0]
        assert d.recommended_qty > 0
