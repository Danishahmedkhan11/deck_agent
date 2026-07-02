"""Stage 04 Specialist — Diagram engine."""
import json
from typing import Any

from models.config import Settings
from models.schemas import SlideSpec, VisualSpec


SYSTEM = """You are a diagram specialist for executive presentations.
Generate meaningful node/step labels for flow, timeline, or funnel diagrams.
Return ONLY a valid JSON array — no prose, no markdown fences."""


async def run_diagram(
    slides: list[SlideSpec],
    analysis: dict[str, Any],
    prompt: str,
    settings: Settings,
) -> list[dict | None]:
    patches: list[dict | None] = [None] * len(slides)

    diag_slides = [
        {
            "list_index": i,
            "slide_index": slide.index,
            "headline": slide.copy.get("headline", ""),
            "section": slide.section,
        }
        for i, slide in enumerate(slides)
        if slide.layout == "diagram"
    ]

    if not diag_slides:
        return patches

    diag_ops = {d["title"]: d for d in analysis.get("diagram_opportunities", [])}

    user_msg = f"""Presentation prompt: {prompt}

Generate diagram node data for these slides:
{json.dumps(diag_slides, indent=2)}

Available diagram opportunities from analysis:
{json.dumps(list(diag_ops.values()), indent=2)}

Return a JSON array — one object per slide:
  list_index    — integer, same as input
  diagram_type  — "flow" | "timeline" | "funnel"
  nodes         — array of 3-6 short label strings (the steps/phases)
  caption       — brief description

Keep node labels concise (2-4 words each)."""

    try:
        from google.genai import types
        from utils.vertex import make_client

        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_diagram,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )
        items = json.loads(response.text.strip())

        for item in items:
            idx = item.get("list_index")
            if idx is None or not (0 <= idx < len(slides)):
                continue
            patches[idx] = {
                "visual": VisualSpec(
                    type=item.get("diagram_type", "flow"),
                    caption=item.get("caption", slides[idx].copy.get("headline", "")),
                    data={"nodes": item.get("nodes", [])},
                )
            }

    except Exception:
        for info in diag_slides:
            idx = info["list_index"]
            if diag_ops:
                title, op = next(iter(diag_ops.items()))
                del diag_ops[title]
                patches[idx] = {
                    "visual": VisualSpec(
                        type=op.get("diagram_type", "flow"),
                        caption=title,
                        data={"nodes": ["Step 1", "Step 2", "Step 3", "Step 4"]},
                    )
                }

    return patches
