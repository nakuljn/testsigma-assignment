"""Results page — KPIs, conflict ledger, agent outputs, report."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ecom_ops.config.settings import OUTPUT_DIR

st.title("📊 Results")

if st.session_state.get("final_state") is None:
    existing = sorted(OUTPUT_DIR.glob("daily_ops_*.md"), reverse=True)
    if existing:
        st.info(
            f"No run in this session. Showing cached report: `{existing[0].name}`. "
            "Run the pipeline on the **Run** page for live results."
        )
        st.markdown(existing[0].read_text(encoding="utf-8"))
    else:
        st.info("No results yet. Go to **Run** and execute the pipeline.")
    st.stop()

state = st.session_state.final_state
restock = state.get("restock_decisions", [])
pricing = state.get("price_decisions", [])
issues = state.get("product_issues", [])
campaigns = state.get("campaign_drafts", [])
conflicts = state.get("conflicts", [])
committed = state.get("committed_changes", [])
report_md = state.get("report_markdown", "")

active_campaigns = [c for c in campaigns if not c.suppressed]
suppressed_campaigns = [c for c in campaigns if c.suppressed]

st.subheader(f"Run: {state.get('run_date', str(date.today()))}")
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Restock Orders", len(restock))
col2.metric("Price Changes", len(pricing))
col3.metric("Product Issues", len(issues),
            delta=f"{sum(1 for i in issues if i.severity == 'high')} high",
            delta_color="inverse")
col4.metric("Campaigns Active", len(active_campaigns))
col5.metric("Campaigns Suppressed", len(suppressed_campaigns),
            delta_color="inverse" if suppressed_campaigns else "off")
col6.metric("Conflicts Resolved", len(conflicts))

st.divider()
st.subheader("Conflict ledger")
if conflicts:
    rows = [{
        "SKU": c.sku,
        "Conflict Type": c.kind,
        "Agents": " vs ".join(c.competing),
        "Resolution": c.resolution,
        "Winning Action": c.winning_action,
    } for c in conflicts]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.success("No conflicts — all agent decisions were consistent.")

st.divider()
tab_restock, tab_pricing, tab_issues, tab_campaigns, tab_committed, tab_report = st.tabs([
    f"Restocking ({len(restock)})",
    f"Pricing ({len(pricing)})",
    f"Product Issues ({len(issues)})",
    f"Campaigns ({len(campaigns)})",
    f"Committed ({len(committed)})",
    "Full Report",
])

with tab_restock:
    if restock:
        for d in restock:
            with st.expander(f"**{d.sku}** — order {d.recommended_qty} units `{d.urgency}`"):
                st.caption(d.rationale)
    else:
        st.info("No restocking required.")

with tab_pricing:
    if pricing:
        for d in pricing:
            direction = "▲" if d.new_price > d.old_price else "▼"
            with st.expander(f"{direction} **{d.sku}** ${d.old_price:.2f} → ${d.new_price:.2f}"):
                st.caption(d.rationale)
    else:
        st.info("No pricing changes.")

with tab_issues:
    if issues:
        for issue in issues:
            with st.expander(f"**{issue.sku}** — {issue.issue_type} `{issue.severity}`"):
                st.caption(issue.rationale)
                for ev in issue.evidence or []:
                    st.write(f"- \"{ev}\"")
    else:
        st.success("No product issues.")

with tab_campaigns:
    if active_campaigns:
        st.write("#### Active")
        for d in active_campaigns:
            with st.expander(f"**{d.sku}** [{d.channel}]"):
                st.write(d.subject)
                st.write(d.body)
    if suppressed_campaigns:
        st.write("#### Suppressed")
        for d in suppressed_campaigns:
            st.warning(f"**{d.sku}** — {d.suppression_reason}")

with tab_committed:
    if committed:
        st.dataframe(pd.DataFrame(committed), use_container_width=True, hide_index=True)
    else:
        st.info("No committed changes.")

with tab_report:
    st.markdown(report_md)
    st.download_button(
        "Download report",
        data=report_md,
        file_name=f"daily_ops_{state.get('run_date', str(date.today()))}.md",
        mime="text/markdown",
    )
