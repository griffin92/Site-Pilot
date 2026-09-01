"""Gemini wrapper: rendering, batching, retries, structured output.

MEMORY DISCIPLINE: every PDF page renders to a multi-MB in-memory image.
Holding a whole 100+ sheet set at once will get the process OOM-killed with
no Python traceback (a silent crash, which is miserable to debug). Every
function here processes in bounded batches and frees each batch before the
next one starts.
"""
import gc
import io
import json

import streamlit as st
from google import genai
from google.genai import types
from pdf2image import convert_from_bytes, pdfinfo_from_bytes

from sp_config import MODEL_NAME, ANALYSIS_WIDTH, VIEWER_WIDTH, THUMB_WIDTH

_client = None


def client():
    global _client
    if _client is None:
        try:
            _client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
        except Exception:
            st.error("GEMINI_API_KEY not found. Add it to your app secrets.")
            st.stop()
    return _client


# ---------------------------------------------------------------- rendering

@st.cache_resource(show_spinner=False)
def page_count(file_bytes):
    return pdfinfo_from_bytes(file_bytes)["Pages"]


@st.cache_data(show_spinner=False, max_entries=40)
def render_page(file_bytes, page_num, width=ANALYSIS_WIDTH):
    """Render one page. Cached, so re-viewing a sheet is instant.
    max_entries caps the cache so a big set can't balloon memory."""
    return convert_from_bytes(
        file_bytes, first_page=page_num, last_page=page_num, size=(width, None)
    )[0]


@st.cache_data(show_spinner=False, max_entries=200)
def render_thumb(file_bytes, page_num):
    return convert_from_bytes(
        file_bytes, first_page=page_num, last_page=page_num, size=(THUMB_WIDTH, None)
    )[0]


def page_jpeg(file_bytes, page_num, width=VIEWER_WIDTH, quality=85):
    """JPEG bytes for the HTML viewer. Smaller over the wire than PNG for
    scanned sheets, and the viewer does its own zoom client-side."""
    img = render_page(file_bytes, page_num, width)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ------------------------------------------------------------------ calling

def generate(contents, system_prompt, temperature=0.2, json_mode=False, retries=2):
    """Single call with retry. Returns text, or raises the last exception."""
    cfg = {"system_instruction": system_prompt, "temperature": temperature}
    if json_mode:
        cfg["response_mime_type"] = "application/json"

    last = None
    for attempt in range(retries + 1):
        try:
            res = client().models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(**cfg),
            )
            return res.text
        except Exception as e:
            last = e
    raise last


def generate_json(contents, system_prompt, temperature=0.1, default=None):
    """JSON-mode call that never raises -- returns `default` on failure.
    Used where a malformed response should degrade, not crash the page."""
    try:
        raw = generate(contents, system_prompt, temperature, json_mode=True)
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return default


def batched_scan(file_bytes, pages, system_prompt, user_prompt,
                 batch_size=12, label_fn=None, merge_prompt=None,
                 progress_label="Analyzing sheets"):
    """Run a prompt across many sheets in memory-safe batches, then merge.

    label_fn(page_num) -> str lets callers pass real sheet names so the model
    cites "A-201 Kitchen Plan" instead of "page 34".
    """
    batches = [pages[i:i + batch_size] for i in range(0, len(pages), batch_size)]
    total = len(batches)
    outputs = []

    bar = st.progress(0)
    status = st.empty()

    for idx, batch in enumerate(batches):
        names = ", ".join(label_fn(p) for p in batch) if label_fn else \
            f"pages {batch[0]}-{batch[-1]}"
        status.caption(f"{progress_label} — group {idx + 1} of {total}: {names[:80]}")

        prompt = user_prompt
        if total > 1:
            prompt += (
                f"\n\n[This is group {idx + 1} of {total}, covering: {names}. "
                f"Report findings ONLY from these sheets; the rest are handled separately.]"
            )

        payload = [prompt]
        for p in batch:
            payload.append(render_page(file_bytes, p, ANALYSIS_WIDTH))

        try:
            outputs.append(generate(payload, system_prompt, 0.2))
        except Exception as e:
            status.warning(f"Group {idx + 1} failed: {e}")
            outputs.append(f"[Group {idx + 1} ({names}) could not be processed: {e}]")

        del payload
        gc.collect()
        bar.progress(int(((idx + 1) / total) * 90))

    bar.progress(100)
    status.empty()

    if total == 1:
        return outputs[0]

    # Merge pass is text-only, so it's cheap regardless of set size
    combined = "\n\n---\n\n".join(outputs)
    merge_sys = merge_prompt or (
        system_prompt
        + "\n\nYou are merging findings extracted from separate groups of the same "
          "drawing set. Combine into ONE result in the same output format. Remove "
          "duplicates across groups; never drop a unique finding."
    )
    try:
        return generate([f"Merge these into one consolidated result:\n\n{combined}"],
                        merge_sys, 0.1)
    except Exception:
        return combined


def batched_json_scan(file_bytes, pages, system_prompt, user_prompt,
                      batch_size=12, label_fn=None,
                      progress_label="Analyzing sheets"):
    """Like batched_scan, but each batch returns a JSON array and the results
    are concatenated in PYTHON.

    WHY THIS EXISTS: the text version asks the model to re-emit findings during
    a merge pass, and models routinely drop the 'ISSUE:'/'TAKEOFF:' prefixes
    when they do -- which made downstream prefix-parsing return an empty list
    and look like the engine had silently failed. Structured output plus a
    Python-side merge removes both failure modes.

    Returns (records, failed_batches).
    """
    batches = [pages[i:i + batch_size] for i in range(0, len(pages), batch_size)]
    total = len(batches)
    records, failed = [], []

    bar = st.progress(0)
    status = st.empty()

    for idx, batch in enumerate(batches):
        names = ", ".join(label_fn(p) for p in batch) if label_fn else \
            f"pages {batch[0]}-{batch[-1]}"
        status.caption(f"{progress_label} — group {idx + 1} of {total}: {names[:80]}")

        prompt = (user_prompt +
                  f"\n\nThe attached sheets are, in order: {names}. "
                  f"Use these exact sheet names when citing.")

        payload = [prompt]
        for p in batch:
            payload.append(render_page(file_bytes, p, ANALYSIS_WIDTH))

        got = generate_json(payload, system_prompt, temperature=0.15, default=None)
        if isinstance(got, dict):
            # Model sometimes wraps the array in a single-key object
            for v in got.values():
                if isinstance(v, list):
                    got = v
                    break
        if isinstance(got, list):
            records.extend([r for r in got if isinstance(r, dict)])
        else:
            failed.append(names)

        del payload
        gc.collect()
        bar.progress(int(((idx + 1) / total) * 100))

    bar.empty()
    status.empty()
    return records, failed


def analyze_images(images, system_prompt, user_prompt, batch_size=6, temperature=0.2):
    """Same batching discipline for photos (PIL images already in memory)."""
    batches = [images[i:i + batch_size] for i in range(0, len(images), batch_size)]
    outputs = []
    for batch in batches:
        payload = [user_prompt] + [img for _, img in batch]
        try:
            outputs.append(generate(payload, system_prompt, temperature))
        except Exception as e:
            outputs.append(f"[Batch could not be processed: {e}]")
        gc.collect()
    if len(outputs) == 1:
        return outputs[0]
    combined = "\n\n---\n\n".join(outputs)
    try:
        return generate([f"Consolidate these photo observations:\n\n{combined}"],
                        system_prompt, 0.1)
    except Exception:
        return combined
