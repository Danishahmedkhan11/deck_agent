"""
Stage 05.4 — Deck Validator (deterministic, no LLM call).

Runs a structural quality check on the DeckSpec BEFORE rendering and fixes
issues that would produce broken slides:

  1. Left/Right without chart data → downgrade to "findings" layout
     (prevents the empty dashed placeholder and body-text-over-title problems)

  2. Headline too long (>50 chars) → trim to last word boundary under 50
     (prevents title overflow colliding with body content at any font size)

  3. Body text too short (<60 chars) on content slides → add a note so the
     slide doesn't render as a near-empty page (visual minimum)

This runs in a tight loop (max 2 passes) until no further issues are found,
matching the "iterate until expectations are met" pattern the user asked for.
No latency is added because there are no LLM calls.
"""
from models.schemas import SlideSpec, VisualSpec

_NEEDS_CHART = {"chart", "left", "right"}
_TEXT_LAYOUTS = {"context", "findings", "recommendation"}


def _has_chart_data(visual: VisualSpec | None) -> bool:
    if not visual:
        return False
    d = visual.data or {}
    if visual.type == "table":
        return bool(d.get("headers") or d.get("rows"))
    return bool(d.get("labels") and d.get("series"))


def _trim_headline(text: str, max_chars: int = 50) -> str:
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    # Trim to last word boundary
    last_space = trimmed.rfind(" ")
    return trimmed[:last_space].rstrip(" ,:;-") if last_space > 0 else trimmed


def _validate_pass(slides: list[SlideSpec]) -> tuple[list[SlideSpec], list[str]]:
    """Single validation pass. Returns (patched_slides, list_of_issues_fixed)."""
    fixes: list[str] = []
    result: list[SlideSpec] = []

    for slide in slides:
        updated = {}

        # ── Rule 1: left/right without chart data ───────────────────────────
        if slide.layout in ("left", "right") and not _has_chart_data(slide.visual):
            updated["layout"] = "findings"
            fixes.append(
                f"slide {slide.index}: downgraded '{slide.layout}' → 'findings' (no chart data)"
            )

        # ── Rule 2: headline too long ────────────────────────────────────────
        headline = slide.copy.get("headline", "")
        if len(headline) > 50:
            trimmed = _trim_headline(headline)
            new_copy = dict(slide.copy)
            new_copy["headline"] = trimmed
            updated["copy"] = new_copy
            fixes.append(
                f"slide {slide.index}: headline trimmed {len(headline)}→{len(trimmed)} chars"
            )

        # ── Rule 3: body too short on text-heavy slides ─────────────────────
        layout = updated.get("layout", slide.layout)
        if layout in _TEXT_LAYOUTS:
            body = (updated.get("copy") or slide.copy).get("body", "")
            if 0 < len(body) < 60:
                new_copy = dict(updated.get("copy") or slide.copy)
                sec_lower = slide.section.lower()
                if "recommendation" in sec_lower:
                    suffix = f" This outlines the recommended action and strategy for {sec_lower} to ensure project success."
                elif any(kw in sec_lower for kw in ("next steps", "close", "conclusion", "summary", "outlook", "thank", "roadmap")):
                    suffix = f" This concludes the analysis and summarizes the next steps for execution and close."
                else:
                    suffix = f" This covers a key aspect of {sec_lower}, providing context for the recommendation that follows."
                new_copy["body"] = body + suffix
                updated["copy"] = new_copy
                fixes.append(
                    f"slide {slide.index}: body padded (was {len(body)} chars)"
                )

        if updated:
            result.append(slide.model_copy(update=updated))
        else:
            result.append(slide)

    return result, fixes


def run_deck_validation(slides: list[SlideSpec], max_passes: int = 2) -> tuple[list[SlideSpec], list[str]]:
    """
    Run up to max_passes validation loops until no further issues are found.
    Returns (final_slides, all_fixes_applied).
    """
    all_fixes: list[str] = []
    for _ in range(max_passes):
        slides, fixes = _validate_pass(slides)
        all_fixes.extend(fixes)
        if not fixes:
            break  # clean pass — stop looping
    return slides, all_fixes
