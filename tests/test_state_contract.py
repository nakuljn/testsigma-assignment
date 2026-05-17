"""
Tests that enforce the OpsState contract.
These run without any LLM calls — they verify the schema and typing only.
"""
import pytest
from pydantic import ValidationError
from ecom_ops.core.state import (
    OpsState,
    RestockDecision,
    PriceDecision,
    ProductIssue,
    CampaignDraft,
    Conflict,
    empty_state,
)


class TestDecisionModels:
    def test_restock_decision_requires_rationale(self):
        with pytest.raises(ValidationError):
            RestockDecision(
                sku="SKU-001",
                current_stock=5,
                reorder_point=20,
                recommended_qty=100,
                urgency="critical",
                # rationale omitted
            )

    def test_restock_decision_valid(self):
        d = RestockDecision(
            sku="SKU-001",
            current_stock=5,
            reorder_point=20,
            recommended_qty=100,
            urgency="critical",
            rationale="Stock critically low, will stock out before replenishment arrives.",
        )
        assert d.urgency == "critical"
        assert d.sku == "SKU-001"

    def test_restock_urgency_enum(self):
        with pytest.raises(ValidationError):
            RestockDecision(
                sku="SKU-001",
                current_stock=5,
                reorder_point=20,
                recommended_qty=100,
                urgency="extreme",  # invalid
                rationale="test",
            )

    def test_price_decision_defaults_competitor_refs(self):
        d = PriceDecision(
            sku="SKU-004",
            old_price=59.99,
            new_price=54.99,
            driver="competitor",
            rationale="Competitor X sells at $52.",
        )
        assert d.competitor_refs == []

    def test_price_decision_driver_enum(self):
        with pytest.raises(ValidationError):
            PriceDecision(
                sku="SKU-004",
                old_price=59.99,
                new_price=54.99,
                driver="random",  # invalid
                rationale="test",
            )

    def test_product_issue_severity_enum(self):
        with pytest.raises(ValidationError):
            ProductIssue(
                sku="SKU-001",
                issue_type="quality",
                severity="extreme",  # invalid
                rationale="test",
            )

    def test_product_issue_valid_with_defaults(self):
        issue = ProductIssue(
            sku="SKU-001",
            issue_type="quality",
            severity="high",
            rationale="Multiple reviews mention broken parts.",
        )
        assert issue.evidence == []
        assert issue.return_rate is None

    def test_campaign_draft_suppressed_default(self):
        draft = CampaignDraft(
            sku="SKU-009",
            reason="low_sales",
            channel="email",
            subject="Get Moving With Our Foam Roller",
            body="Limited time offer...",
        )
        assert draft.suppressed is False
        assert draft.suppression_reason == ""

    def test_conflict_kind_enum(self):
        with pytest.raises(ValidationError):
            Conflict(
                sku="SKU-001",
                kind="unknown_conflict",  # invalid
                competing=["pricing", "marketing"],
                resolution="test",
                winning_action="test",
            )


class TestOpsState:
    def test_empty_state_structure(self):
        state = empty_state("2026-05-17")
        assert state["run_date"] == "2026-05-17"
        assert isinstance(state["catalog"], list)
        assert isinstance(state["restock_decisions"], list)
        assert state["report_markdown"] == ""

    def test_state_is_typeddict(self):
        state = empty_state()
        # TypedDict instances are plain dicts
        assert isinstance(state, dict)
        # All required keys present
        required_keys = [
            "run_date", "catalog", "inventory", "sales_history", "reviews",
            "restock_decisions", "product_issues", "price_decisions",
            "campaign_drafts", "conflicts", "committed_changes", "report_markdown",
        ]
        for key in required_keys:
            assert key in state, f"Missing key: {key}"

    def test_agent_output_lists_are_separate(self):
        state = empty_state()
        state["restock_decisions"].append(
            RestockDecision(
                sku="SKU-001",
                current_stock=5,
                reorder_point=20,
                recommended_qty=100,
                urgency="critical",
                rationale="test",
            )
        )
        # Other lists must remain empty
        assert len(state["price_decisions"]) == 0
        assert len(state["product_issues"]) == 0
        assert len(state["campaign_drafts"]) == 0

    def test_orchestrator_fields_start_empty(self):
        state = empty_state()
        assert state["conflicts"] == []
        assert state["committed_changes"] == []
        assert state["report_markdown"] == ""


class TestMockStore:
    def test_store_loads_seed_data(self):
        from ecom_ops.data.store import MockStore
        store = MockStore()
        assert len(store.get_catalog()) == 15
        assert len(store.get_inventory()) == 15
        history = store.get_sales_history()
        assert "SKU-001" in history
        assert len(history["SKU-001"]) == 30

    def test_store_returns_copies(self):
        from ecom_ops.data.store import MockStore
        store = MockStore()
        catalog1 = store.get_catalog()
        catalog2 = store.get_catalog()
        catalog1[0]["name"] = "MUTATED"
        assert store.get_catalog()[0]["name"] != "MUTATED"

    def test_store_commit_price_change(self):
        from ecom_ops.data.store import MockStore
        store = MockStore()
        store.commit_price_change("SKU-001", 89.99, 79.99, "competitor")
        changes = store.get_committed_changes()
        assert len(changes) == 1
        assert changes[0]["type"] == "price_change"
        assert changes[0]["new_price"] == 79.99

    def test_store_commit_restock(self):
        from ecom_ops.data.store import MockStore
        store = MockStore()
        old_inv = store.get_inventory_record("SKU-003")
        old_stock = old_inv["stock_level"]
        store.commit_restock("SKU-003", 200, "critical")
        new_inv = store.get_inventory_record("SKU-003")
        assert new_inv["stock_level"] == old_stock + 200
