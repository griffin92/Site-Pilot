"""Photo analysis and the two-week look-ahead engine.

The look-ahead is the payoff feature: it reconciles what the drawings say
SHOULD be happening against what the photos show IS happening, and turns the
gap into an actionable plan.
"""
import sp_ai as ai
import sp_prompts as prompts
from sp_config import PHOTO_BATCH


def analyze_photos(photos, focus=""):
    """photos: list of (label, PIL.Image). Returns observation text."""
    if not photos:
        return "No photos to analyze."
    labels = ", ".join(lbl for lbl, _ in photos[:PHOTO_BATCH])
    user = (
        f"Review these jobsite photos ({labels}) and report your field observations.\n"
        + (f"\nSPECIFIC FOCUS REQUESTED: {focus}\n" if focus else "")
        + "\nReport only what is actually visible in the photos."
    )
    return ai.analyze_images(photos, prompts.PHOTO_ANALYST, user, batch_size=PHOTO_BATCH)


def two_week_lookahead(photo_observations, schedule_context="",
                       scope_context="", today_label="", extra_notes=""):
    """Reconciles planned scope/schedule against observed field conditions."""
    parts = [f"TODAY'S DATE: {today_label}"] if today_label else []

    if scope_context:
        parts.append("PROJECT SCOPE (from drawings):\n" + scope_context[:4000])
    if schedule_context:
        parts.append("PLANNED SCHEDULE:\n" + schedule_context[:4000])
    if photo_observations:
        parts.append("FIELD OBSERVATIONS (from recent jobsite photos):\n" + photo_observations[:4000])
    if extra_notes:
        parts.append("SUPERINTENDENT NOTES:\n" + extra_notes)

    if not (schedule_context or photo_observations):
        return ("Not enough context yet. Generate a timeline and/or analyze jobsite photos "
                "first, then run the look-ahead so it has something to reconcile.")

    parts.append(
        "Produce the two-week look-ahead and action plan per your instructions. "
        "Where the photos and the planned schedule disagree, say so explicitly."
    )
    return ai.generate(["\n\n".join(parts)], prompts.SUGGESTION, 0.3)
