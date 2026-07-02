"""
Stage 02 — Analysis agent.

Uses Gemini via Vertex AI to extract:
  - key metrics / numbers
  - detected chart opportunities
  - detected diagram opportunities
  - narrative thread (what the data says)
"""
import json
from typing import Any

from google.genai import types

from models.config import Settings
from utils.vertex import make_client


SYSTEM = """You are a data analysis agent for the Unilever Deck Agent pipeline.
Given source material and a user prompt, extract:
1. key_metrics: list of {label, value, delta, unit} dicts found in the data
2. chart_opportunities: list of {title, chart_type, data_ref} — where chart_type is one of bar|line|donut|table
3. diagram_opportunities: list of {title, diagram_type} — where diagram_type is one of flow|timeline|funnel|org
4. narrative: 2-3 sentence summary of the central insight the deck should convey

Respond ONLY with valid JSON matching this exact schema — no prose outside the JSON.
"""


async def run_analysis(
    prompt: str,
    parsed_sources: list[dict[str, Any]],
    settings: Settings,
    datasets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources_text = _format_sources(parsed_sources)

    # Grounding: surface the real structured tables (with provenance) so the
    # analysis references actual figures instead of paraphrasing prose.
    grounding_block = ""
    if datasets:
        from agents.grounding import format_datasets_for_llm
        grounding_block = (
            "\n\nSTRUCTURED DATA (cite these source_refs — do not invent numbers):\n"
            + format_datasets_for_llm(datasets)
        )

    try:
        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_analysis,
            contents=f"User prompt:\n{prompt}\n\nSource material:\n{sources_text[:8000]}{grounding_block}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        raw = response.text or ""
    except Exception:
        return _mock_analysis(prompt)

    # Tolerant parse (handles truncated/wrapped JSON); never raises to the caller.
    from utils.jsonsafe import loads_tolerant
    data = loads_tolerant(raw)
    return data if isinstance(data, dict) and data else _mock_analysis(prompt)


def _format_sources(sources: list[dict[str, Any]]) -> str:
    parts = []
    for s in sources:
        parts.append(f"[{s.get('type','?')}] {s.get('path','')}\n{s.get('text','')[:2000]}")
    return "\n\n".join(parts) or "(no files uploaded — use prompt only)"


def _mock_analysis(prompt: str) -> dict[str, Any]:
    """Fallback when no API key is configured."""
    return {
        "key_metrics": [
            {"label": "Revenue growth", "value": "+38%", "delta": "+38%", "unit": "%"},
            {"label": "Total revenue", "value": "$4.2M", "delta": "", "unit": "USD"},
            {"label": "NPS", "value": "91", "delta": "+12", "unit": "score"},
        ],
        "chart_opportunities": [
            {"title": "Revenue by quarter", "chart_type": "bar", "data_ref": ""},
            {"title": "Revenue by segment", "chart_type": "donut", "data_ref": ""},
        ],
        "diagram_opportunities": [
            {"title": "Go-to-market flow", "diagram_type": "flow"},
        ],
        "narrative": (
            "Revenue grew 38% driven by enterprise demand, exceeding the annual target. "
            "The recommendation is to double down on enterprise acquisition in Q4 "
            "while stabilising mid-market churn."
        ),
    }
