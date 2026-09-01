"""Project directory: create, list, recall.

THE POINT OF THIS MODULE: the drawing index (sheet number -> sheet name) is
expensive to build -- one AI call per sheet, so ~100 calls on a full set.
Once built it never changes for that drawing set, so it's stored with the
project and reloaded instantly on recall. Same for generated artifacts
(timelines, audits, Q&A history): computed once, recalled free.

Works with or without Firebase. Without it, projects live in session state
and vanish when the session ends -- the API is identical either way.
"""
import uuid
from datetime import datetime

import streamlit as st

import sp_firebase as firebase
from sp_config import COL_PROJECTS, COL_ARTIFACTS


def _local_store():
    if "_local_projects" not in st.session_state:
        st.session_state._local_projects = {}
    return st.session_state._local_projects


def _local_artifacts():
    if "_local_artifacts" not in st.session_state:
        st.session_state._local_artifacts = {}
    return st.session_state._local_artifacts


# ----------------------------------------------------------------- projects

def create_project(name, number="", client="", location="", notes=""):
    pid = uuid.uuid4().hex[:12]
    record = {
        "id": pid,
        "name": name.strip(),
        "number": number.strip(),
        "client": client.strip(),
        "location": location.strip(),
        "notes": notes.strip(),
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
        "drawing_index": {},
        "pdf_path": "",
        "pdf_name": "",
        "sheet_count": 0,
        "rfi_counter": 0,
    }
    if not firebase.doc_set(COL_PROJECTS, pid, record):
        _local_store()[pid] = record
    return pid


def list_projects():
    if firebase.is_live():
        items = firebase.doc_list(COL_PROJECTS)
        if items:
            return sorted(items, key=lambda p: p.get("updated", ""), reverse=True)
        return []
    return sorted(_local_store().values(), key=lambda p: p.get("updated", ""), reverse=True)


def get_project(pid):
    if not pid:
        return None
    rec = firebase.doc_get(COL_PROJECTS, pid)
    if rec:
        return rec
    return _local_store().get(pid)


def update_project(pid, **fields):
    fields["updated"] = datetime.now().isoformat()
    if not firebase.doc_set(COL_PROJECTS, pid, fields):
        store = _local_store()
        if pid in store:
            store[pid].update(fields)
    # keep the in-session copy hot so the UI reflects changes immediately
    active = st.session_state.get("active_project")
    if isinstance(active, dict) and active.get("id") == pid:
        active.update(fields)


def delete_project(pid):
    firebase.doc_delete(COL_PROJECTS, pid)
    _local_store().pop(pid, None)


def next_rfi_number(pid):
    """Atomic-ish increment. Single-user, so a read-modify-write is fine."""
    proj = get_project(pid) or {}
    n = int(proj.get("rfi_counter", 0)) + 1
    update_project(pid, rfi_counter=n)
    return n


# ---------------------------------------------------------------- drawings

def save_drawing_index(pid, index):
    """The expensive artifact -- saved once, recalled forever."""
    update_project(pid, drawing_index=index, sheet_count=len(index))


def save_pdf(pid, file_bytes, filename):
    """Stores the drawing PDF. Needs Firebase Storage (Blaze plan); without
    it the bytes stay in session and must be re-uploaded next session."""
    path = firebase.upload_bytes(f"projects/{pid}/drawings/{filename}", file_bytes, "application/pdf")
    if path:
        update_project(pid, pdf_path=path, pdf_name=filename)
        return True
    update_project(pid, pdf_name=filename)
    return False


def load_pdf(pid):
    proj = get_project(pid) or {}
    path = proj.get("pdf_path")
    if path:
        return firebase.download_bytes(path)
    return None


# --------------------------------------------------------------- artifacts

def save_artifact(pid, kind, payload, label=""):
    """kind: timeline | audit | takeoff | estimate | qa | suggestion"""
    aid = uuid.uuid4().hex[:12]
    record = {
        "id": aid,
        "project_id": pid,
        "kind": kind,
        "label": label,
        "payload": payload,
        "created": datetime.now().isoformat(),
    }
    if not firebase.doc_set(COL_ARTIFACTS, aid, record):
        _local_artifacts().setdefault(pid, []).append(record)
    return aid


def list_artifacts(pid, kind=None):
    if firebase.is_live():
        items = firebase.doc_list(COL_ARTIFACTS, where=("project_id", "==", pid))
    else:
        items = list(_local_artifacts().get(pid, []))
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    return sorted(items, key=lambda a: a.get("created", ""), reverse=True)


def latest_artifact(pid, kind):
    items = list_artifacts(pid, kind)
    return items[0] if items else None
