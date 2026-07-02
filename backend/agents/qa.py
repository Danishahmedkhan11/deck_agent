"""
Stage 04.5 — Narrative QA (LLM critic).

Reviews the full slide list for story coherence:
  - Does each slide follow logically from the last?
  - Are headlines consistent in tense and person?
  - Are any slides duplicated or contradictory?

Returns the (potentially reordered / patched) slide list.
"""
import json
from models.config import Settings
from models.schemas import SlideSpec


SYSTEM = """You are a narrative quality reviewer for executive presentations.
Given a JSON array of slide specs, return the same array with any copy improvements needed for coherence.
Only change copy — never change index, section, or layout.
Return ONLY the JSON array.
"""


async def run_narrative_qa(slides: list[SlideSpec], settings: Settings) -> list[SlideSpec]:
    from google.genai import types
    from utils.vertex import make_client

    payload = [s.model_dump(exclude={"visual", "speaker_notes"}) for s in slides]

    try:
        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_qa,
            contents=json.dumps(payload),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        revised = json.loads(response.text.strip())
        by_index = {r["index"]: r for r in revised}
        for slide in slides:
            if r := by_index.get(slide.index):
                slide.copy = r.get("copy", slide.copy)
    except Exception:
        pass  # QA failure is non-fatal

    return slides
