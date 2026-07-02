"""
Stage 05.3 — Requirements QA Check.

Validates the generated deck against the original user prompt and applies
targeted patches to close gaps:
  • Wrong or missing chart types (bar, pie, donut, line, table)
  • Thin / bullet-only explanation slides that need real paragraphs
  • Requested images or videos not yet surfaced
  • Key topics from the prompt not covered by any slide

The agent never throws — it always returns the (possibly patched) slides.
"""
import json
from typing import Any

from models.config import Settings
from models.schemas import SlideSpec, VisualSpec


SYSTEM = """You are a senior presentation consultant doing a final quality review.
Your job: compare a client's original brief against the current slide plan, then
produce a compact JSON list of targeted fixes.
Return ONLY valid JSON — no prose, no markdown fences."""


class RQAResult:
    """Wraps the patched slides list together with audit metadata."""
    def __init__(self, slides: list[SlideSpec], score: Any, applied: int, assessment: str):
        self.slides     = slides
        self.score      = score
        self.applied    = applied
        self.assessment = assessment


async def run_requirements_check(
    slides: list[SlideSpec],
    prompt: str,
    settings: Settings,
) -> RQAResult:
    """Entry point — always returns an RQAResult (patched or original)."""
    try:
        return await _check_and_patch(slides, prompt, settings)
    except Exception:
        return RQAResult(slides, "?", 0, "")


async def _check_and_patch(
    slides: list[SlideSpec],
    prompt: str,
    settings: Settings,
) -> RQAResult:
    from google.genai import types
    from utils.vertex import make_client

    summary = [
        {
            "list_pos":      i,
            "layout":        s.layout,
            "section":       s.section,
            "headline":      s.copy.get("headline", "")[:60],
            "body_chars":    len(s.copy.get("body", "")),
            "visual_type":   s.visual.type if s.visual else None,
            "has_chart_data": bool(
                s.visual and s.visual.data and
                (s.visual.data.get("labels") or s.visual.data.get("headers"))
            ),
        }
        for i, s in enumerate(slides)
    ]

    user_msg = f"""USER'S ORIGINAL PRESENTATION REQUEST:
\"\"\"{prompt}\"\"\"

CURRENT DECK PLAN ({len(slides)} slides):
{json.dumps(summary, indent=2)}

Identify gaps between the request and the plan. Produce AT MOST 6 fixes.

WHAT TO CHECK:
1. CHART TYPES — did the user ask for bar, pie, donut, column, line, or table?
   Are those chart types present (visual_type field)?
   If a chart slide exists but uses the wrong type, fix it with "update_visual_type".

2. EXPLANATION DEPTH — are there slides with body_chars < 100 on a findings, context,
   or recommendation layout? If the user asked for "explanation", "analysis",
   "summary", "detail", or "paragraph", those slides need richer text.
   Fix with "enrich_body" — write 2-4 meaningful sentences drawn from the prompt topic.

3. IMAGES / VIDEO — if the user explicitly asked for images or video, flag with
   "add_media_note" on the most relevant slide. We cannot auto-fetch media, so this
   becomes a visible note in the body text.

4. MISSING TOPICS — if the user mentioned a specific topic (e.g. "education spending",
   "defense budget", "trend over time") and NO slide headline covers it, flag with
   "enrich_body" on the closest slide and expand its body to address the topic.

RETURN FORMAT (strict JSON, no extra keys):
{{
  "completeness_score": <0-10>,
  "assessment": "<one sentence>",
  "fixes": [
    {{
      "gap_type": "wrong_chart_type|missing_explanation|missing_topic|media_request",
      "list_pos": <integer 0-{len(slides)-1}>,
      "action": "update_visual_type|enrich_body|add_media_note|no_action",
      "new_visual_type": "<bar|pie|donut|column|line|table>",
      "new_body": "<replacement body — 2-4 sentences, substantive>",
      "media_note": "<description of image/video that should appear here>"
    }}
  ]
}}

RULES:
- Only suggest "update_visual_type" for slides where has_chart_data is true.
- For "enrich_body", new_body MUST be longer than the current body_chars.
- For "add_media_note", set action to "add_media_note".
- Do NOT add or remove slides — only patch existing ones.
- list_pos must be a valid integer (0 to {len(slides) - 1}).
"""

    client = make_client(settings)
    response = await client.aio.models.generate_content(
        model=settings.model_requirements,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            max_output_tokens=2048,
            response_mime_type="application/json",
        ),
    )

    result     = json.loads(response.text.strip())
    fixes      = result.get("fixes", [])
    _raw_score = result.get("completeness_score", None)
    # Normalise to int 0-10 or "?" if unparseable
    try:
        score = max(0, min(10, int(str(_raw_score).split("/")[0].strip())))
    except (TypeError, ValueError):
        score = "?"
    assessment = result.get("assessment", "")

    applied = 0
    for fix in fixes:
        action   = fix.get("action", "no_action")
        list_pos = fix.get("list_pos")

        if action == "no_action" or list_pos is None:
            continue
        if not isinstance(list_pos, int) or not (0 <= list_pos < len(slides)):
            continue

        slide = slides[list_pos]

        if action == "update_visual_type":
            new_type = (fix.get("new_visual_type") or "").strip().lower()
            valid = {"bar", "pie", "donut", "column", "line", "table"}
            if new_type in valid and slide.visual and slide.layout == "chart":
                slides[list_pos] = slide.model_copy(update={
                    "visual": slide.visual.model_copy(update={"type": new_type})
                })
                applied += 1

        elif action == "enrich_body":
            new_body = (fix.get("new_body") or "").strip()
            current_len = len(slide.copy.get("body", ""))
            if new_body and len(new_body) > current_len:
                new_copy = dict(slide.copy)
                new_copy["body"] = new_body
                slides[list_pos] = slide.model_copy(update={"copy": new_copy})
                applied += 1

        elif action == "add_media_note":
            note = (fix.get("media_note") or "").strip()
            if note:
                new_copy = dict(slide.copy)
                body = new_copy.get("body", "")
                separator = "\n\n" if body else ""
                new_copy["body"] = f"{body}{separator}[Recommended visual: {note}]"
                slides[list_pos] = slide.model_copy(update={"copy": new_copy})
                applied += 1

    return RQAResult(slides, score, applied, assessment)
