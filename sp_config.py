"""Central configuration for Site Pilot.

Everything that might need to change in one place: the model name, storage
paths, and the design system. Changing MODEL_NAME here changes it everywhere.
"""

# ---- AI ----
# gemini-2.5-pro is retired Oct 2026. 3.6-flash is the current fast tier --
# built for latency and multi-step work, cheaper per token than 2.5-pro.
MODEL_NAME = "gemini-3.6-flash"

# Batch sizes tuned for memory safety. Each PDF page renders to a ~2-5MB
# in-memory image; holding 100 at once is what caused the original OOM crash.
DEEP_SCAN_BATCH = 12   # audit / takeoff / estimate: broad coverage
QA_BATCH = 8           # targeted Q&A: smaller, faster turnaround
PHOTO_BATCH = 6        # photos are smaller but numerous

# ---- Rendering ----
VIEWER_WIDTH = 1500      # px width for the on-screen drawing viewer
ANALYSIS_WIDTH = 1600    # px width for images sent to the AI
THUMB_WIDTH = 190        # px width for the sheet thumbnail rail

# ---- Gantt template ----
GANTT_TEMPLATE_PATH = "gantt_template.xlsx"
GANTT_TASK_START_ROW = 14
GANTT_MAX_TASK_ROWS = 50

# ---- Firestore collections ----
COL_PROJECTS = "projects"
COL_ARTIFACTS = "artifacts"   # timelines, audits, takeoffs, Q&A
COL_RFIS = "rfis"
COL_PHOTOS = "photos"

# ---- Design system ----
# Jobsite/blueprint vernacular rather than generic SaaS: structural navy,
# steel gray-blue, safety orange. Drawing surface stays neutral so sheets
# read true.
THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
    --sp-navy: #0E1B2E;
    --sp-navy-2: #1B2A42;
    --sp-steel: #52627A;
    --sp-ink: #10151C;
    --sp-safety: #E8590C;
    --sp-verified: #1F7A4D;
    --sp-alert: #C0392B;
    --sp-border: rgba(16, 27, 46, 0.14);
    --sp-surface: #F3F5F7;
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; letter-spacing: -0.02em; }

/* Tighten the default Streamlit padding -- the viewer needs the room */
.block-container { padding-top: 2.2rem; padding-bottom: 2rem; max-width: 100%; }

/* ---- Buttons ---- */
.stButton>button {
    border-radius: 3px;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 0.78em;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    background-color: var(--sp-safety);
    color: #ffffff;
    border: none;
    width: 100%;
    height: 2.7em;
    transition: filter 0.15s ease, box-shadow 0.15s ease;
}
.stButton>button:hover { filter: brightness(1.08); box-shadow: 0 2px 10px rgba(232, 89, 12, 0.28); }
.btn-ghost>button { background-color: transparent; color: var(--sp-steel); border: 1px solid var(--sp-border); }
.btn-ghost>button:hover { background-color: rgba(82, 98, 122, 0.08); filter: none; box-shadow: none; }

/* ---- Sidebar: the AI drawer ----
   CONTRAST RULE, learned the hard way: never set a text colour on an element
   whose background you don't also control. The earlier version forced light
   text on everything in the sidebar (killing the uploader's Browse button),
   then forced dark text on native buttons (which broke under a dark theme).
   Both were half-fixes. Here every native widget gets BOTH a background and a
   text colour, so contrast holds regardless of the viewer's theme. */
section[data-testid="stSidebar"] { background-color: var(--sp-navy); border-right: 1px solid rgba(255,255,255,0.06); }

/* Our own text, sitting directly on the navy */
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] div[data-testid="stCaptionContainer"] { color: #E8ECF1; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.1); }

/* File uploader: own both surfaces */
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    background-color: rgba(255,255,255,0.055);
    border: 1px dashed rgba(232,236,241,0.32);
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] div,
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] span,
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small { color: #C9D2DC; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
    background-color: rgba(232,236,241,0.14);
    color: #FFFFFF;
    border: 1px solid rgba(232,236,241,0.42);
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
    background-color: rgba(232,236,241,0.24);
}
/* Uploaded-file chips */
section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] * { color: #C9D2DC; }

/* Inputs, selects, textareas: light field, dark text -- both specified */
section[data-testid="stSidebar"] [data-baseweb="input"],
section[data-testid="stSidebar"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] [data-baseweb="textarea"] {
    background-color: #FFFFFF;
    border-color: rgba(232,236,241,0.28);
}
section[data-testid="stSidebar"] [data-baseweb="input"] input,
section[data-testid="stSidebar"] [data-baseweb="textarea"] textarea,
section[data-testid="stSidebar"] [data-baseweb="select"] > div { color: var(--sp-ink); }
section[data-testid="stSidebar"] [data-baseweb="input"] input::placeholder,
section[data-testid="stSidebar"] [data-baseweb="textarea"] textarea::placeholder { color: #8A94A3; }

/* Radio / checkbox labels sit on the navy, so keep them light */
section[data-testid="stSidebar"] [data-testid="stRadio"] label p,
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label p { color: #E8ECF1; }

/* Sidebar tabs */
section[data-testid="stSidebar"] div[data-testid="stTabs"] button[data-baseweb="tab"] { color: #94A3B4; }
section[data-testid="stSidebar"] div[data-testid="stTabs"] button[aria-selected="true"] {
    color: #FFFFFF; border-bottom-color: var(--sp-safety) !important;
}

/* Expanders in the sidebar */
section[data-testid="stSidebar"] [data-testid="stExpander"] { border-color: rgba(232,236,241,0.18); }
section[data-testid="stSidebar"] [data-testid="stExpander"] summary { color: #E8ECF1; }
section[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stMarkdownContainer"] { color: #D5DCE4; }

/* Ghost buttons inside the sidebar need the light treatment, not the
   canvas treatment -- they sit on navy, not on paper. */
section[data-testid="stSidebar"] .btn-ghost>button {
    color: #C9D2DC; border-color: rgba(232,236,241,0.32);
}
section[data-testid="stSidebar"] .btn-ghost>button:hover { background-color: rgba(232,236,241,0.12); }

/* ---- Tabs ---- */
div[data-testid="stTabs"] button[data-baseweb="tab"] {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600; font-size: 0.76em;
    letter-spacing: 0.03em; text-transform: uppercase;
    color: var(--sp-steel);
}
div[data-testid="stTabs"] button[aria-selected="true"] { color: var(--sp-ink); border-bottom-color: var(--sp-safety) !important; }

/* ---- Cards & panels ---- */
.tool-card { padding: 18px 20px; border-radius: 4px; border: 1px solid var(--sp-border); border-top: 3px solid var(--sp-steel); background-color: var(--secondary-background-color); margin-bottom: 16px; color: var(--text-color); }
.module-tag { font-family: 'IBM Plex Mono', monospace; font-size: 0.66em; letter-spacing: 0.08em; text-transform: uppercase; color: var(--sp-steel); margin-bottom: 9px; padding-bottom: 7px; border-bottom: 1px dashed var(--sp-border); }
.section-title { font-size: 1.18em; font-weight: 600; color: var(--text-color); margin-bottom: 5px; border-bottom: 2px solid var(--sp-border); padding-bottom: 7px; }
.report-box { padding: 16px 18px; border-radius: 3px; background-color: rgba(82, 98, 122, 0.07); border-left: 3px solid var(--sp-steel); color: var(--text-color); margin-top: 12px; font-size: 0.93em; overflow-x: auto; }
.report-box.accent-safety { border-left-color: var(--sp-safety); }
.report-box.accent-verified { border-left-color: var(--sp-verified); }
.report-box.accent-alert { border-left-color: var(--sp-alert); }
.ref-header { background-color: var(--sp-navy); color: #ffffff !important; padding: 7px 13px; border-radius: 3px 3px 0 0; font-weight: 600; font-family: 'IBM Plex Mono', monospace; font-size: 0.73em; letter-spacing: 0.06em; text-transform: uppercase; }

/* ---- Project bar: drawing title block ---- */
.title-block { display: flex; border: 1.5px solid var(--sp-ink); border-radius: 2px; overflow: hidden; margin-bottom: 16px; background-color: var(--secondary-background-color); flex-wrap: wrap; }
.tb-field { padding: 8px 16px; border-right: 1px solid var(--sp-border); display: flex; flex-direction: column; justify-content: center; min-width: 120px; }
.tb-field:last-child { border-right: none; flex: 1; }
.tb-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.6em; letter-spacing: 0.08em; text-transform: uppercase; color: var(--sp-steel); margin-bottom: 2px; }
.tb-value { font-family: 'IBM Plex Mono', monospace; font-size: 0.88em; font-weight: 600; color: var(--sp-ink); }
.tb-brand { background-color: var(--sp-navy); justify-content: center; align-items: center; min-width: 58px; border-right: 1.5px solid var(--sp-ink); }
.tb-brand .tb-value { color: #ffffff; font-family: 'Space Grotesk', sans-serif; font-size: 1em; }

/* ---- Status pills ---- */
.pill { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 0.64em; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 9px; border-radius: 2px; margin-right: 6px; }
.pill-live { background: rgba(31,122,77,0.14); color: var(--sp-verified); border: 1px solid rgba(31,122,77,0.3); }
.pill-local { background: rgba(232,89,12,0.12); color: var(--sp-safety); border: 1px solid rgba(232,89,12,0.3); }

/* ---- Hero ---- */
.hero-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 0.76em; letter-spacing: 0.14em; text-transform: uppercase; color: var(--sp-safety); margin-bottom: 12px; }
.hero-title { font-family: 'Space Grotesk', sans-serif; font-size: 2.9em; font-weight: 700; color: var(--sp-ink); margin-bottom: 6px; letter-spacing: -0.03em; }
.hero-sub { font-size: 1.08em; opacity: 0.75; color: var(--text-color); margin-bottom: 32px; max-width: 520px; margin-left: auto; margin-right: auto; }
</style>
"""
