"""Stage 04 Specialist — Visual media (section icons + optional AI imagery)."""
import asyncio
import base64

from models.config import Settings
from models.schemas import SlideSpec, VisualSpec

# Curated icon mapping per section — no generative image calls needed
SECTION_ICONS: dict[str, str] = {
    "Cover": "presentation",
    "Agenda": "list",
    "Context & goals": "target",
    "Findings & data": "chart-bar",
    "Recommendation": "lightbulb",
    "Next steps & close": "flag",
}

# Layouts that can host a generated image without clashing with their content.
_IMAGE_TEXT_LAYOUTS = {"context", "findings", "recommendation"}


async def run_visual_media(
    slides: list[SlideSpec],
    settings: Settings,
    generate_images: bool = False,
    topic: str = "",
) -> list[dict | None]:
    # IMPORTANT: icon patches are ADDITIVE (`copy_icon`) so they never clobber
    # refined copy. Image patches set `visual`. A slide gets at most one.
    patches: list[dict | None] = [None] * len(slides)

    image_targets: list[int] = []
    if generate_images:
        image_targets = _pick_image_targets(slides)

    # 1) Kick off image generations concurrently (best-effort).
    if image_targets:
        from utils.imagegen import generate_image
        prompts = [_image_prompt(slides[i], topic) for i in image_targets]
        results = await asyncio.gather(
            *[generate_image(p, settings) for p in prompts],
            return_exceptions=True,
        )
        for i, raw in zip(image_targets, results):
            if isinstance(raw, (bytes, bytearray)) and raw:
                b64 = base64.b64encode(raw).decode("ascii")
                patches[i] = {"visual": VisualSpec(type="image", data={"image_b64": b64},
                                                   caption="")}

    # 2) Icons for the remaining light slides (skip ones that got an image).
    for i, slide in enumerate(slides):
        if patches[i] is not None:
            continue
        icon = SECTION_ICONS.get(slide.section)
        if icon and slide.visual is None and slide.layout in ("cover", "context", "recommendation", "close"):
            patches[i] = {"copy_icon": icon}

    return patches


def _pick_image_targets(slides: list[SlideSpec], cap: int = 3) -> list[int]:
    targets: list[int] = []
    # Cover first (hero image).
    for i, s in enumerate(slides):
        if s.layout == "cover":
            targets.append(i)
            break
    # Then a couple of text slides with no existing visual.
    for i, s in enumerate(slides):
        if len(targets) >= cap:
            break
        if i in targets:
            continue
        if s.layout in _IMAGE_TEXT_LAYOUTS and s.visual is None:
            targets.append(i)
    return targets


def _image_prompt(slide: SlideSpec, topic: str) -> str:
    headline = slide.copy.get("headline", "") or topic
    if slide.layout == "cover":
        return (
            f"A professional abstract background illustration for a corporate presentation "
            f"titled '{headline}'. Modern, clean, deep blue and navy palette, subtle geometric "
            f"shapes, lots of empty negative space, soft gradient, no text, no words, no letters."
        )
    return (
        f"A minimal professional illustration representing '{headline}' "
        f"({topic}). Flat modern vector style, corporate blue palette, clean, "
        f"lots of white space, no text, no words, no letters."
    )
