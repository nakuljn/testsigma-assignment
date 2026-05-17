"""
Agentic E-Commerce Ops — Streamlit interviewer demo.

Run: make dashboard
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

_DASHBOARD_DIR = Path(__file__).parent

st.set_page_config(
    page_title="E-Com Ops Manager",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "final_state" not in st.session_state:
    st.session_state.final_state = None
if "run_error" not in st.session_state:
    st.session_state.run_error = None

pages = [
    st.Page(
        str(_DASHBOARD_DIR / "pages" / "1_run.py"),
        title="Run",
        icon="▶️",
        default=True,
    ),
    st.Page(
        str(_DASHBOARD_DIR / "pages" / "2_store_data.py"),
        title="Store data",
        icon="📦",
    ),
    st.Page(
        str(_DASHBOARD_DIR / "pages" / "3_results.py"),
        title="Results",
        icon="📊",
    ),
]

pg = st.navigation(pages)
pg.run()
