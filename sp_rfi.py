"""RFI drafting and PDF generation.

The AI drafts the formal language from your quick field notes; the PDF layout
is deterministic Python so every RFI comes out identically formatted and
looks like it came from a document control system, not a chat window.
"""
import re
from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos

import sp_ai as ai
import sp_prompts as prompts

NAVY = (14, 27, 46)
STEEL = (82, 98, 122)
SAFETY = (232, 89, 12)
INK = (16, 21, 28)
LINE = (200, 206, 214)


def draft(project, recipient, subject_hint, question_notes, sheets="",
          spec_section="", impact_notes="", suggested=""):
    """Turn rough field notes into formal RFI language. Returns a dict."""
    user = f"""Draft a formal RFI from these field notes.

PROJECT: {project.get('name', '')} {('#' + project['number']) if project.get('number') else ''}
DRAWING SHEETS INVOLVED: {sheets or 'not specified'}
SPEC SECTION: {spec_section or 'not specified'}

FIELD NOTES (informal, from the superintendent):
{question_notes}

SUBJECT HINT: {subject_hint or 'none given'}
IMPACT NOTES: {impact_notes or 'none given'}
SUGGESTED RESOLUTION FROM FIELD: {suggested or 'none offered'}

Return the JSON object described in your instructions."""

    result = ai.generate_json([user], prompts.RFI_WRITER, temperature=0.2, default=None)
    if not result:
        # Degrade to the raw notes rather than failing outright -- a usable
        # draft the user can edit beats an error message.
        return {
            "subject": subject_hint or "Request for Information",
            "background": "",
            "question": question_notes,
            "impact": impact_notes or "None identified at this time",
            "suggested_resolution": suggested,
            "_fallback": True,
        }
    return result


PAGE_H = 279.4          # Letter, mm
BOTTOM_MARGIN = 18.0    # leaves room for the footer rule at -16mm
RESPONSE_RECT_H = 34.0
RESPONSE_TOTAL_H = RESPONSE_RECT_H + 11.0   # rect + signature line beneath it


class _RFIDoc(FPDF):
    def __init__(self, company, rfi_no):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.company = company
        self.rfi_no = rfi_no
        self.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN)

    def header(self):
        # Navy title bar
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 216, 22, style="F")
        self.set_xy(14, 6)
        self.set_font("helvetica", "B", 15)
        self.set_text_color(255, 255, 255)
        self.cell(120, 8, "REQUEST FOR INFORMATION", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("helvetica", "B", 13)
        self.set_text_color(*SAFETY)
        self.set_xy(150, 6)
        self.cell(52, 8, f"RFI #{self.rfi_no}", align="R")
        self.set_text_color(*INK)
        self.set_y(30)

    def footer(self):
        self.set_y(-16)
        self.set_draw_color(*LINE)
        self.line(14, self.get_y() - 2, 202, self.get_y() - 2)
        self.set_font("helvetica", "", 7.5)
        self.set_text_color(*STEEL)
        self.cell(94, 6, self.company, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(94, 6, f"RFI #{self.rfi_no}  |  Page {self.page_no()}", align="R")


def _clean(txt):
    """fpdf core fonts are latin-1 only. Map the characters that actually
    show up in AI output instead of dropping them silently."""
    if txt is None:
        return ""
    s = str(txt)
    for bad, good in [
        ("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
        ("\u2014", " - "), ("\u2013", "-"), ("\u2026", "..."), ("\u00a0", " "),
        ("\u2022", "-"), ("\u2032", "'"), ("\u2033", '"'),
        ("\u00bd", "1/2"), ("\u00bc", "1/4"), ("\u00be", "3/4"),
        ("\u00b0", " deg"), ("\u00d7", "x"), ("\u2260", "!="),
        ("**", ""), ("###", ""), ("##", ""),
    ]:
        s = s.replace(bad, good)
    # The em-dash swap above inserts spaces; if the source already had them
    # we end up with "word  -  word". Collapse runs of spaces.
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.encode("latin-1", "replace").decode("latin-1")


def _field_grid(pdf, rows):
    """Two-column label/value block, ruled like a transmittal form."""
    pdf.set_draw_color(*LINE)
    for label, value in rows:
        y = pdf.get_y()
        pdf.set_font("helvetica", "B", 7.5)
        pdf.set_text_color(*STEEL)
        pdf.set_x(14)
        pdf.cell(34, 7, _clean(label).upper(), border=0)
        pdf.set_font("helvetica", "", 9.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(154, 7, _clean(value) or "-", border=0)
        pdf.line(14, pdf.get_y(), 202, pdf.get_y())
        pdf.set_y(max(pdf.get_y(), y + 7))


def _section(pdf, title, body):
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 8.5)
    pdf.set_text_color(*SAFETY)
    pdf.set_x(14)
    pdf.cell(188, 6, _clean(title).upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(*INK)
    pdf.set_x(14)
    pdf.multi_cell(188, 5.6, _clean(body) or "-")


def build_pdf(rfi, project, recipient, company="SCK Contractors"):
    """rfi: dict from draft() plus the user's metadata. Returns PDF bytes."""
    pdf = _RFIDoc(company, rfi.get("number", "---"))
    pdf.add_page()

    # Subject
    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(*INK)
    pdf.set_x(14)
    pdf.multi_cell(188, 6.5, _clean(rfi.get("subject", "Request for Information")))
    pdf.ln(3)

    _field_grid(pdf, [
        ("Project", f"{project.get('name','')}"
                    f"{'  |  #' + project['number'] if project.get('number') else ''}"),
        ("Location", project.get("location", "")),
        ("To", f"{recipient.get('name','')}"
               f"{', ' + recipient['company'] if recipient.get('company') else ''}"),
        ("Attn / Email", recipient.get("email", "")),
        ("From", f"{recipient.get('from_name','')}"
                 f"{', ' + company if company else ''}"),
        ("Date Issued", rfi.get("date", datetime.now().strftime("%B %d, %Y"))),
        ("Response Needed By", rfi.get("due", "")),
        ("Priority", rfi.get("priority", "Normal")),
        ("Drawing Refs", rfi.get("sheets", "")),
        ("Spec Section", rfi.get("spec_section", "")),
    ])

    if rfi.get("background"):
        _section(pdf, "Background", rfi["background"])
    _section(pdf, "Information Requested", rfi.get("question", ""))
    _section(pdf, "Schedule / Cost Impact", rfi.get("impact", "None identified at this time"))
    if rfi.get("suggested_resolution"):
        _section(pdf, "Suggested Resolution (for design team review)", rfi["suggested_resolution"])

    # Response block -- left blank for the recipient.
    # Break to a new page ONLY if the whole block genuinely won't fit; the
    # earlier fixed threshold orphaned it onto page 2 with 7cm of page 1 free.
    pdf.ln(4)
    if pdf.get_y() + RESPONSE_TOTAL_H > (PAGE_H - BOTTOM_MARGIN):
        pdf.add_page()
    y = pdf.get_y()

    pdf.set_fill_color(245, 247, 249)
    pdf.set_draw_color(*LINE)
    pdf.rect(14, y, 188, RESPONSE_RECT_H, style="DF")
    pdf.set_xy(18, y + 3)
    pdf.set_font("helvetica", "B", 8.5)
    pdf.set_text_color(*STEEL)
    pdf.cell(180, 5, "RESPONSE (to be completed by design team)")
    pdf.set_draw_color(190, 196, 204)
    for i in range(4):
        ly = y + 12 + (i * 5.6)
        pdf.line(18, ly, 198, ly)

    pdf.set_xy(18, y + RESPONSE_RECT_H + 3)
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*STEEL)
    pdf.cell(90, 5, "Signed: ______________________________")
    pdf.cell(90, 5, "Date: ____________________", align="R")

    return bytes(pdf.output())
