"""Progress logging — routes to RunObserver when set, else stdout."""

from __future__ import annotations

import os
import re

from ecom_ops.core.run_observer import get_current_agent, get_observer

_AGENT_FROM_MSG = re.compile(r"\[(\w+)\]")


def _infer_agent(message: str) -> str:
    m = _AGENT_FROM_MSG.search(message)
    if m:
        name = m.group(1)
        mapping = {
            "inventory": "inventory_agent",
            "customer_insight": "customer_insight_agent",
            "pricing": "pricing_agent",
            "marketing": "marketing_agent",
            "orchestrator": "orchestrator",
        }
        return mapping.get(name, name)
    return "system"


def progress(message: str, agent: str | None = None) -> None:
    """Emit a progress line to the active observer or stdout."""
    if os.getenv("OPS_QUIET", "").lower() in ("1", "true", "yes"):
        return

    node = agent or get_current_agent() or _infer_agent(message)
    # Strip redundant agent prefix for UI display when already in agent card
    display = message.strip()
    obs = get_observer()
    if obs is not None:
        obs.on_log(node, display)
    else:
        print(message, flush=True)
