"""
Stage 05.5 — Critic loop with quality rubric (Copilot architecture 3.8).

This is the "reviewer loop" pattern from the reference doc: a critic scores the
deck against an executive rubric and rewrites weak slides, then re-scores — up to
`critic_max_passes`. Unlike the single-pass narrative/requirements checks, this
loop keeps improving until the deck clears the quality gate or passes budget.

Rubric dimensions (0-2 each → 0-10 total):
  storyline · slide_density · factuality · visual_quality · exec_readiness

Returns (slides, score, one_line_assessment). Never throws.
"""
import json

from models.config import Settings
from models.schemas import SlideSpec


SYSTEM = """You are an executive presentation reviewer. Score a deck against this
rubric and rewrite ONLY the weakest slides' copy to raise the score.

RUBRIC (score each 0-2, sum to a 0-10 total):
- storyline:      slides follow a logical narrative arc, no gaps or jumps
- slide_density:  each slide has one clear idea; not overcrowded, not empty
- factuality:     claims are specific and consistent; no vague filler
- visual_quality: charts/diagrams match the message; layouts varied
- exec_readiness: headlines are sharp and decision-oriented

Return ONLY JSON, with "score" and "assessment" FIRST so they are never lost:
{
  "score": <0-10 total>,
  "assessment": "<one sentence>",
  "rewrites": [
    {"index": <int>, "headline": "<improved>", "body": "<improved, max 2 sentences>"}
  ]
}
Include AT MOST 4 slides in "rewrites" — only the weakest ones that genuinely
need improvement. Keep each rewritten body to 2 sentences.
Never change index/layout/section — only headline and body."""


async def run_critic_loop(
    slides: list[SlideSpec],
    prompt: str,
    settings: Settings,
) -> tuple[list[SlideSpec], float | None, str]:
    score: float | None = None
    assessment = ""

    for _ in range(max(1, settings.critic_max_passes)):
        result = await _critique_once(slides, prompt, settings)
        if result is None:
            break  # model unavailable — stop looping, keep what we have

        score, assessment, rewrites = result

        applied = 0
        by_index = {s.index: i for i, s in enumerate(slides)}  # index → list position
        for rw in rewrites:
            pos = by_index.get(rw.get("index"))
            if pos is None:
                continue
            slide = slides[pos]
            new_copy = dict(slide.copy)
            if rw.get("headline"):
                new_copy["headline"] = rw["headline"]
            if rw.get("body"):
                new_copy["body"] = rw["body"]
            if new_copy != slide.copy:
                slides[pos] = slide.model_copy(update={"copy": new_copy})
                applied += 1

        # Clean pass or already above the gate → stop early.
        if applied == 0 or (score is not None and score >= settings.quality_gate):
            break

    return slides, score, assessment


async def _critique_once(
    slides: list[SlideSpec],
    prompt: str,
    settings: Settings,
) -> tuple[float | None, str, list[dict]] | None:
    payload = [
        {
            "index": s.index,
            "layout": s.layout,
            "section": s.section,
            "headline": s.copy.get("headline", ""),
            "body": s.copy.get("body", "")[:300],
            "has_visual": s.visual is not None,
        }
        for s in slides
    ]

    try:
        from google.genai import types
        from utils.vertex import make_client
        from utils.jsonsafe import loads_tolerant

        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_critic,
            contents=f"Original request:\n{prompt}\n\nDeck:\n{json.dumps(payload)}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        data = loads_tolerant(response.text or "")
        if not isinstance(data, dict):
            return None
    except Exception:
        return None

    raw_score = data.get("score")
    try:
        score: float | None = max(0.0, min(10.0, float(raw_score)))
    except (TypeError, ValueError):
        score = None

    rewrites = data.get("rewrites", []) or []
    return score, data.get("assessment", ""), rewrites
