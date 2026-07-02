"""
Stage 04.7 — Speaker Notes agent (Copilot §2 capability).

Generates a short presenter script for every slide from its final copy + intent.
Notes are attached to SlideSpec.speaker_notes and written into the PPTX notes
pane by the renderer. Non-fatal: on failure slides keep empty notes.
"""
import json

from models.config import Settings
from models.schemas import IntentSpec, SlideSpec


SYSTEM = """You write concise speaker notes for a presenter delivering a deck.
For each slide you receive (index, headline, body), write 2-3 sentences the
presenter would SAY out loud — not a repeat of the on-slide text, but the
context, the "so what", and the transition to the next idea.
Match the requested audience and tone.
Return ONLY a JSON array of objects: {"index": <int>, "notes": "<text>"}."""


async def run_speaker_notes(
    slides: list[SlideSpec],
    intent: IntentSpec | None,
    settings: Settings,
) -> list[SlideSpec]:
    payload = [
        {
            "index": s.index,
            "headline": s.copy.get("headline", ""),
            "body": s.copy.get("body", "")[:280],
            "layout": s.layout,
        }
        for s in slides
    ]
    aud = intent.audience if intent else "executives"
    tone = intent.tone if intent else "confident, board-ready"

    try:
        from google.genai import types
        from utils.vertex import make_client
        from utils.jsonsafe import loads_tolerant

        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_notes,
            contents=(
                f"Audience: {aud}\nTone: {tone}\n\n"
                f"Slides:\n{json.dumps(payload)}"
            ),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        notes = loads_tolerant(response.text or "") or []
        by_index = {n["index"]: n.get("notes", "") for n in notes if isinstance(n, dict) and "index" in n}
        for s in slides:
            note = by_index.get(s.index)
            if note:
                s.speaker_notes = note
    except Exception:
        pass  # notes are a nice-to-have — never block the deck

    return slides
