"""Deep-scan engines: clash audit, takeoff, submittals, doc intel, indexing.

REWRITTEN to use structured JSON output instead of scraping 'ISSUE:' /
'TAKEOFF:' prefixes out of free text. The old approach failed silently: on a
multi-batch run the merge pass would re-word the findings and drop the
prefixes, the parser would match nothing, and the UI would show an empty
result as though the scan had found no problems. Structured output plus a
Python-side merge removes that whole failure class.
"""
import re

import sp_ai as ai
import sp_prompts as prompts
from sp_config import DEEP_SCAN_BATCH


# ------------------------------------------------------------------ helpers

def _norm(s):
    """Loose key for dedupe: lowercase, collapse punctuation."""
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower())[:90].strip()


def _dedupe(records, key_fields):
    """The same finding often appears in overlapping batches. Keep the first,
    but merge the sheet citations so no reference is lost."""
    seen, out = {}, []
    for r in records:
        key = "|".join(_norm(r.get(f, "")) for f in key_fields)
        if not key.strip("|"):
            continue
        if key in seen:
            prior = seen[key]
            new_sheets = str(r.get("sheets") or r.get("sheet") or "")
            old_sheets = str(prior.get("sheets") or prior.get("sheet") or "")
            if new_sheets and new_sheets not in old_sheets:
                merged = f"{old_sheets}, {new_sheets}".strip(", ")
                if "sheets" in prior:
                    prior["sheets"] = merged
                else:
                    prior["sheet"] = merged
            continue
        seen[key] = r
        out.append(r)
    return out


SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# -------------------------------------------------------------- clash audit

CLASH_SCHEMA = """Return ONLY a JSON array. Each element must have exactly these fields:
- "issue": the problem, stated specifically (string)
- "category": one of "Phasing/Scope", "Equipment-MEP", "Spatial Clash", "Utility Capacity", "Code/Life Safety", "Missing Dimensions"
- "severity": one of "Critical", "High", "Medium"
- "sheets": the sheet name(s) this was found on (string)
- "impact": the practical field consequence if it isn't resolved (string)

If you find no qualifying issues on these sheets, return an empty array: []
Do not include cosmetic or drafting-quality observations."""


def clash_audit(file_bytes, pages, label_fn=None):
    """Returns (findings, warnings). findings: list of dicts."""
    user = ("Audit the attached drawing sheets. Apply the Frankenstein Rule and the other "
            "five critical failure points. Report only major, expensive, schedule-killing "
            "issues.\n\n" + CLASH_SCHEMA)

    records, failed = ai.batched_json_scan(
        file_bytes, pages, prompts.CLASH, user,
        batch_size=DEEP_SCAN_BATCH, label_fn=label_fn,
        progress_label="Auditing sheets",
    )
    findings = _dedupe(records, ["issue"])
    findings.sort(key=lambda r: SEVERITY_RANK.get(str(r.get("severity", "")).lower(), 9))

    warnings = []
    if failed:
        warnings.append(f"{len(failed)} sheet group(s) returned unreadable output: "
                        f"{'; '.join(failed)[:120]}")
    return findings, warnings


# ------------------------------------------------------------------ takeoff

TAKEOFF_SCHEMA = """Return ONLY a JSON array. Each element must have exactly these fields:
- "item": what is being counted (string)
- "quantity": numeric quantity (a number, not a string)
- "unit": unit of measure -- SF, LF, EA, CY, SY, TON, etc. (string)
- "material": material or specification (string)
- "division": CSI division name, e.g. "09 - Finishes" (string)
- "sheet": the sheet name it came from (string)
- "basis": "LABELED" if the quantity is printed or scheduled on the drawing, "DERIVED" if you calculated it from labeled dimensions (string)

Count only what is actually shown, dimensioned, or scheduled. If a quantity
cannot be determined without scaling the drawing, omit that item rather than
guessing. If nothing is quantifiable on these sheets, return an empty array: []"""


def takeoff(file_bytes, pages, label_fn=None):
    """Returns (items, warnings). items: list of dicts."""
    user = ("Perform a material takeoff from the attached sheets.\n\n" + TAKEOFF_SCHEMA)

    records, failed = ai.batched_json_scan(
        file_bytes, pages, prompts.TAKEOFF, user,
        batch_size=DEEP_SCAN_BATCH, label_fn=label_fn,
        progress_label="Counting materials",
    )

    clean = []
    for r in records:
        try:
            r["quantity"] = float(str(r.get("quantity", "")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        clean.append(r)

    items = _dedupe(clean, ["item", "unit"])
    items.sort(key=lambda r: (str(r.get("division", "zz")), str(r.get("item", ""))))

    warnings = []
    if failed:
        warnings.append(f"{len(failed)} sheet group(s) returned unreadable output: "
                        f"{'; '.join(failed)[:120]}")
    derived = sum(1 for i in items if str(i.get("basis", "")).upper() == "DERIVED")
    if derived:
        warnings.append(f"{derived} of {len(items)} quantities were calculated rather than "
                        f"read directly off the drawings - verify before ordering.")
    return items, warnings


def group_by_division(items):
    by_div = {}
    for i in items:
        by_div.setdefault(str(i.get("division", "Unclassified")), []).append(i)
    return dict(sorted(by_div.items()))


# ----------------------------------------------------------------- the rest

def submittals(file_bytes, pages):
    schema = """Return ONLY a JSON array. Each element must have:
- "item": what must be submitted (string)
- "type": one of "Shop Drawing", "Product Data", "Sample", "Certificate", "Closeout"
- "spec_section": spec section number if identifiable, else "" (string)
Return [] if none found."""
    records, _ = ai.batched_json_scan(
        file_bytes, pages, prompts.SUBMITTAL,
        "Extract every submittal requirement from these specification pages.\n\n" + schema,
        batch_size=DEEP_SCAN_BATCH, progress_label="Scanning specifications",
    )
    return _dedupe(records, ["item"])


def doc_intel(file_bytes, pages):
    user = ("Summarize the primary purpose, key data points, financial impacts, schedule "
            "impacts, and critical risks in this document.")
    return ai.batched_scan(file_bytes, pages, prompts.DOC_INTEL, user,
                           batch_size=DEEP_SCAN_BATCH,
                           progress_label="Reading document")


INDEX_BATCH = 8   # sheets per call -- ~8x fewer round trips than one-per-page


def build_index(file_bytes, total_pages, progress_cb=None, only_pages=None,
                existing=None):
    """Extract sheet numbers/titles from title blocks.

    REWRITTEN. The original made one API call per sheet and wrapped it in a
    bare `except`, so a rate-limit burst (very likely at ~100 rapid calls)
    turned every sheet into "Page N" while still reporting success -- the same
    silent-failure shape that made clash/takeoff look broken.

    Now: sheets are read in batches via structured JSON, failures are counted
    and returned rather than swallowed, and a failed batch retries page-by-page
    so one unreadable title block doesn't cost the other seven.

    only_pages lets you re-run just the ones that failed instead of all of them.
    Returns (index, failures) where failures is a list of page numbers.
    """
    index = dict(existing or {})
    pages = list(only_pages) if only_pages else list(range(1, total_pages + 1))
    failures = []
    done = 0

    def record(page, text):
        cleaned = str(text or "").strip().replace("\n", " ")
        cleaned = cleaned.replace("```", "").strip(" -\t")
        if not cleaned or len(cleaned) < 2:
            return False
        index[str(page)] = cleaned[:70]
        return True

    batches = [pages[i:i + INDEX_BATCH] for i in range(0, len(pages), INDEX_BATCH)]

    for batch in batches:
        prompt = (
            f"The {len(batch)} attached images are consecutive drawing sheets.\n"
            f"For EACH image, read the title block and extract its sheet number and "
            f"sheet title.\n\n"
            f'Return ONLY a JSON array with one entry per image, in the same order:\n'
            f'[{{"n": 1, "sheet": "A-101 - FLOOR PLAN"}}, {{"n": 2, "sheet": "..."}}]\n\n'
            f'"n" is the image position (1 to {len(batch)}). "sheet" is the number and '
            f'title joined by " - ". If a title block is unreadable, use "" for that entry.'
        )
        payload = [prompt]
        try:
            for pnum in batch:
                payload.append(ai.render_page(file_bytes, pnum))
        except Exception:
            failures.extend(batch)
            done += len(batch)
            if progress_cb:
                progress_cb(done, len(pages))
            continue

        got = ai.generate_json(
            payload,
            "You are a meticulous document archivist. Output only the requested JSON.",
            temperature=0.1, default=None,
        )
        if isinstance(got, dict):
            for v in got.values():
                if isinstance(v, list):
                    got = v
                    break

        resolved = set()
        if isinstance(got, list):
            for entry in got:
                if not isinstance(entry, dict):
                    continue
                try:
                    pos = int(entry.get("n", 0))
                except (TypeError, ValueError):
                    continue
                if 1 <= pos <= len(batch):
                    page = batch[pos - 1]
                    if record(page, entry.get("sheet")):
                        resolved.add(page)

        # Anything the batch missed gets one individual attempt, so a single
        # bad title block doesn't take the whole group down with it.
        for page in batch:
            if page in resolved:
                continue
            try:
                res = ai.generate(
                    ["Read this drawing title block. Output ONLY the sheet number and "
                     "sheet title in the format 'SheetNumber - SheetTitle', nothing else.",
                     ai.render_page(file_bytes, page)],
                    "You are a meticulous document archivist. Output strictly the "
                    "requested format with no other text.",
                    temperature=0.1, retries=1,
                )
                if not record(page, res):
                    failures.append(page)
            except Exception:
                failures.append(page)

        done += len(batch)
        if progress_cb:
            progress_cb(done, len(pages))

    # Any page still unnamed keeps a stable placeholder
    for page in pages:
        index.setdefault(str(page), f"Page {page}")

    return index, failures


def unnamed_pages(index):
    """Pages still sitting on a placeholder -- the re-run candidates."""
    out = []
    for k, v in (index or {}).items():
        if str(v).strip().lower().startswith("page "):
            try:
                out.append(int(k))
            except ValueError:
                pass
    return sorted(out)
