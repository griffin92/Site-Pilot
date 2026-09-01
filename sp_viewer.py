"""The drawing viewer -- the primary surface of the app.

Pan/zoom runs client-side in an HTML component rather than round-tripping to
the server. Streamlit reruns the whole script on every interaction, so
server-side zoom would mean a full re-render per scroll wheel tick, which
feels broken. Sending the sheet once and letting the browser transform it
gives the Bluebeam-style responsiveness the drawing surface needs.
"""
import base64

import streamlit as st
import streamlit.components.v1 as components

import sp_ai as ai
import sp_compat as compat
from sp_config import VIEWER_WIDTH


def _viewer_html(jpeg_b64, sheet_label, height=760):
    return f"""
<div id="spWrap" style="position:relative;width:100%;height:{height}px;overflow:hidden;
     background:#5A6472;border:1px solid rgba(16,27,46,0.25);border-radius:3px;cursor:grab;">

  <div id="spStage" style="position:absolute;top:0;left:0;transform-origin:0 0;
       will-change:transform;">
    <img id="spImg" src="data:image/jpeg;base64,{jpeg_b64}"
         style="display:block;max-width:none;user-select:none;-webkit-user-drag:none;"/>
  </div>

  <div style="position:absolute;top:10px;left:10px;background:rgba(14,27,46,0.92);
       color:#fff;font:600 10px/1.4 'IBM Plex Mono',monospace;letter-spacing:.06em;
       padding:6px 11px;border-radius:3px;text-transform:uppercase;pointer-events:none;">
    {sheet_label}
  </div>

  <div style="position:absolute;bottom:12px;right:12px;display:flex;gap:5px;">
    <button onclick="spZoom(1.25)" style="{_btn()}">+</button>
    <button onclick="spZoom(0.8)" style="{_btn()}">&minus;</button>
    <button onclick="spFit()" style="{_btn()};width:auto;padding:0 11px;font-size:9px;">FIT</button>
    <button onclick="spFull()" style="{_btn()};width:auto;padding:0 11px;font-size:9px;">100%</button>
  </div>

  <div id="spPct" style="position:absolute;bottom:12px;left:12px;background:rgba(14,27,46,0.92);
       color:#E8ECF1;font:600 10px 'IBM Plex Mono',monospace;padding:6px 10px;
       border-radius:3px;pointer-events:none;">100%</div>
</div>

<script>
(function() {{
  const wrap = document.getElementById('spWrap');
  const stage = document.getElementById('spStage');
  const img = document.getElementById('spImg');
  const pct = document.getElementById('spPct');
  let scale = 1, tx = 0, ty = 0, natW = 0, natH = 0;
  let dragging = false, sx = 0, sy = 0;

  function apply() {{
    stage.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
    pct.textContent = Math.round(scale * 100) + '%';
  }}

  function fit() {{
    if (!natW) return;
    const s = Math.min(wrap.clientWidth / natW, wrap.clientHeight / natH);
    scale = s;
    tx = (wrap.clientWidth - natW * s) / 2;
    ty = (wrap.clientHeight - natH * s) / 2;
    apply();
  }}

  window.spFit = fit;
  window.spFull = function() {{
    // Anchor 100% on the current view centre so you don't lose your place
    const cx = wrap.clientWidth / 2, cy = wrap.clientHeight / 2;
    const ix = (cx - tx) / scale, iy = (cy - ty) / scale;
    scale = 1; tx = cx - ix; ty = cy - iy; apply();
  }};
  window.spZoom = function(f) {{
    const cx = wrap.clientWidth / 2, cy = wrap.clientHeight / 2;
    const ix = (cx - tx) / scale, iy = (cy - ty) / scale;
    scale = Math.min(8, Math.max(0.05, scale * f));
    tx = cx - ix * scale; ty = cy - iy * scale; apply();
  }};

  img.onload = function() {{
    natW = img.naturalWidth; natH = img.naturalHeight; fit();
  }};
  if (img.complete && img.naturalWidth) {{ natW = img.naturalWidth; natH = img.naturalHeight; fit(); }}

  // Wheel zoom toward the cursor -- the behaviour people expect from
  // drawing software, rather than zooming to centre.
  wrap.addEventListener('wheel', function(e) {{
    e.preventDefault();
    const r = wrap.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const ix = (mx - tx) / scale, iy = (my - ty) / scale;
    const f = e.deltaY < 0 ? 1.12 : 0.89;
    scale = Math.min(8, Math.max(0.05, scale * f));
    tx = mx - ix * scale; ty = my - iy * scale;
    apply();
  }}, {{ passive: false }});

  wrap.addEventListener('mousedown', function(e) {{
    dragging = true; sx = e.clientX - tx; sy = e.clientY - ty; wrap.style.cursor = 'grabbing';
  }});
  window.addEventListener('mousemove', function(e) {{
    if (!dragging) return;
    tx = e.clientX - sx; ty = e.clientY - sy; apply();
  }});
  window.addEventListener('mouseup', function() {{ dragging = false; wrap.style.cursor = 'grab'; }});

  // Touch: single-finger pan, two-finger pinch
  let pinch = 0;
  wrap.addEventListener('touchstart', function(e) {{
    if (e.touches.length === 1) {{
      dragging = true; sx = e.touches[0].clientX - tx; sy = e.touches[0].clientY - ty;
    }} else if (e.touches.length === 2) {{
      dragging = false;
      pinch = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
                         e.touches[0].clientY - e.touches[1].clientY);
    }}
  }}, {{ passive: true }});
  wrap.addEventListener('touchmove', function(e) {{
    if (e.touches.length === 1 && dragging) {{
      tx = e.touches[0].clientX - sx; ty = e.touches[0].clientY - sy; apply();
    }} else if (e.touches.length === 2) {{
      e.preventDefault();
      const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
                           e.touches[0].clientY - e.touches[1].clientY);
      if (pinch) {{
        const r = wrap.getBoundingClientRect();
        const mx = (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left;
        const my = (e.touches[0].clientY + e.touches[1].clientY) / 2 - r.top;
        const ix = (mx - tx) / scale, iy = (my - ty) / scale;
        scale = Math.min(8, Math.max(0.05, scale * (d / pinch)));
        tx = mx - ix * scale; ty = my - iy * scale;
        apply();
      }}
      pinch = d;
    }}
  }}, {{ passive: false }});
  wrap.addEventListener('touchend', function() {{ dragging = false; pinch = 0; }});
}})();
</script>
"""


def sheet_labels(drawing_index):
    """Return (pages, labels, label_to_page) with GUARANTEED-UNIQUE labels.

    Sheet titles are not unique in practice -- a bad index run can emit the
    same title for several pages, or fall back to "Page N" for some. Any
    labels.index(pick) lookup then silently resolves to the FIRST match, so
    selecting sheet 47 quietly opens sheet 12. Disambiguating here removes
    that whole class of wrong-sheet bug.
    """
    pages = sorted(int(k) for k in drawing_index.keys())
    counts = {}
    for p in pages:
        base = str(drawing_index.get(str(p)) or "").strip() or f"Page {p}"
        counts[base] = counts.get(base, 0) + 1

    labels, mapping = [], {}
    for p in pages:
        base = str(drawing_index.get(str(p)) or "").strip() or f"Page {p}"
        label = f"{base}  ·  p{p}" if counts[base] > 1 else base
        while label in mapping:          # belt and braces
            label += " "
        labels.append(label)
        mapping[label] = p
    return pages, labels, mapping


def _btn():
    return ("width:30px;height:26px;background:rgba(14,27,46,0.92);color:#fff;border:none;"
            "border-radius:3px;font:600 13px 'IBM Plex Mono',monospace;cursor:pointer;"
            "display:flex;align-items:center;justify-content:center;")


def render(file_bytes, page_num, sheet_label, height=760):
    """Draw the pan/zoom viewer for one sheet."""
    try:
        jpeg = ai.page_jpeg(file_bytes, page_num, VIEWER_WIDTH)
        b64 = base64.b64encode(jpeg).decode("ascii")
        components.html(_viewer_html(b64, sheet_label, height), height=height + 8)
    except Exception as e:
        st.error(f"Couldn't render this sheet: {e}")


def sheet_picker(drawing_index, key="active_sheet"):
    """Sheet selector + prev/next. Returns the selected page number."""
    pages, labels, label_to_page = sheet_labels(drawing_index)
    if not pages:
        return None

    if key not in st.session_state or st.session_state[key] not in pages:
        st.session_state[key] = pages[0]

    current = st.session_state[key]
    pos = pages.index(current)

    c_prev, c_sel, c_next = st.columns([1, 6, 1])
    with c_prev:
        st.markdown('<div class="btn-ghost">', unsafe_allow_html=True)
        if st.button("◀", key=f"{key}_prev", disabled=(pos == 0), **compat.stretch()):
            st.session_state[key] = pages[pos - 1]
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with c_sel:
        picked = st.selectbox(
            "Sheet", labels, index=pos, label_visibility="collapsed", key=f"{key}_sel"
        )
        new_page = label_to_page[picked]
        if new_page != current:
            st.session_state[key] = new_page
            st.rerun()
    with c_next:
        st.markdown('<div class="btn-ghost">', unsafe_allow_html=True)
        if st.button("▶", key=f"{key}_next", disabled=(pos == len(pages) - 1), **compat.stretch()):
            st.session_state[key] = pages[pos + 1]
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    return st.session_state[key]


def thumbnail_rail(file_bytes, drawing_index, active_page, key="active_sheet", per_row=6):
    """Contact-sheet strip for fast visual navigation. Paged, because
    rendering 100 thumbnails at once is both slow and memory-hungry."""
    pages = sorted(int(k) for k in drawing_index.keys())
    if not pages:
        return

    page_size = per_row * 2
    total_chunks = max(1, (len(pages) + page_size - 1) // page_size)
    chunk_key = f"{key}_thumbchunk"
    if chunk_key not in st.session_state:
        st.session_state[chunk_key] = 0
    # Follow the active sheet so the rail stays in sync with the viewer
    st.session_state[chunk_key] = min(pages.index(active_page) // page_size, total_chunks - 1)
    chunk = st.session_state[chunk_key]

    subset = pages[chunk * page_size:(chunk + 1) * page_size]
    st.caption(f"Sheets {subset[0]}–{subset[-1]} of {len(pages)}")

    for row_start in range(0, len(subset), per_row):
        row = subset[row_start:row_start + per_row]
        cols = st.columns(per_row)
        for col, p in zip(cols, row):
            with col:
                try:
                    st.image(ai.render_thumb(file_bytes, p), **compat.stretch())
                except Exception:
                    st.caption("—")
                name = drawing_index.get(str(p), f"Page {p}")
                is_active = (p == active_page)
                st.markdown('<div class="btn-ghost">' if not is_active else "", unsafe_allow_html=True)
                if st.button(name[:16] or f"P{p}", key=f"{key}_thumb_{p}", **compat.stretch()):
                    st.session_state[key] = p
                    st.rerun()
                st.markdown("</div>" if not is_active else "", unsafe_allow_html=True)
