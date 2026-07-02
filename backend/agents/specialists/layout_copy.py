"""
Stage 04 Specialist — Layout & copy model.

Refines headline / body copy for every slide using a fast LLM call.
Falls back to orchestrator copy if no API key is available.
"""
import json
from typing import Any

from models.config import Settings
from models.schemas import SlideSpec


SYSTEM = """You are a copywriter for Unilever executive presentations.
Given a list of slide specs (JSON array), return an improved copy version of each slide.
Rules:
- Headlines: max 8 words, punchy, data-led where possible
- Body: max 25 words, one crisp insight per bullet
- Tone: confident, board-room appropriate
Return ONLY a JSON array of objects with keys: index, headline, body.
"""


async def run_layout_copy(
    slides: list[SlideSpec],
    prompt: str,
    settings: Settings,
) -> list[dict | None]:
    from google.genai import types
    from utils.vertex import make_client

    payload = [{"index": s.index, "section": s.section, "headline": s.copy.get("headline",""), "body": s.copy.get("body","")} for s in slides]

    try:
        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_layout,
            contents=f"User prompt context: {prompt}\n\nSlides:\n{json.dumps(payload)}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()
        improved = json.loads(raw)
    except Exception:
        return [None] * len(slides)

    # Align patches by LIST POSITION (not slide.index) to match how the pipeline
    # merges them. slide.index is treated as identity only.
    patches = [None] * len(slides)
    by_index = {item["index"]: item for item in improved}
    for pos, slide in enumerate(slides):
        if item := by_index.get(slide.index):
            patches[pos] = {
                "copy": {
                    "headline": item.get("headline", slide.copy.get("headline", "")),
                    "body": item.get("body", slide.copy.get("body", "")),
                }
            }
    return patches
