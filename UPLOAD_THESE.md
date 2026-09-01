# Flat version — no folders

Everything sits at the top level now. GitHub's file picker can select these,
so you don't have to drag folders (which is what kept failing).

## What to do

1. In your repo, click **Add file → Upload files**
2. Click **"choose your files"** — the picker works fine now, there are no folders
3. Select **all 21 files** in this folder (Ctrl+A)
4. Commit

That's it. No settings to change — the entry point is already named
`SitePilotAI_Cloud.py`, which is what Streamlit is already pointed at.

## Cleaning up afterwards (optional)

Your repo will still have `app.py` and `config.py` from the earlier attempt.
They're harmless — nothing loads them — but you can delete them if you like
tidy. `SitePilotAI_Cloud.py` replaces `app.py` as the entry point.

## The files

| File | What it is |
|---|---|
| `SitePilotAI_Cloud.py` | **entry point** — the app itself |
| `sp_config.py` | settings, colours, batch sizes |
| `sp_ai.py` | Gemini calls, PDF rendering, batching |
| `sp_firebase.py` | cloud saving (optional, degrades gracefully) |
| `sp_projects.py` | project directory + memory |
| `sp_prompts.py` | all AI instructions, in one place |
| `sp_analysis.py` | clash audit, takeoff, submittals, indexer |
| `sp_qa.py` | ask-the-drawings |
| `sp_schedule.py` | timeline + Gantt fill |
| `sp_estimate.py` | cost maths + Excel export |
| `sp_rfi.py` | RFI drafting + PDF |
| `sp_suggestions.py` | photo analysis, two-week look-ahead |
| `sp_compat.py` | Streamlit version shim |
| `sp_viewer.py` | drawing viewer (pan/zoom) |
| `sp_ai_panel.py` | the AI sidebar |
| `sp_estimator.py` | estimator screen |
| `sp_photos.py` | photo library |
| `sp_rfi_panel.py` | RFI screen |
| `gantt_template.xlsx` | your boss's Gantt template (50 rows) |
| `requirements.txt` | Python packages |
| `packages.txt` | system packages (poppler) |

## Optional: fix the dark-text contrast

Not required to run. When you're ready:

Repo → **Add file → Create new file** → filename exactly `.streamlit/config.toml`
(typing the slash creates the folder), then paste:

```toml
[theme]
base = "light"
primaryColor = "#E8590C"
backgroundColor = "#F3F5F7"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#10151C"
font = "sans serif"
```

## If it still errors

Click **Manage app** at the bottom right of the app, scroll the black log panel
to the bottom, and send me the block starting with `Traceback`.
