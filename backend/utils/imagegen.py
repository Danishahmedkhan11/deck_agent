"""
Image generation via Gemini 2.5 Flash Image ("Nano Banana") on Vertex AI.

Returns raw PNG/JPEG bytes for a text prompt, or None on any failure — image
generation is always best-effort and must never block a deck from rendering.
"""
from __future__ import annotations

from models.config import Settings

IMAGE_MODEL = "gemini-2.5-flash-image"


async def generate_image(prompt: str, settings: Settings) -> bytes | None:
    try:
        from google.genai import types
        from utils.vertex import make_client

        client = make_client(settings)
        resp = await client.aio.models.generate_content(
            model=IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for cand in resp.candidates or []:
            for part in cand.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    return inline.data
    except Exception as exc:
        print(f"[imagegen] failed: {exc}")
    return None
