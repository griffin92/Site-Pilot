"""The AI drawer -- lives in Streamlit's native (collapsible) sidebar so the
drawing surface owns the main canvas.

Design note: the sidebar collapses natively via the chevron, which is exactly
the Procore-style behaviour wanted -- drawings full-bleed when you're reading
them, AI a click away when you need it.
"""
from datetime import datetime, timedelta

import streamlit as st

import sp_ai as ai
import sp_projects as projects
import sp_analysis as analysis
import sp_qa as qa
import sp_schedule as schedule
import sp_suggestions as suggestions
import sp_viewer as viewer


def _sheet_scope(proj, drawing_index):
    """Which sheets the engines run against. Defaults to the sheet you're
    looking at, since that's usually the intent."""
    pages = sorted(int(k) for k in drawing_index.keys())
    if not pages:
        return []

    mode = st.radio(
        "Scope",
        ["Current sheet", "Choose sheets", "Entire set"],
        key="ai_scope", horizontal=False, label_visibility="collapsed",
    )
    if mode == "Current sheet":
        cur = st.session_state.get("active_sheet", pages[0])
        return [cur]
    if mode == "Entire set":
        return pages

    _, labels, label_to_page = viewer.sheet_labels(drawing_index)
    picked = st.multiselect("Sheets", labels, key="ai_sheet_pick",
                            label_visibility="collapsed")
    return [label_to_page[l] for l in picked if l in label_to_page]


def render(proj, file_bytes, drawing_index):
    pid = proj["id"]
    label_fn = lambda p: drawing_index.get(str(p), f"Page {p}")

    st.markdown("## AI Engines")
    st.caption(proj.get("name", "")[:34])
    st.divider()

    scope = _sheet_scope(proj, drawing_index)
    if scope:
        st.caption(f"{len(scope)} sheet{'s' if len(scope) != 1 else ''} in scope")
    st.divider()

    tab_ask, tab_scan, tab_plan = st.tabs(["Ask", "Scan", "Plan"])

    # ---------------------------------------------------------------- ASK
    with tab_ask:
        st.markdown("**Ask the Drawings**")
        indexed = qa.routing_available(drawing_index, sorted(int(k) for k in drawing_index.keys()))
        smart = st.checkbox("Smart routing", value=indexed, disabled=not indexed,
                            help="Finds the sheets likely to hold the answer before reading "
                                 "them. Needs the Sheet Indexer to have run.")
        if not indexed:
            st.caption("Run the Sheet Indexer to enable routing.")

        with st.form("qa_form", clear_on_submit=True):
            question = st.text_area("Question", height=80,
                                    placeholder="Dimensions of the walk-in cooler?",
                                    label_visibility="collapsed")
            asked = st.form_submit_button("Ask")

        if asked and question.strip():
            all_pages = sorted(int(k) for k in drawing_index.keys())
            search = scope or all_pages
            if smart and indexed:
                routed = qa.select_relevant_sheets(question, drawing_index, search)
                if routed:
                    search = routed
            answer = qa.ask(file_bytes, search, question.strip(), drawing_index,
                            st.session_state.get("qa_history", []))
            st.session_state.setdefault("qa_history", []).append({
                "time": datetime.now().strftime("%I:%M %p"),
                "q": question.strip(), "a": answer,
                "sheets": ", ".join(label_fn(p) for p in search),
            })
            projects.save_artifact(pid, "qa", {"q": question.strip(), "a": answer})
            st.rerun()

        for turn in reversed(st.session_state.get("qa_history", [])[-6:]):
            with st.expander(turn["q"][:44], expanded=False):
                st.markdown(turn["a"])
                st.caption(turn["sheets"][:70])

    # --------------------------------------------------------------- SCAN
    with tab_scan:
        if not scope:
            st.caption("Select sheets above to enable scanning.")
        else:
            if st.button("Clash Audit", key="run_clash"):
                findings, warns = analysis.clash_audit(file_bytes, scope, label_fn)
                projects.save_artifact(pid, "audit", findings, f"{len(scope)} sheets")
                st.session_state.last_audit = findings
                st.session_state.audit_warnings = warns
                st.session_state.audit_ran = True
                st.rerun()

            if st.button("Material Takeoff", key="run_takeoff"):
                items, warns = analysis.takeoff(file_bytes, scope, label_fn)
                projects.save_artifact(pid, "takeoff", items, f"{len(scope)} sheets")
                st.session_state.last_takeoff = items
                st.session_state.takeoff_warnings = warns
                st.session_state.takeoff_ran = True
                st.rerun()

        st.caption("Cost estimating lives in the Estimator tab on the main canvas.")

        # ---- Audit results ----
        audit = st.session_state.get("last_audit")
        if audit is None:
            audit = (projects.latest_artifact(pid, "audit") or {}).get("payload")
        for w in st.session_state.get("audit_warnings", []):
            st.warning(w)
        if audit is not None:
            if not audit:
                # Distinguish "found nothing" from "silently broke" -- the old
                # version showed an empty panel for both.
                if st.session_state.get("audit_ran"):
                    st.success("Audit complete — no qualifying issues found on those sheets.")
            else:
                sev_counts = {}
                for f in audit:
                    s = str(f.get("severity", "—"))
                    sev_counts[s] = sev_counts.get(s, 0) + 1
                summary = " · ".join(f"{v} {k}" for k, v in sev_counts.items())
                with st.expander(f"Audit — {len(audit)} findings ({summary})", expanded=False):
                    for f in audit[:30]:
                        sev = str(f.get("severity", "")).lower()
                        mark = {"critical": "▲", "high": "▲", "medium": "■"}.get(sev, "·")
                        st.markdown(
                            f"**{mark} {f.get('severity','')} · {f.get('category','')}**  \n"
                            f"{f.get('issue','')}  \n"
                            f"<span style='opacity:.65;font-size:.85em'>"
                            f"{f.get('sheets','')} — {f.get('impact','')}</span>",
                            unsafe_allow_html=True)
                        st.markdown("---")

        # ---- Takeoff results ----
        takeoff = st.session_state.get("last_takeoff")
        if takeoff is None:
            takeoff = (projects.latest_artifact(pid, "takeoff") or {}).get("payload")
        for w in st.session_state.get("takeoff_warnings", []):
            st.warning(w)
        if takeoff is not None:
            if not takeoff:
                if st.session_state.get("takeoff_ran"):
                    st.info("Takeoff complete — nothing quantifiable on those sheets. "
                            "Plan and schedule sheets work better than details.")
            else:
                with st.expander(f"Takeoff — {len(takeoff)} items", expanded=False):
                    for div, rows in analysis.group_by_division(takeoff).items():
                        st.markdown(f"**{div}**")
                        for r in rows[:20]:
                            flag = "" if str(r.get("basis", "")).upper() == "LABELED" else " ⚠"
                            st.markdown(
                                f"- {r.get('quantity'):,.0f} {r.get('unit','')} — "
                                f"{r.get('item','')}{flag}  \n"
                                f"<span style='opacity:.6;font-size:.8em'>"
                                f"{r.get('material','')} · {r.get('sheet','')}</span>",
                                unsafe_allow_html=True)
                    st.caption("⚠ = quantity derived, not read directly off the drawing")

    # --------------------------------------------------------------- PLAN
    with tab_plan:
        st.markdown("**Timeline**")
        start = st.date_input("Project start", value=datetime.now().date(), key="sched_start")

        use_target = st.checkbox("Work to a deadline", key="use_target",
                                 help="Sequence the schedule toward a fixed duration. "
                                      "Leave off for an unconstrained timeline.")
        target_weeks = None
        if use_target:
            target_weeks = st.number_input(
                "Target duration (weeks)", min_value=1, max_value=260, value=12, step=1,
                key="target_weeks",
                help="Substantial completion within this many weeks of the start date.",
            )
            finish_by = start + timedelta(weeks=int(target_weeks))
            st.caption(f"Finish by {finish_by.strftime('%b %d, %Y')} "
                       f"({int(target_weeks) * 5} working days)")

        if st.button("Generate Timeline", key="run_timeline"):
            if not scope:
                st.warning("Select sheets first.")
            else:
                res = schedule.generate_timeline(file_bytes, scope, start,
                                                 target_weeks=target_weeks, label_fn=label_fn)
                projects.save_artifact(pid, "timeline", res,
                                       f"{start.strftime('%m/%d/%Y')}"
                                       + (f" · {int(target_weeks)}wk target" if target_weeks else ""))
                st.session_state.last_timeline = res
                st.session_state.timeline_target = int(target_weeks) if target_weeks else None
                st.rerun()

        timeline = st.session_state.get("last_timeline") or \
            (projects.latest_artifact(pid, "timeline") or {}).get("payload")

        if timeline:
            with st.expander("Timeline", expanded=False):
                st.markdown(timeline)

            if st.button("Build Gantt (.xlsx)", key="run_gantt"):
                with st.spinner("Filling your Gantt template..."):
                    try:
                        tasks = schedule.extract_tasks(timeline)
                        if not tasks:
                            st.error("Couldn't extract tasks from the timeline.")
                        else:
                            data, truncated = schedule.fill_gantt(start, tasks)
                            st.session_state.gantt_bytes = data
                            st.session_state.gantt_summary = schedule.duration_summary(start, tasks)
                            if truncated:
                                st.warning("More tasks than the template's 50 rows — "
                                           "truncated. Group smaller tasks together.")
                    except Exception as e:
                        st.error(f"Gantt build failed: {e}")
                    st.rerun()

            # Target vs. what the dates actually compute to. The AI proposes
            # durations; only this arithmetic says whether they land in time.
            summary = st.session_state.get("gantt_summary")
            if summary:
                tgt = st.session_state.get("timeline_target")
                st.caption(f"Scheduled finish: **{summary['finish'].strftime('%b %d, %Y')}** — "
                           f"{summary['weeks']:.1f} weeks, {summary['task_count']} tasks")
                if tgt:
                    delta = summary["weeks"] - tgt
                    if delta <= 0.5:
                        st.success(f"Fits the {tgt}-week target "
                                   f"({abs(delta):.1f} weeks of float).")
                    elif delta <= 2:
                        st.warning(f"Runs {delta:.1f} weeks past the {tgt}-week target.")
                    else:
                        st.error(f"Runs {delta:.1f} weeks past the {tgt}-week target — "
                                 f"the deadline is not achievable as sequenced. Check the "
                                 f"timeline for a SCHEDULE FEASIBILITY note.")

            if st.session_state.get("gantt_bytes"):
                st.download_button(
                    "Download Gantt", st.session_state.gantt_bytes,
                    "Project_Schedule.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_gantt",
                )

        st.divider()
        st.markdown("**Two-Week Look-Ahead**")
        st.caption("Reconciles the drawings and schedule against what your photos show.")
        notes = st.text_area("Field notes (optional)", height=68, key="look_notes",
                             placeholder="Weather delay Tues-Wed, steel arriving Friday")

        if st.button("Build Look-Ahead", key="run_look"):
            photo_review = (projects.latest_artifact(pid, "photo_review") or {}).get("payload", "")
            if not (timeline or photo_review):
                st.warning("Generate a timeline or analyze photos first.")
            else:
                res = suggestions.two_week_lookahead(
                    photo_observations=photo_review,
                    schedule_context=timeline or "",
                    today_label=datetime.now().strftime("%B %d, %Y"),
                    extra_notes=notes,
                )
                projects.save_artifact(pid, "lookahead", res)
                st.session_state.last_lookahead = res
                st.rerun()

        look = st.session_state.get("last_lookahead") or \
            (projects.latest_artifact(pid, "lookahead") or {}).get("payload")
        if look:
            with st.expander("Look-ahead", expanded=True):
                st.markdown(look)
