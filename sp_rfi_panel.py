"""RFI generation UI.

Flow: quick field notes -> AI drafts formal language -> you review and edit
-> download PDF. The edit step is deliberate: this document goes to a client,
so nothing gets sent that you haven't read.
"""
from datetime import datetime, timedelta

import streamlit as st

import sp_firebase as firebase
import sp_projects as projects
import sp_rfi as rfi_engine
from sp_config import COL_RFIS


def _save_rfi(pid, record):
    if not firebase.doc_set(COL_RFIS, f"{pid}_{record['number']}", record):
        st.session_state.setdefault("_session_rfis", {}).setdefault(pid, []).append(record)


def _list_rfis(pid):
    if firebase.is_live():
        remote = firebase.doc_list(COL_RFIS, where=("project_id", "==", pid))
        if remote:
            return sorted(remote, key=lambda r: r.get("created", ""), reverse=True)
    return sorted(st.session_state.get("_session_rfis", {}).get(pid, []),
                  key=lambda r: r.get("created", ""), reverse=True)


def render(proj, drawing_index):
    pid = proj["id"]
    st.markdown('<div class="section-title">Request for Information</div>', unsafe_allow_html=True)
    st.caption("Enter it the way you'd say it in the field. The draft comes back in formal "
               "RFI language for you to review before sending.")

    with st.form("rfi_form"):
        st.markdown('<div class="module-tag">Recipient</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            to_name = st.text_input("To (name)", placeholder="Jane Doe, AIA")
        with c2:
            to_company = st.text_input("Company", placeholder="Doe Architecture")
        with c3:
            to_email = st.text_input("Email", placeholder="jane@doearch.com")

        c4, c5, c6 = st.columns(3)
        with c4:
            from_name = st.text_input("From (you)", placeholder="Your name")
        with c5:
            priority = st.selectbox("Priority", ["Normal", "High", "Urgent"])
        with c6:
            due = st.date_input("Response needed by",
                                value=(datetime.now() + timedelta(days=7)).date())

        st.markdown('<div class="module-tag">The Question</div>', unsafe_allow_html=True)
        subject = st.text_input("Subject (optional — AI will refine)",
                                placeholder="Conflict between kitchen hood and structural beam")

        notes = st.text_area(
            "What's the issue? Write it however you'd say it out loud.",
            height=120,
            placeholder="The hood on A-401 sits right where the W12 beam runs on S-201. "
                        "No way to hang it as drawn. Need to know if we can drop the hood "
                        "6 inches or if the beam moves.",
        )

        sheet_opts = [drawing_index[k] for k in sorted(drawing_index, key=lambda x: int(x))]
        c7, c8 = st.columns(2)
        with c7:
            sheets = st.multiselect("Drawing references", sheet_opts)
        with c8:
            spec = st.text_input("Spec section (optional)", placeholder="11 40 00")

        c9, c10 = st.columns(2)
        with c9:
            impact = st.text_area("Schedule/cost impact (optional)", height=68,
                                  placeholder="Holds hood rough-in, 3 day float left")
        with c10:
            suggested = st.text_area("Your suggested fix (optional)", height=68,
                                     placeholder="Drop hood 6in, still meets 6'-6\" clearance")

        submitted = st.form_submit_button("Draft RFI")

    if submitted:
        if not notes.strip():
            st.warning("Describe the issue before drafting.")
        else:
            with st.spinner("Drafting..."):
                drafted = rfi_engine.draft(
                    proj,
                    {"name": to_name, "company": to_company, "email": to_email,
                     "from_name": from_name},
                    subject, notes.strip(),
                    sheets=", ".join(sheets), spec_section=spec,
                    impact_notes=impact, suggested=suggested,
                )
            drafted.update({
                "number": projects.next_rfi_number(pid),
                "date": datetime.now().strftime("%B %d, %Y"),
                "due": due.strftime("%B %d, %Y"),
                "priority": priority,
                "sheets": ", ".join(sheets),
                "spec_section": spec,
            })
            st.session_state.rfi_draft = drafted
            st.session_state.rfi_recipient = {
                "name": to_name, "company": to_company,
                "email": to_email, "from_name": from_name,
            }
            if drafted.get("_fallback"):
                st.warning("AI drafting failed — your raw notes are loaded below. Edit and proceed.")
            st.rerun()

    draft = st.session_state.get("rfi_draft")
    if not draft:
        st.divider()
        past = _list_rfis(pid)
        if past:
            st.markdown('<div class="module-tag">Issued RFIs</div>', unsafe_allow_html=True)
            for r in past[:10]:
                st.markdown(f"**RFI #{r.get('number')}** — {r.get('subject','')[:60]}  \n"
                            f"<span style='opacity:.6;font-size:.85em'>"
                            f"{r.get('date','')} · to {r.get('to_name','')}</span>",
                            unsafe_allow_html=True)
        return

    # ---- Review & edit before it goes out ----
    st.divider()
    st.markdown(f'<div class="ref-header">Draft — RFI #{draft["number"]}</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="report-box accent-safety">', unsafe_allow_html=True)

    draft["subject"] = st.text_input("Subject", value=draft.get("subject", ""), key="rd_sub")
    draft["background"] = st.text_area("Background", value=draft.get("background", ""),
                                       height=70, key="rd_bg")
    draft["question"] = st.text_area("Information requested", value=draft.get("question", ""),
                                     height=140, key="rd_q")
    draft["impact"] = st.text_area("Schedule / cost impact",
                                   value=draft.get("impact", ""), height=70, key="rd_imp")
    draft["suggested_resolution"] = st.text_area(
        "Suggested resolution", value=draft.get("suggested_resolution", ""),
        height=70, key="rd_sug")
    st.markdown("</div>", unsafe_allow_html=True)

    c_a, c_b = st.columns([1, 1])
    with c_a:
        company = st.text_input("Your company (on letterhead)", value="SCK Contractors",
                                key="rd_co")
    with c_b:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="btn-ghost">', unsafe_allow_html=True)
        if st.button("Discard draft", key="rd_discard"):
            st.session_state.pop("rfi_draft", None)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    try:
        pdf_bytes = rfi_engine.build_pdf(
            draft, proj, st.session_state.get("rfi_recipient", {}), company
        )
        recip = st.session_state.get("rfi_recipient", {})
        if st.download_button(
            f"Download RFI #{draft['number']} (PDF)", pdf_bytes,
            f"RFI_{draft['number']}_{proj.get('number') or proj.get('name','project')}.pdf",
            "application/pdf", key="rd_dl",
        ):
            _save_rfi(pid, {
                "project_id": pid, "number": draft["number"],
                "subject": draft.get("subject", ""), "question": draft.get("question", ""),
                "to_name": recip.get("name", ""), "to_company": recip.get("company", ""),
                "date": draft.get("date", ""), "priority": draft.get("priority", ""),
                "sheets": draft.get("sheets", ""),
                "created": datetime.now().isoformat(),
            })
    except Exception as e:
        st.error(f"PDF generation failed: {e}")
