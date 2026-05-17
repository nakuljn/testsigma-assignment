"""Streamlit RunObserver — live-updates agent cards during pipeline execution."""

from __future__ import annotations

from typing import Any

PIPELINE_NODES = (
    "inventory_agent",
    "customer_insight_agent",
    "pricing_agent",
    "marketing_agent",
    "orchestrator",
)

NODE_TITLES = {
    "inventory_agent": "Inventory Agent",
    "customer_insight_agent": "Customer Insight Agent",
    "pricing_agent": "Pricing Agent",
    "marketing_agent": "Marketing Agent",
    "orchestrator": "Orchestrator",
}


class StreamlitObserver:
    """Updates Streamlit placeholders when graph nodes emit events."""

    def __init__(
        self,
        status_placeholders: dict[str, Any],
        log_placeholders: dict[str, Any],
    ) -> None:
        self.status_placeholders = status_placeholders
        self.log_placeholders = log_placeholders
        self.logs: dict[str, list[str]] = {n: [] for n in PIPELINE_NODES}
        self.running: set[str] = set()
        self.done: set[str] = set()
        self.summaries: dict[str, str] = {}
        self.errors: dict[str, str] = {}

    def on_node_start(self, node: str) -> None:
        if node == "seed":
            return
        self.running.add(node)
        self._render_status(node)

    def on_node_end(self, node: str, summary: str = "") -> None:
        if node == "seed":
            return
        self.running.discard(node)
        self.done.add(node)
        if summary:
            self.summaries[node] = summary
        self._render_status(node)

    def on_log(self, node: str, message: str) -> None:
        if node == "system":
            return
        if node not in self.logs:
            self.logs[node] = []
        self.logs[node].append(message)
        text = "\n".join(self.logs[node][-100:]) or "Waiting for logs…"
        if node in self.log_placeholders:
            self.log_placeholders[node].code(text, language=None)

    def on_error(self, node: str, error: str) -> None:
        self.errors[node] = error
        self.running.discard(node)
        self._render_status(node)
        if node in self.log_placeholders:
            self.log_placeholders[node].error(error)

    def _render_status(self, node: str) -> None:
        if node not in self.status_placeholders:
            return
        if node in self.errors:
            badge = f"🔴 Error — {self.errors[node]}"
        elif node in self.running:
            badge = "🟡 Running…"
        elif node in self.done:
            summary = self.summaries.get(node, "")
            badge = f"🟢 Complete{f' — {summary}' if summary else ''}"
        else:
            badge = "⚪ Pending"
        self.status_placeholders[node].markdown(f"**{badge}**")
