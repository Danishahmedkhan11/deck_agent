"""
Stage 04 Specialist — Data visualisation model.

Makes a real Gemini call to generate actual chart data (labels + numeric series)
for every chart-layout slide. Falls back to caption-only spec on failure.
"""
import json
from typing import Any

from models.config import Settings
from models.schemas import SlideSpec, VisualSpec


SYSTEM = """You are a data visualisation specialist for executive presentations.

GROUNDING RULES (critical):
- If STRUCTURED DATA is provided, you MUST take chart figures from it and set
  "source_ref" to the dataset's source_ref and "grounded" to true. Do NOT invent
  numbers when real data exists — select, aggregate, or pick the top rows.
- Only if NO structured data is provided may you invent representative figures.
  In that case set "grounded" to false and "source_ref" to "".

Return ONLY a valid JSON array — no prose, no markdown fences."""


async def run_data_viz(
    slides: list[SlideSpec],
    analysis: dict[str, Any],
    prompt: str,
    settings: Settings,
    datasets: list[dict[str, Any]] | None = None,
) -> list[dict | None]:
    patches: list[dict | None] = [None] * len(slides)

    VISUAL_LAYOUTS = {"chart", "left", "right"}
    chart_slides = [
        {
            "list_index": i,
            "slide_index": slide.index,
            "headline": slide.copy.get("headline", ""),
            "section": slide.section,
            "layout": slide.layout,
            "existing_type": slide.visual.type if slide.visual else None,
        }
        for i, slide in enumerate(slides)
        if slide.layout in VISUAL_LAYOUTS
    ]

    if not chart_slides:
        return patches

    # Grounding block — real datasets with provenance (empty if none uploaded)
    from agents.grounding import format_datasets_for_llm, has_grounding
    grounded = has_grounding(datasets or [])
    grounding_block = (
        f"\n\nSTRUCTURED DATA (use these real figures + cite source_ref):\n"
        f"{format_datasets_for_llm(datasets or [])}"
        if grounded else
        "\n\n(No structured data uploaded — you may use illustrative figures.)"
    )

    user_msg = f"""Presentation prompt: {prompt}

Analysis:
{json.dumps(analysis, indent=2)}
{grounding_block}

Generate chart data for these slides:
{json.dumps(chart_slides, indent=2)}

Return a JSON array — one object per slide with these fields:
  list_index   — integer, same as input
  chart_type   — "column" | "bar" | "line" | "pie" | "donut" | "table"
  labels       — array of category label strings (omit for "table")
  series       — array of {{"name": string, "values": [number, ...]}} (omit for "table")
  headers      — array of column header strings ("table" only)
  rows         — array of row arrays ("table" only)
  caption      — short description string
  grounded     — true if figures came from STRUCTURED DATA, else false
  source_ref   — the dataset source_ref you used (or "" if illustrative)

Guidelines:
- column/bar for comparisons, line for trends, pie/donut for proportions, table for detailed breakdowns
- 4-7 categories, numeric values appropriate to the topic (billions, percentages, etc.)
- When STRUCTURED DATA is present, DERIVE values from it and set grounded=true
- Table rows: 4-8 rows max, concise cell text"""

    try:
        from google.genai import types
        from utils.vertex import make_client

        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_data_viz,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        items = json.loads(response.text.strip())

        for item in items:
            idx = item.get("list_index")
            if idx is None or not (0 <= idx < len(slides)):
                continue
            chart_type = item.get("chart_type", "column")
            if chart_type == "table":
                data = {"headers": item.get("headers", []), "rows": item.get("rows", [])}
            else:
                data = {"labels": item.get("labels", []), "series": item.get("series", [])}
            # Only trust the grounded flag when we actually supplied datasets.
            is_grounded = bool(grounded and item.get("grounded"))
            patches[idx] = {
                "visual": VisualSpec(
                    type=chart_type,
                    caption=item.get("caption", slides[idx].copy.get("headline", "")),
                    data=data,
                    grounded=is_grounded,
                    source_ref=item.get("source_ref", "") if is_grounded else "",
                )
            }

    except Exception:
        # Fallback: assign chart type from analysis without data
        chart_ops = {c["title"]: c for c in analysis.get("chart_opportunities", [])}
        for info in chart_slides:
            idx = info["list_index"]
            if chart_ops:
                title, op = next(iter(chart_ops.items()))
                del chart_ops[title]
                patches[idx] = {
                    "visual": VisualSpec(
                        type=op.get("chart_type", "column"),
                        caption=title,
                    )
                }

    return patches
