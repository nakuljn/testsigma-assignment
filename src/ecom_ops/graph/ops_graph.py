"""
LangGraph wiring for the Agentic E-Commerce Ops system.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from langgraph.graph import StateGraph, END

from ecom_ops.core.state import OpsState
from ecom_ops.agents.inventory_agent import run_inventory_agent
from ecom_ops.agents.customer_insight_agent import run_customer_insight_agent
from ecom_ops.agents.pricing_agent import run_pricing_agent
from ecom_ops.agents.marketing_agent import run_marketing_agent
from ecom_ops.agents.orchestrator import run_orchestrator
from ecom_ops.data.store import MockStore
from ecom_ops.core.progress import progress
from ecom_ops.core.run_observer import (
    PrintObserver,
    RunObserver,
    _summarize_node_output,
    get_observer,
    reset_current_agent,
    reset_observer,
    set_current_agent,
    set_observer,
)

_NODE_LABELS = {
    "seed": "Initialising",
    "inventory_agent": "Inventory",
    "customer_insight_agent": "Customer Insight",
    "pricing_agent": "Pricing",
    "marketing_agent": "Marketing",
    "orchestrator": "Orchestrator",
}

_PIPELINE_NODES = (
    "inventory_agent",
    "customer_insight_agent",
    "pricing_agent",
    "marketing_agent",
    "orchestrator",
)


def _apply_fast_env(fast: bool) -> None:
    if fast:
        os.environ["SKIP_WEB_SEARCH"] = "1"
        os.environ["BATCH_LLM"] = "1"


async def _wrap_node(node: str, fn, state: OpsState) -> dict:
    observer = get_observer()
    agent_token = set_current_agent(node)
    if observer:
        observer.on_node_start(node)
    try:
        result = await fn(state)
        if observer:
            observer.on_node_end(node, _summarize_node_output(node, result))
        return result
    except Exception as exc:
        if observer:
            observer.on_error(node, str(exc))
        raise
    finally:
        reset_current_agent(agent_token)


def build_graph(store: MockStore | None = None) -> Any:
    if store is None:
        store = MockStore()

    async def inventory_node(state: OpsState) -> dict:
        return await _wrap_node("inventory_agent", run_inventory_agent, state)

    async def customer_insight_node(state: OpsState) -> dict:
        return await _wrap_node("customer_insight_agent", run_customer_insight_agent, state)

    async def pricing_node(state: OpsState) -> dict:
        return await _wrap_node("pricing_agent", run_pricing_agent, state)

    async def marketing_node(state: OpsState) -> dict:
        return await _wrap_node("marketing_agent", run_marketing_agent, state)

    async def orchestrator_node(state: OpsState) -> dict:
        async def _run_orch(s: OpsState) -> dict:
            return await run_orchestrator(s, store=store)

        return await _wrap_node("orchestrator", _run_orch, state)

    graph = StateGraph(OpsState)

    graph.add_node("inventory_agent", inventory_node)
    graph.add_node("customer_insight_agent", customer_insight_node)
    graph.add_node("pricing_agent", pricing_node)
    graph.add_node("marketing_agent", marketing_node)
    graph.add_node("orchestrator", orchestrator_node)

    graph.add_node("seed", lambda state: {})
    graph.set_entry_point("seed")
    graph.add_edge("seed", "inventory_agent")
    graph.add_edge("seed", "customer_insight_agent")
    graph.add_edge("inventory_agent", "pricing_agent")
    graph.add_edge("customer_insight_agent", "pricing_agent")
    graph.add_edge("pricing_agent", "marketing_agent")
    graph.add_edge("marketing_agent", "orchestrator")
    graph.add_edge("orchestrator", END)

    return graph.compile()


async def run_daily_cycle(
    run_date: str | None = None,
    store: MockStore | None = None,
    observer: Optional[RunObserver] = None,
    fast: bool = False,
) -> OpsState:
    """
    Load seed data, build the graph, run one full daily cycle.
    Returns the final OpsState.
    """
    from datetime import date as dt
    from ecom_ops.core.state import empty_state

    _apply_fast_env(fast)

    if store is None:
        store = MockStore()
    run_date = run_date or str(dt.today())

    obs = observer if observer is not None else PrintObserver()
    obs_token = set_observer(obs)

    initial_state = empty_state(run_date)
    initial_state["catalog"] = store.get_catalog()
    initial_state["inventory"] = store.get_inventory()
    initial_state["sales_history"] = store.get_sales_history()
    initial_state["reviews"] = store.get_reviews()

    graph = build_graph(store=store)

    progress("Loading seed data — done", agent="system")
    progress(
        "Running pipeline "
        f"({'fast: batched LLM, no web search' if fast else 'full mode'})…",
        agent="system",
    )

    final_state = dict(initial_state)
    try:
        async for event in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "seed":
                    continue
                final_state.update(node_output)
    finally:
        reset_observer(obs_token)

    return final_state  # type: ignore[return-value]
