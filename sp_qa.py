"""Ask-the-drawings: targeted lookup, as opposed to the deep-scan engines.

Two-stage design. A cheap text-only routing call reads the sheet index and
picks which sheets likely hold the answer; only those get rendered and sent.
On a 100-sheet set that's the difference between seconds and minutes per
question, and accuracy improves because the model isn't wading through 90
irrelevant sheets.
"""
import gc
import json

import streamlit as st

import sp_ai as ai
import sp_prompts as prompts
from sp_config import QA_BATCH, ANALYSIS_WIDTH


def routing_available(drawing_index, pages):
    """Routing only works if sheets have real names. An un-indexed set
    ("Page 12") carries no signal, so we fall back to scanning everything."""
    named = [p for p in pages
             if not str(drawing_index.get(str(p), "")).strip().lower().startswith("page ")]
    return len(named) >= max(3, len(pages) * 0.5)


def select_relevant_sheets(question, drawing_index, pages, max_sheets=8):
    if not routing_available(drawing_index, pages):
        return None

    catalog = "\n".join(f"{p} = {drawing_index.get(str(p), f'Page {p}')}" for p in pages)
    user = f"""A field question needs answering from a drawing set. Below is the sheet index.

Pick the sheets most likely to contain the answer. Consider which discipline and sheet type carries this information. Include schedule sheets when the question involves equipment, finishes, doors, or power.

Return ONLY a JSON array of page numbers, most relevant first, max {max_sheets}. Example: [12, 45, 46]

QUESTION: {question}

SHEET INDEX (page = name):
{catalog}"""

    picked = ai.generate_json(
        [user],
        "You route construction questions to the correct drawing sheets. Output only JSON.",
        default=None,
    )
    if not picked:
        return None
    try:
        valid = [int(p) for p in picked if int(p) in pages]
        return valid[:max_sheets] or None
    except Exception:
        return None


def ask(file_bytes, pages, question, drawing_index, prior_turns=None):
    """Answer a question against the given sheets. Returns answer text."""
    batches = [pages[i:i + QA_BATCH] for i in range(0, len(pages), QA_BATCH)]
    total = len(batches)
    findings = []

    context = ""
    if prior_turns:
        recent = prior_turns[-3:]
        context = "\n\nEARLIER IN THIS CONVERSATION (context for follow-ups):\n" + "\n".join(
            f"Q: {t['q']}\nA: {t['a'][:350]}" for t in recent
        )

    bar = st.progress(0)
    status = st.empty()

    for idx, batch in enumerate(batches):
        labels = ", ".join(drawing_index.get(str(p), f"Page {p}") for p in batch)
        status.caption(f"Reading {idx + 1}/{total}: {labels[:80]}")

        user = (
            f"QUESTION FROM THE FIELD: {question}{context}\n\n"
            f"The attached images are these sheets, in order: {labels}.\n"
            f"Cite sheets by these names.\n\n"
            f"Answer from these sheets. If the answer is not on these particular sheets, "
            f"respond with exactly: NOT_ON_THESE_SHEETS"
        )
        payload = [user]
        for p in batch:
            payload.append(ai.render_page(file_bytes, p, ANALYSIS_WIDTH))

        try:
            txt = ai.generate(payload, prompts.QA, 0.1).strip()
            if "NOT_ON_THESE_SHEETS" not in txt.upper():
                findings.append(txt)
        except Exception as e:
            status.warning(f"Sheet group {idx + 1} could not be read: {e}")

        del payload
        gc.collect()
        bar.progress(int(((idx + 1) / total) * 90))

    bar.progress(100)
    status.empty()

    if not findings:
        return ("Not found on the sheets searched. Try widening your sheet selection, or "
                "run the Sheet Indexer so questions can be routed to the right sheets.")
    if len(findings) == 1:
        return findings[0]

    merged = "\n\n---\n\n".join(findings)
    try:
        return ai.generate(
            [f"QUESTION: {question}\n\nPartial answers from different sheets:\n\n{merged}\n\n"
             f"Combine into one direct answer. Keep every sheet citation. If the partials "
             f"conflict, say so and flag it as a coordination issue."],
            prompts.QA, 0.1
        )
    except Exception:
        return merged
