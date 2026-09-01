"""Jobsite photo library with AI analysis.

Photos live in Firebase Storage when it's available; otherwise they stay in
session state for the current session. Either way the analysis path is
identical.
"""
import io
import uuid
from datetime import datetime

import streamlit as st
from PIL import Image

import sp_firebase as firebase
import sp_projects as projects
import sp_compat as compat
import sp_suggestions as suggestions
from sp_config import COL_PHOTOS

MAX_EDGE = 1400   # downscale on ingest: phone photos are 4000px+ and the
                  # model gains nothing from the extra pixels


def _session_photos(pid):
    store = st.session_state.setdefault("_session_photos", {})
    return store.setdefault(pid, [])


def _downscale(img):
    img = img.convert("RGB")
    if max(img.size) > MAX_EDGE:
        ratio = MAX_EDGE / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    return img


def add_photos(pid, files, caption="", area=""):
    added = 0
    for f in files:
        try:
            img = _downscale(Image.open(f))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82, optimize=True)
            data = buf.getvalue()

            phid = uuid.uuid4().hex[:12]
            meta = {
                "id": phid,
                "project_id": pid,
                "name": f.name,
                "caption": caption,
                "area": area,
                "taken": datetime.now().isoformat(),
            }

            path = firebase.upload_bytes(f"projects/{pid}/photos/{phid}.jpg", data, "image/jpeg")
            if path:
                meta["path"] = path
                firebase.doc_set(COL_PHOTOS, phid, meta)
            else:
                meta["_bytes"] = data
                _session_photos(pid).append(meta)
            added += 1
        except Exception as e:
            st.warning(f"Couldn't add {f.name}: {e}")
    return added


def list_photos(pid):
    if firebase.is_live():
        remote = firebase.doc_list(COL_PHOTOS, where=("project_id", "==", pid))
        if remote:
            return sorted(remote, key=lambda p: p.get("taken", ""), reverse=True)
    return sorted(_session_photos(pid), key=lambda p: p.get("taken", ""), reverse=True)


def load_image(meta):
    if meta.get("_bytes"):
        return Image.open(io.BytesIO(meta["_bytes"]))
    if meta.get("path"):
        data = firebase.download_bytes(meta["path"])
        if data:
            return Image.open(io.BytesIO(data))
    return None


def render(pid):
    st.markdown('<div class="section-title">Photo Library</div>', unsafe_allow_html=True)

    if not firebase.has_storage():
        st.caption("Photos are held for this session only. Connect Firebase Storage "
                   "(Blaze plan) to keep them with the project.")

    with st.expander("Add photos", expanded=False):
        files = st.file_uploader("Jobsite photos", type=["jpg", "jpeg", "png", "heic"],
                                 accept_multiple_files=True, key="photo_up")
        c1, c2 = st.columns(2)
        with c1:
            area = st.text_input("Area / location", placeholder="e.g. Kitchen, Level 2 East")
        with c2:
            caption = st.text_input("Caption", placeholder="e.g. MEP rough-in above ceiling")
        if st.button("Upload", key="photo_add") and files:
            n = add_photos(pid, files, caption, area)
            st.success(f"Added {n} photo{'s' if n != 1 else ''}.")
            st.rerun()

    photos = list_photos(pid)
    if not photos:
        st.info("No photos yet. Add jobsite photos to enable photo analysis and the "
                "two-week look-ahead.")
        return

    st.caption(f"{len(photos)} photo{'s' if len(photos) != 1 else ''} on file")

    # Grid
    for row_start in range(0, min(len(photos), 12), 4):
        row = photos[row_start:row_start + 4]
        cols = st.columns(4)
        for col, meta in zip(cols, row):
            with col:
                img = load_image(meta)
                if img:
                    st.image(img, **compat.stretch())
                label = meta.get("area") or meta.get("name", "")
                st.caption(f"**{label[:22]}**" + (f"  \n{meta['caption'][:40]}" if meta.get("caption") else ""))

    st.divider()
    st.markdown('<div class="module-tag">Photo Analysis</div>', unsafe_allow_html=True)
    focus = st.text_input("Focus the review (optional)",
                          placeholder="e.g. check fire caulking at rated walls",
                          key="photo_focus")
    limit = st.slider("Photos to analyze (most recent first)", 1,
                      min(12, len(photos)), min(6, len(photos)), key="photo_limit")

    if st.button("Analyze Photos", key="photo_analyze"):
        with st.spinner("Reviewing photos..."):
            loaded = []
            for meta in photos[:limit]:
                img = load_image(meta)
                if img:
                    label = meta.get("area") or meta.get("name", "photo")
                    if meta.get("caption"):
                        label += f" ({meta['caption']})"
                    loaded.append((label, img))
            if not loaded:
                st.error("Couldn't load the photos for analysis.")
            else:
                result = suggestions.analyze_photos(loaded, focus)
                projects.save_artifact(pid, "photo_review", result,
                                       label=f"{len(loaded)} photos")
                st.session_state.last_photo_review = result
                st.rerun()

    latest = st.session_state.get("last_photo_review") or \
        (projects.latest_artifact(pid, "photo_review") or {}).get("payload")
    if latest:
        st.markdown('<div class="report-box accent-verified">', unsafe_allow_html=True)
        st.markdown(latest)
        st.markdown("</div>", unsafe_allow_html=True)
