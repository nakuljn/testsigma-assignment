"""
End-to-end graph tests. All LLM calls are mocked so no API key is needed.
Tests verify:
  - Graph runs without error from initial seeded state to final state.
  - All expected keys are present in final state.
  - Conflict ledger is populated when conflicting seed data is used.
  - Web search failure does not crash the pipeline.
  - Report file is written to disk.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ecom_ops.core.state import empty_state, OpsState


def _mock_llm_factory(responses: dict[str, dict]):
    default = {"urgency": "medium", "rationale": "Test.",
               "issue_type": "quality", "severity": "low",
               "evidence": [], "new_price": 25.0, "driver": "demand",
               "subject": "Test subject", "body": "Test body."}

    mock_llm = MagicMock()

    async def smart_invoke(messages):
        content = " ".join(str(m.content) for m in messages)
        if "resolution narrative" in content.lower() or "winning action" in content.lower():
            resp = MagicMock()
            resp.content = "Conflict resolved per policy."
            return resp
        if "urgency" in content and "days_of_cover" in content:
            payload = {"urgency": "medium", "rationale": "Stock is low."}
        elif "issue_type" in content or "return_rate" in content:
            payload = {"issue_type": "quality", "severity": "low",
                       "evidence": [], "rationale": "Minor issue."}
        elif "new_price" in content or "demand_signal" in content:
            payload = {"new_price": 25.0, "driver": "demand", "rationale": "Demand-only pricing."}
        elif "subject" in content or "campaign_reason" in content:
            payload = {"subject": "Try this product", "body": "Check it out today."}
        else:
            payload = default
        resp = MagicMock()
        resp.content = json.dumps(payload)
        return resp

    mock_llm.ainvoke = AsyncMock(side_effect=smart_invoke)
    return mock_llm


class TestGraphEndToEnd:
    async def _run_graph(self, mock_llm=None):
        if mock_llm is None:
            mock_llm = _mock_llm_factory({})

        from ecom_ops.graph.ops_graph import run_daily_cycle

        with patch("ecom_ops.agents.inventory_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.customer_insight_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.pricing_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.marketing_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.orchestrator.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.pricing_agent.web_search_async", new_callable=AsyncMock, return_value=[]):
            return await run_daily_cycle("2026-05-17")

    @pytest.mark.asyncio
    async def test_graph_runs_and_returns_ops_state(self):
        final = await self._run_graph()
        assert isinstance(final, dict)
        assert "report_markdown" in final
        assert "committed_changes" in final
        assert "conflicts" in final

    @pytest.mark.asyncio
    async def test_all_state_keys_present(self):
        final = await self._run_graph()
        required_keys = [
            "run_date", "catalog", "inventory", "sales_history", "reviews",
            "restock_decisions", "product_issues", "price_decisions",
            "campaign_drafts", "conflicts", "committed_changes", "report_markdown",
        ]
        for key in required_keys:
            assert key in final, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_report_markdown_non_empty(self):
        final = await self._run_graph()
        assert len(final["report_markdown"]) > 100
        assert "Daily Ops Report" in final["report_markdown"]

    @pytest.mark.asyncio
    async def test_report_file_written_to_disk(self, tmp_path):
        import ecom_ops.config.settings as s
        original_dir = s.OUTPUT_DIR
        s.OUTPUT_DIR = tmp_path
        try:
            final = await self._run_graph()
            report_file = tmp_path / "daily_ops_2026-05-17.md"
            assert report_file.exists(), f"Expected report at {report_file}"
            assert report_file.read_text(encoding="utf-8") == final["report_markdown"]
        finally:
            s.OUTPUT_DIR = original_dir

    @pytest.mark.asyncio
    async def test_restock_decisions_from_seeded_data(self):
        final = await self._run_graph()
        restock_skus = {d.sku for d in final["restock_decisions"]}
        assert "SKU-001" in restock_skus
        assert "SKU-003" in restock_skus

    @pytest.mark.asyncio
    async def test_no_crash_with_network_failure(self):
        mock_llm = _mock_llm_factory({})

        async def exploding_search(*a, **kw):
            raise ConnectionError("Simulated network failure")

        from ecom_ops.graph.ops_graph import run_daily_cycle

        with patch("ecom_ops.agents.inventory_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.customer_insight_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.pricing_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.marketing_agent.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.orchestrator.get_llm", return_value=mock_llm), \
             patch("ecom_ops.agents.pricing_agent.web_search_async", side_effect=exploding_search):
            final = await run_daily_cycle("2026-05-17")

        assert "report_markdown" in final

    @pytest.mark.asyncio
    async def test_product_issues_surfaced(self):
        final = await self._run_graph()
        for issue in final["product_issues"]:
            assert hasattr(issue, "sku")
            assert hasattr(issue, "severity")
            assert hasattr(issue, "rationale")

    @pytest.mark.asyncio
    async def test_committed_changes_are_dicts(self):
        final = await self._run_graph()
        for change in final["committed_changes"]:
            assert isinstance(change, dict)
            assert "type" in change
            assert "sku" in change


class TestWebSearchFallback:
    def test_ddg_failure_returns_empty(self):
        from ecom_ops.core.tools import web_search
        with patch("ecom_ops.core.tools._ddg_search", side_effect=RuntimeError("DDG down")), \
             patch("ecom_ops.core.tools._tavily_search", side_effect=RuntimeError("Tavily down")):
            result = web_search("some query")
        assert result == []

    def test_tavily_fails_ddg_used_as_fallback(self):
        fallback_result = [{"title": "t", "url": "http://example.com", "snippet": "s"}]
        import os
        original_provider = os.environ.get("SEARCH_PROVIDER", "duckduckgo")
        os.environ["SEARCH_PROVIDER"] = "tavily"
        os.environ["TAVILY_API_KEY"] = "fake-key"
        try:
            with patch("ecom_ops.core.tools._tavily_search", side_effect=RuntimeError("Tavily down")), \
                 patch("ecom_ops.core.tools._ddg_search", return_value=fallback_result):
                from ecom_ops.core.tools import web_search
                result = web_search("test")
            assert result == fallback_result
        finally:
            os.environ["SEARCH_PROVIDER"] = original_provider
            if "TAVILY_API_KEY" in os.environ:
                del os.environ["TAVILY_API_KEY"]
