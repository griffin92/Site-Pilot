"""Estimator UI.

The editable unit-cost grid is the point of this screen. The AI's numbers are
a starting point, not an answer -- you overwrite them with your real
subcontractor pricing and the totals recompute in Python instantly.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import sp_projects as projects
import sp_compat as compat
import sp_estimate as estimate

COLS = ["division", "item", "quantity", "unit", "unit_cost", "confidence", "sheet", "basis"]


def _to_df(lines):
    df = pd.DataFrame(lines)
    for c in COLS:
        if c not in df.columns:
            df[c] = "" if c not in ("quantity", "unit_cost") else 0.0
    return df[COLS]


def _money(v):
    return f"${v:,.0f}"


def render(proj, file_bytes, drawing_index, scope_pages):
    pid = proj["id"]
    label_fn = lambda p: drawing_index.get(str(p), f"Page {p}")

    st.markdown('<div class="section-title">Cost Estimator</div>', unsafe_allow_html=True)
    st.markdown('<div class="module-tag">Module 08 — ROM Estimate</div>', unsafe_allow_html=True)
    st.caption("The AI proposes quantities and starting unit costs. Edit any rate below — "
               "all totals are calculated in Python from what you enter, never by the model.")

    # ---- Build or seed the line items -------------------------------------
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("Generate from Drawings", key="est_gen"):
            if not scope_pages:
                st.warning("Select sheets in the AI panel first.")
            else:
                lines, warns = estimate.generate_line_items(file_bytes, scope_pages, label_fn)
                if not lines:
                    st.error("No priceable scope came back. Try selecting plan and schedule "
                             "sheets rather than details or general notes.")
                else:
                    st.session_state.est_lines = lines
                    st.session_state.est_warnings = warns
                    st.rerun()
    with c2:
        prior_takeoff = (projects.latest_artifact(pid, "takeoff") or {}).get("payload")
        if st.button("Seed from Takeoff", key="est_seed", disabled=not prior_takeoff):
            st.session_state.est_lines = estimate.from_takeoff(prior_takeoff)
            st.session_state.est_warnings = ["Seeded from takeoff — unit costs start at $0, "
                                             "enter your own rates."]
            st.rerun()
        if not prior_takeoff:
            st.caption("Run a takeoff to enable")
    with c3:
        saved = projects.latest_artifact(pid, "estimate")
        if st.button("Load Last Estimate", key="est_load", disabled=not saved):
            st.session_state.est_lines = saved["payload"].get("lines", [])
            st.rerun()

    lines = st.session_state.get("est_lines")
    if not lines:
        st.info("Generate from drawings, or seed from a completed takeoff to start pricing.")
        return

    for w in st.session_state.get("est_warnings", []):
        st.warning(w)

    # ---- Assumptions -------------------------------------------------------
    st.divider()
    ca, cb = st.columns([1, 2])
    with ca:
        region = st.selectbox("Pricing region", list(estimate.REGIONS.keys()),
                              key="est_region_sel")
        st.caption(f"Factor: ×{estimate.REGIONS[region]:.2f}")
    with cb:
        st.markdown("**Markups (%)**")
        m1, m2, m3, m4 = st.columns(4)
        markups = {
            "general_conditions": m1.number_input("Gen. Cond.", 0.0, 40.0,
                                                  estimate.DEFAULT_MARKUPS["general_conditions"],
                                                  0.5, key="mk_gc"),
            "overhead": m2.number_input("Overhead", 0.0, 40.0,
                                        estimate.DEFAULT_MARKUPS["overhead"], 0.5, key="mk_oh"),
            "profit": m3.number_input("Profit", 0.0, 40.0,
                                      estimate.DEFAULT_MARKUPS["profit"], 0.5, key="mk_pr"),
            "contingency": m4.number_input("Contingency", 0.0, 40.0,
                                           estimate.DEFAULT_MARKUPS["contingency"], 0.5,
                                           key="mk_ct"),
        }

    # ---- The editable grid -------------------------------------------------
    st.markdown("**Line items** — edit any cell; add or delete rows as needed.")
    edited = st.data_editor(
        _to_df(lines),
        key="est_editor",
        **compat.stretch(),
        num_rows="dynamic",
        column_config={
            "division": st.column_config.TextColumn("Division", width="medium"),
            "item": st.column_config.TextColumn("Item", width="large"),
            "quantity": st.column_config.NumberColumn("Qty", format="%.2f", min_value=0.0),
            "unit": st.column_config.TextColumn("Unit", width="small"),
            "unit_cost": st.column_config.NumberColumn("Unit Cost", format="$%.2f",
                                                       min_value=0.0),
            "confidence": st.column_config.SelectboxColumn(
                "Conf.", options=["High", "Medium", "Low"], width="small"),
            "sheet": st.column_config.TextColumn("Sheet", width="small"),
            "basis": st.column_config.TextColumn("Basis", width="medium"),
        },
    )

    current = edited.fillna({"quantity": 0, "unit_cost": 0}).to_dict("records")
    result = estimate.compute(current, region=region, markups=markups)

    # ---- Rollup ------------------------------------------------------------
    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Direct cost", _money(result["direct"]))
    k2.metric("Markups", _money(result["gc_amt"] + result["oh_amt"] + result["profit_amt"]))
    k3.metric("Contingency", _money(result["contingency_amt"]))
    k4.metric("TOTAL", _money(result["total"]))

    with st.expander("Cost breakdown", expanded=False):
        st.markdown(
            f"| | Amount |\n|---|---:|\n"
            f"| Direct cost (regional ×{result['region_factor']:.2f}) | {_money(result['direct'])} |\n"
            f"| General conditions ({markups['general_conditions']}%) | {_money(result['gc_amt'])} |\n"
            f"| Overhead ({markups['overhead']}%) | {_money(result['oh_amt'])} |\n"
            f"| Profit ({markups['profit']}%) | {_money(result['profit_amt'])} |\n"
            f"| Contingency ({markups['contingency']}%) | {_money(result['contingency_amt'])} |\n"
            f"| **Total** | **{_money(result['total'])}** |"
        )
        st.caption("Markups compound in sequence: overhead applies to direct + general "
                   "conditions, profit to that subtotal, contingency to everything.")

    if result["by_division"]:
        st.markdown("**By division**")
        st.bar_chart(pd.DataFrame(
            {"Cost": list(result["by_division"].values())},
            index=list(result["by_division"].keys()),
        ))

    low = [l for l in result["lines"] if str(l.get("confidence", "")).lower() == "low"]
    if low:
        st.warning(f"{len(low)} low-confidence line item(s) — scope implied but not "
                   f"quantified on the drawings. Verify before relying on this number.")

    st.error("**ROM planning estimate.** Unit costs are model-proposed starting points "
             "unless you replaced them. Validate against current subcontractor pricing "
             "before submitting any number to a client.")

    # ---- Export ------------------------------------------------------------
    e1, e2 = st.columns([1, 1])
    with e1:
        st.download_button(
            "Download Estimate (.xlsx)",
            estimate.to_xlsx(result, proj),
            f"Estimate_{proj.get('number') or proj.get('name', 'project')}_"
            f"{datetime.now().strftime('%Y%m%d')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="est_dl",
        )
    with e2:
        st.markdown('<div class="btn-ghost">', unsafe_allow_html=True)
        if st.button("Save to project", key="est_save"):
            projects.save_artifact(pid, "estimate",
                                   {"lines": current, "region": region,
                                    "markups": markups, "total": result["total"]},
                                   label=f"{region} · {_money(result['total'])}")
            st.success("Saved.")
        st.markdown("</div>", unsafe_allow_html=True)
