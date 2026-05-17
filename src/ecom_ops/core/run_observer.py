"""Pluggable observers for pipeline runs (CLI stdout, Streamlit UI, tests)."""

from __future__ import annotations

import contextvars
from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class RunObserver(Protocol):
    def on_node_start(self, node: str) -> None: ...
    def on_node_end(self, node: str, summary: str = "") -> None: ...
    def on_log(self, node: str, message: str) -> None: ...
    def on_error(self, node: str, error: str) -> None: ...


_observer_var: contextvars.ContextVar[Optional[RunObserver]] = contextvars.ContextVar(
    "run_observer", default=None
)
_agent_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_agent", default=None
)


def get_observer() -> Optional[RunObserver]:
    return _observer_var.get()


def set_observer(observer: Optional[RunObserver]) -> contextvars.Token:
    return _observer_var.set(observer)


def reset_observer(token: contextvars.Token) -> None:
    _observer_var.reset(token)


def get_current_agent() -> Optional[str]:
    return _agent_var.get()


def set_current_agent(agent: Optional[str]) -> contextvars.Token:
    return _agent_var.set(agent)


def reset_current_agent(token: contextvars.Token) -> None:
    _agent_var.reset(token)


class PrintObserver:
    """Default CLI observer — prints to stdout."""

    def on_node_start(self, node: str) -> None:
        print(f"→ {node} started", flush=True)

    def on_node_end(self, node: str, summary: str = "") -> None:
        suffix = f" — {summary}" if summary else ""
        print(f"✓ {node} complete{suffix}", flush=True)

    def on_log(self, node: str, message: str) -> None:
        print(message, flush=True)

    def on_error(self, node: str, error: str) -> None:
        print(f"✗ {node} error: {error}", flush=True)


class CollectingObserver:
    """In-memory observer for tests."""

    def __init__(self) -> None:
        self.logs: dict[str, list[str]] = {}
        self.node_starts: list[str] = []
        self.node_ends: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def on_node_start(self, node: str) -> None:
        self.node_starts.append(node)

    def on_node_end(self, node: str, summary: str = "") -> None:
        self.node_ends.append((node, summary))

    def on_log(self, node: str, message: str) -> None:
        self.logs.setdefault(node, []).append(message)

    def on_error(self, node: str, error: str) -> None:
        self.errors.append((node, error))


def _summarize_node_output(node: str, output: dict[str, Any]) -> str:
    if node == "inventory_agent":
        n = len(output.get("restock_decisions", []))
        return f"{n} restock decision(s)"
    if node == "customer_insight_agent":
        n = len(output.get("product_issues", []))
        return f"{n} product issue(s)"
    if node == "pricing_agent":
        n = len(output.get("price_decisions", []))
        return f"{n} price change(s)"
    if node == "marketing_agent":
        drafts = output.get("campaign_drafts", [])
        active = sum(1 for d in drafts if not getattr(d, "suppressed", False))
        return f"{active} active campaign(s), {len(drafts)} total"
    if node == "orchestrator":
        n = len(output.get("conflicts", []))
        return f"{n} conflict(s) resolved, report written"
    return ""
