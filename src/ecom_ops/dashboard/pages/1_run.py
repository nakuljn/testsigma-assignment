"""Run page — live agent pipeline + controls."""

from __future__ import annotations

import asyncio
import os
from datetime import date

import streamlit as st

from ecom_ops.dashboard.components.agent_pipeline import build_agent_pipeline
from ecom_ops.dashboard.components.streamlit_observer import StreamlitObserver
from ecom_ops.graph.ops_graph import run_daily_cycle

st.title("▶ Run daily ops cycle")

if "final_state" not in st.session_state:
    st.session_state.final_state = None
if "run_error" not in st.session_state:
    st.session_state.run_error = None

with st.sidebar:
    st.subheader("Run settings")
    provider = st.selectbox("LLM provider", ["openai", "anthropic"], index=0)
    run_date = st.date_input("Run date", value=date.today())
    fast_mode = st.checkbox(
        "Fast mode",
        value=True,
        help="Batched LLM (~5 API calls) + no web search. Best for live demos.",
    )
    run_btn = st.button("Run pipeline", type="primary", use_container_width=True)
    st.caption("Requires OPENAI_API_KEY or ANTHROPIC_API_KEY in .env")

status_ph, log_ph = build_agent_pipeline()

if run_btn:
    st.session_state.run_error = None
    os.environ["MODEL_PROVIDER"] = provider
    if fast_mode:
        os.environ["SKIP_WEB_SEARCH"] = "1"
        os.environ["BATCH_LLM"] = "1"
    else:
        os.environ.pop("SKIP_WEB_SEARCH", None)
        os.environ.pop("BATCH_LLM", None)

    observer = StreamlitObserver(status_ph, log_ph)

    with st.spinner("Executing pipeline…"):
        try:
            final_state = asyncio.run(
                run_daily_cycle(
                    str(run_date),
                    observer=observer,
                    fast=fast_mode,
                )
            )
            st.session_state.final_state = final_state
            st.success("Pipeline complete — open **Results** in the sidebar.")
        except Exception as exc:
            st.session_state.run_error = str(exc)
            st.session_state.final_state = None
            st.error(f"Run failed: {exc}")

if st.session_state.run_error:
    st.error(st.session_state.run_error)

if st.session_state.final_state:
    state = st.session_state.final_state
    st.divider()
    st.markdown("### Quick summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Restock", len(state.get("restock_decisions", [])))
    c2.metric("Price changes", len(state.get("price_decisions", [])))
    c3.metric("Issues", len(state.get("product_issues", [])))
    c4.metric("Conflicts", len(state.get("conflicts", [])))
