"""Render vertical agent pipeline cards with status + log areas."""

from __future__ import annotations

import streamlit as st

from ecom_ops.dashboard.components.streamlit_observer import (
    NODE_TITLES,
    PIPELINE_NODES,
)


def build_agent_pipeline() -> tuple[dict, dict]:
    """
    Render agent cards and return (status_placeholders, log_placeholders)
    for StreamlitObserver to update live.
    """
    status_ph: dict = {}
    log_ph: dict = {}

    st.markdown("### Agent pipeline")
    st.caption("Inventory and Customer Insight run in parallel after seed load.")

    for node in PIPELINE_NODES:
        title = NODE_TITLES.get(node, node)
        with st.container(border=True):
            cols = st.columns([1, 3])
            with cols[0]:
                st.markdown(f"#### {title}")
                status_ph[node] = st.empty()
                status_ph[node].markdown("**⚪ Pending**")
            with cols[1]:
                st.markdown("**Log**")
                log_ph[node] = st.empty()
                log_ph[node].code("Waiting…", language=None)

    return status_ph, log_ph
