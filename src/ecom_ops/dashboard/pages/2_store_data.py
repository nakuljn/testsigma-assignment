"""Store data page — edit seed JSON and save to data/seed/."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ecom_ops.data.seed_io import (
    SEED_FILES,
    load_all_seed,
    load_seed_file,
    save_seed_file,
    validate_seed_file,
)

st.title("📦 Store seed data")
st.caption("Edits are saved to `data/seed/` and used on the next pipeline run.")

if "seed_catalog" not in st.session_state:
    st.session_state.seed_catalog = pd.DataFrame(load_seed_file("catalog.json"))
if "seed_inventory" not in st.session_state:
    st.session_state.seed_inventory = pd.DataFrame(load_seed_file("inventory.json"))
if "seed_sales_text" not in st.session_state:
    st.session_state.seed_sales_text = json.dumps(
        load_seed_file("sales_history.json"), indent=2
    )
if "seed_reviews_text" not in st.session_state:
    st.session_state.seed_reviews_text = json.dumps(
        load_seed_file("reviews.json"), indent=2
    )

tab_cat, tab_inv, tab_sales, tab_rev = st.tabs([
    "Catalog", "Inventory", "Sales history", "Reviews",
])

with tab_cat:
    st.session_state.seed_catalog = st.data_editor(
        st.session_state.seed_catalog,
        num_rows="dynamic",
        use_container_width=True,
        key="editor_catalog",
    )
    if st.button("Save catalog.json", key="save_cat"):
        data = st.session_state.seed_catalog.to_dict(orient="records")
        try:
            path = save_seed_file("catalog.json", data)
            st.success(f"Saved to {path}")
        except ValueError as e:
            st.error(str(e))

with tab_inv:
    st.session_state.seed_inventory = st.data_editor(
        st.session_state.seed_inventory,
        num_rows="dynamic",
        use_container_width=True,
        key="editor_inventory",
    )
    if st.button("Save inventory.json", key="save_inv"):
        data = st.session_state.seed_inventory.to_dict(orient="records")
        try:
            path = save_seed_file("inventory.json", data)
            st.success(f"Saved to {path}")
        except ValueError as e:
            st.error(str(e))

with tab_sales:
    st.session_state.seed_sales_text = st.text_area(
        "sales_history.json",
        value=st.session_state.seed_sales_text,
        height=400,
        key="editor_sales",
    )
    if st.button("Save sales_history.json", key="save_sales"):
        try:
            data = json.loads(st.session_state.seed_sales_text)
            errors = validate_seed_file("sales_history.json", data)
            if errors:
                st.error("\n".join(errors))
            else:
                path = save_seed_file("sales_history.json", data)
                st.success(f"Saved to {path}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

with tab_rev:
    st.session_state.seed_reviews_text = st.text_area(
        "reviews.json",
        value=st.session_state.seed_reviews_text,
        height=400,
        key="editor_reviews",
    )
    if st.button("Save reviews.json", key="save_rev"):
        try:
            data = json.loads(st.session_state.seed_reviews_text)
            errors = validate_seed_file("reviews.json", data)
            if errors:
                st.error("\n".join(errors))
            else:
                path = save_seed_file("reviews.json", data)
                st.success(f"Saved to {path}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

st.divider()
col_a, col_b = st.columns(2)
with col_a:
    if st.button("Reload from disk", use_container_width=True):
        seed = load_all_seed()
        st.session_state.seed_catalog = pd.DataFrame(seed["catalog.json"])
        st.session_state.seed_inventory = pd.DataFrame(seed["inventory.json"])
        st.session_state.seed_sales_text = json.dumps(seed["sales_history.json"], indent=2)
        st.session_state.seed_reviews_text = json.dumps(seed["reviews.json"], indent=2)
        st.rerun()
with col_b:
    st.info("Tip: lower stock on SKU-001 or add bad reviews on SKU-008 to trigger conflicts in the demo.")
