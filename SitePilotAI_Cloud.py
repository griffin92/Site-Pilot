"""Site Pilot — construction field intelligence.

Layout intent: the drawing owns the main canvas; AI lives in the collapsible
sidebar. Project selection sits in a title block across the top, the way a
real sheet is identified.
"""
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Site Pilot", layout="wide",
                   page_icon="■", initial_sidebar_state="expanded")

from sp_config import THEME_CSS
import sp_ai as ai
import sp_firebase as firebase
import sp_projects as projects
import sp_analysis as analysis
import sp_ai_panel as ai_panel
import sp_estimator as estimator
import sp_photos as photos
import sp_rfi_panel as rfi_panel
import sp_viewer as viewer

st.markdown(THEME_CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers

def _title_block(proj, sheet_count, live):
    pill = ('<span class="pill pill-live">Cloud</span>' if live
            else '<span class="pill pill-local">Session</span>')
    st.markdown(f"""
        <div class="title-block">
            <div class="tb-field tb-brand"><div class="tb-value">SP</div></div>
            <div class="tb-field"><div class="tb-label">Project</div>
                <div class="tb-value">{proj.get('name','—')}</div></div>
            <div class="tb-field"><div class="tb-label">Number</div>
                <div class="tb-value">{proj.get('number') or '—'}</div></div>
            <div class="tb-field"><div class="tb-label">Sheets</div>
                <div class="tb-value">{sheet_count or '—'}</div></div>
            <div class="tb-field"><div class="tb-label">Date</div>
                <div class="tb-value">{datetime.now().strftime('%m.%d.%Y')}</div></div>
            <div class="tb-field"><div class="tb-label">Sync</div>
                <div class="tb-value">{pill}</div></div>
        </div>
    """, unsafe_allow_html=True)


def _project_gate():
    """Landing: pick an existing project or create one."""
    st.markdown("""
        <div style="text-align:center;padding:56px 20px 30px;">
            <div class="hero-eyebrow">Field Intelligence System</div>
            <h1 class="hero-title">Site Pilot</h1>
            <p class="hero-sub">Select a project to pick up where you left off,
            or start a new one.</p>
        </div>
    """, unsafe_allow_html=True)

    if not firebase.is_live():
        st.info(f"**{firebase.status_note()}** — the app works fully, but projects "
                f"won't persist after you close it. See SETUP.md to connect Firebase.")

    existing = projects.list_projects()
    c_left, c_right = st.columns([1, 1], gap="large")

    with c_left:
        st.markdown('<div class="tool-card">', unsafe_allow_html=True)
        st.markdown('<div class="module-tag">Open Project</div>', unsafe_allow_html=True)
        if existing:
            # Enumerate-prefixed so two projects sharing a name can't collide
            labels = [f"{p.get('name','Untitled')}"
                      f"{'  ·  #' + p['number'] if p.get('number') else ''}"
                      f"  ·  {p.get('sheet_count', 0)} sheets"
                      for p in existing]
            seen = {}
            for i, l in enumerate(labels):
                if l in seen:
                    labels[i] = f"{l}  ({i + 1})"
                seen[labels[i]] = i
            pick = st.selectbox("Project", labels, label_visibility="collapsed")
            chosen = existing[seen[pick]]
            if st.button("Open", key="open_proj"):
                st.session_state.active_project = chosen
                st.rerun()
            st.caption(f"Last updated {chosen.get('updated','')[:10]}")
        else:
            st.caption("No saved projects yet.")
        st.markdown("</div>", unsafe_allow_html=True)

    with c_right:
        st.markdown('<div class="tool-card">', unsafe_allow_html=True)
        st.markdown('<div class="module-tag">New Project</div>', unsafe_allow_html=True)
        with st.form("new_proj"):
            name = st.text_input("Project name", placeholder="Riverside Commons Tenant Fit-Out")
            cc1, cc2 = st.columns(2)
            with cc1:
                number = st.text_input("Project number", placeholder="2026-014")
            with cc2:
                client = st.text_input("Client", placeholder="Riverside Holdings")
            location = st.text_input("Location", placeholder="1200 Market St, Wilmington DE")
            if st.form_submit_button("Create") and name.strip():
                pid = projects.create_project(name, number, client, location)
                st.session_state.active_project = projects.get_project(pid)
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


def _drawing_setup(proj):
    """Shown when a project has no drawings loaded this session."""
    pid = proj["id"]
    st.markdown('<div class="tool-card">', unsafe_allow_html=True)
    st.markdown('<div class="module-tag">Load Drawings</div>', unsafe_allow_html=True)

    stored = proj.get("pdf_name")
    if stored and firebase.has_storage():
        st.caption(f"On file: {stored}")
        if st.button("Load saved drawings", key="load_stored"):
            with st.spinner("Retrieving drawing set..."):
                data = projects.load_pdf(pid)
            if data:
                st.session_state.file_bytes = data
                st.rerun()
            else:
                st.error("Couldn't retrieve the stored file. Re-upload below.")
    elif stored:
        st.caption(f"Last used: {stored} — re-upload it (cloud storage not connected).")

    up = st.file_uploader("Drawing set (.pdf)", type=["pdf"], key="dwg_up")
    if up:
        data = up.read()
        st.session_state.file_bytes = data
        with st.spinner("Saving to project..."):
            projects.save_pdf(pid, data, up.name)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _ensure_index(proj, file_bytes):
    """Index once per project, then never again — this is the whole point of
    project persistence."""
    pid = proj["id"]
    index = proj.get("drawing_index") or {}
    total = ai.page_count(file_bytes)

    if index and len(index) == total:
        return index

    if not index:
        index = {str(i): f"Page {i}" for i in range(1, total + 1)}
        projects.save_drawing_index(pid, index)

    named = sum(1 for v in index.values()
                if not str(v).strip().lower().startswith("page "))
    if named < total * 0.5:
        st.markdown('<div class="tool-card">', unsafe_allow_html=True)
        st.markdown('<div class="module-tag">Sheet Indexer</div>', unsafe_allow_html=True)
        st.caption("Reads each title block to name your sheets. Runs once per project — "
                   "after this, sheets are named everywhere and AI questions can be routed "
                   "to the right sheet automatically.")
        if st.button(f"Index {total} sheets", key="run_index"):
            bar = st.progress(0)
            note = st.empty()

            def cb(i, tot):
                bar.progress(int(i / tot * 100))
                note.caption(f"Reading title block {i} of {tot}")

            new_index = analysis.build_index(file_bytes, total, cb)
            projects.save_drawing_index(pid, new_index)
            st.session_state.active_project["drawing_index"] = new_index
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    return index


# --------------------------------------------------------------------- main

proj = st.session_state.get("active_project")

if not proj:
    _project_gate()
    st.stop()

# refresh from store so persisted fields (index, counters) are current
fresh = projects.get_project(proj["id"])
if fresh:
    proj = fresh
    st.session_state.active_project = proj

file_bytes = st.session_state.get("file_bytes")

# Top bar
_title_block(proj, proj.get("sheet_count", 0), firebase.is_live())

c_nav1, c_nav2 = st.columns([6, 1])
with c_nav2:
    st.markdown('<div class="btn-ghost">', unsafe_allow_html=True)
    if st.button("Switch project", key="switch"):
        for k in ["active_project", "file_bytes", "qa_history", "last_audit",
                  "last_takeoff", "last_estimate", "last_timeline", "last_lookahead",
                  "last_photo_review", "gantt_bytes", "rfi_draft", "active_sheet",
                  "est_lines", "est_warnings", "audit_warnings",
                  "takeoff_warnings", "audit_ran", "takeoff_ran"]:
            st.session_state.pop(k, None)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

if not file_bytes:
    _drawing_setup(proj)
    st.stop()

drawing_index = _ensure_index(proj, file_bytes)

# AI drawer in the collapsible sidebar; drawings own the canvas
with st.sidebar:
    ai_panel.render(proj, file_bytes, drawing_index)

tab_plans, tab_est, tab_photos, tab_rfi = st.tabs(
    ["Plan Room", "Estimator", "Photos", "RFIs"])

with tab_plans:
    active = viewer.sheet_picker(drawing_index)
    if active:
        viewer.render(file_bytes, active,
                      drawing_index.get(str(active), f"Page {active}"))
        with st.expander("Sheet thumbnails", expanded=False):
            viewer.thumbnail_rail(file_bytes, drawing_index, active)

with tab_est:
    # Reuse whatever sheet scope the AI panel is set to, so the estimator
    # prices the same sheets you've been working with.
    _pages = sorted(int(k) for k in drawing_index.keys())
    _mode = st.session_state.get("ai_scope", "Current sheet")
    if _mode == "Entire set":
        _scope = _pages
    elif _mode == "Current sheet":
        _scope = [st.session_state.get("active_sheet", _pages[0])] if _pages else []
    else:
        _, _labels, _map = viewer.sheet_labels(drawing_index)
        _scope = [_map[l] for l in st.session_state.get("ai_sheet_pick", []) if l in _map]
    estimator.render(proj, file_bytes, drawing_index, _scope)

with tab_photos:
    photos.render(proj["id"])

with tab_rfi:
    rfi_panel.render(proj, drawing_index)
