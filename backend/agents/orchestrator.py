"""
Stage 03 — Orchestrator (frontier LLM).

Plans the full slide structure, assigns layouts, and routes each slide
to the appropriate specialist model tier.
"""
import json
from typing import Any

from google.genai import types

from models.config import Settings
from utils.vertex import make_client
from models.schemas import DeckSpec, DeckType, SlideSpec, VisualSpec
from brand.unilever_2026 import STRUCTURE_LOCK, LAYOUT_MAP


SYSTEM = """You are the orchestrator for the Unilever Deck Agent.
Given the user prompt, analysis data, and the brand's locked slide structure, produce a
complete slide plan as JSON.

RULES (hard):
- Follow the brand's locked section order exactly: {sections}
- Use layouts from this set ONLY: cover, agenda, context, findings, chart, metrics, diagram, recommendation, roadmap, close, left, right
- Each slide must have: index(int), section(str), layout(str), copy dict with "headline" and "body" keys
- Total slides must equal the requested count

LAYOUT GUIDANCE (choose for visual variety and structure clarity):
- "cover"          — first slide only; big title, no body text needed
- "agenda"         — second slide; list agenda items in body (one per line, · separated)
- "context"        — full-width text: background, goals, problem statement
- "findings"       — full-width text: key insights and supporting narrative
- "left"           — TWO-COLUMN: title on LEFT half; body text lower-left; chart/table on RIGHT half
                     USE WHEN: a slide has BOTH narrative text AND data/chart to show side-by-side
- "right"          — TWO-COLUMN: title on RIGHT half; chart/table on LEFT half; key points lower-right
                     USE WHEN: chart is the hero — leads the eye; text reinforces on the right
- "chart"          — FULL-WIDTH chart: use when the visual is the entire message (no supporting text)
- "metrics"        — 4-box KPI grid; body = "label: value · label: value · label: value · label: value"
- "diagram"        — horizontal flow diagram; visual.data.nodes = list of step labels
- "roadmap"        — coloured phase boxes; body = "Phase 1 · Phase 2 · Phase 3"
- "recommendation" — full-width text: clear recommendation statement with supporting rationale
- "close"          — final slide; key next steps as bullets; body = one line per action

VISUAL SPEC RULES:
- Assign a visual spec to ALL "chart", "left", and "right" slides — they require chart data
- For visual spec, include: type (bar|column|line|pie|donut|table), caption, data (labels + series)
- Generate REALISTIC data values derived from the prompt topic (do NOT leave data empty)
- For a "left" or "right" slide, generate concise body text (2-3 sentences) AND a visual spec
- Only plan "left" or "right" when you will include a visual spec with chart data

HEADLINE RULES (CRITICAL for layout quality):
- Keep headlines SHORT: maximum 6 words / 45 characters
- Good: "Defense Budget Highlights", "Top 5 Spending Sectors"
- Bad: "Key Fiscal Metrics: Deficit, Revenue, Capital Expenditure" (too long, wraps and collides)
- A colon is allowed: "Defense: Key Priorities" but keep each half short

VARIETY RULE:
- Do NOT use the same layout more than 3 times in a row
- A deck of 8+ slides MUST include at least: 1 chart/left/right, 1 metrics or diagram/roadmap
- Distribute layout types across the deck for visual rhythm

Respond ONLY with a JSON object: {{"title": "...", "slides": [...]}}
No prose outside the JSON.
"""


SYSTEM_FIDELITY = """You are laying out CONTENT THE USER HAS ALREADY WRITTEN into a
professional slide deck. Your job is faithful structuring, NOT summarising.

ABSOLUTE RULES:
- PRESERVE the user's content. Keep every specific: numbers (e.g. €8,500),
  product/system names (ADLS, Unity Catalog, UDL/BDL/PDS, Gold/Silver indexes),
  and every detail. Do NOT shorten, generalise, or drop facts.
- Follow the USER'S structure and headings, not a generic template.
- If the user lists items each with "Overview", "What Went Well", and
  "What Could Have Been Better", give EACH ITEM its own slide using layout
  "achievement", with copy fields: headline (the item name), overview,
  went_well, could_better — filled from the user's own words (lightly tidied).
- Put any "H2 Goal" content on its own "recommendation" or "findings" slide,
  grouped sensibly.
- {visual_rule}

DECK SHAPE:
- Slide 0: "cover" (headline = the deck title).
- Slide 1: "agenda" listing the sections (body: items separated by " · ").
- Then the achievement slides (one per item), in the user's order.
- Then H2 goals slide(s).
- Final slide: "close" with a brief wrap-up.
- Choose the slide count to fit the content — do not pad or truncate.

Use section names that reflect the user's framing (e.g. "Key Achievements",
"H2 Goals", "Close"). Allowed layouts: cover, agenda, achievement, findings,
recommendation, context, close.

Respond ONLY with JSON: {{"title": "...", "slides": [
  {{"index": int, "section": str, "layout": str,
    "copy": {{"headline": str, "overview": str, "went_well": str,
             "could_better": str, "body": str}}}}
]}}
Include only the copy keys relevant to each layout. No prose outside the JSON.
"""


async def run_orchestrator(
    req,
    analysis: dict[str, Any],
    settings: Settings,
    intent=None,
    slide_count: int | None = None,
    auto_count: bool = False,
) -> DeckSpec:
    fidelity = bool(intent and getattr(intent, "source_mode", "topic") == "provided_content")
    sections_str = " → ".join(STRUCTURE_LOCK)
    target = slide_count or req.slide_count or 8
    count_line = (
        f"Slide count: choose the right number yourself (~{target}, allowed 4-20) "
        f"based on how much content the topic and data warrant.\n"
        if auto_count else
        f"Slide count: {target} (produce exactly this many)\n"
    )

    intent_block = ""
    if intent is not None:
        intent_block = (
            f"\nAudience: {intent.audience}\n"
            f"Tone: {intent.tone}\n"
            f"Purpose: {intent.purpose}\n"
            f"Data-heavy: {intent.data_heavy}\n"
            f"Must-cover topics: {', '.join(intent.key_topics) or '(none specified)'}\n"
            f"Constraints: {', '.join(intent.constraints) or '(none)'}\n"
        )

    if fidelity:
        visuals = getattr(intent, "visuals", "auto")
        visual_rule = (
            "Do NOT add any charts, tables, or diagrams — the user asked for none."
            if visuals == "none" else
            "Only add a chart/diagram where the user's content explicitly calls for one."
        )
        system_instruction = SYSTEM_FIDELITY.format(visual_rule=visual_rule)
        # Give the model the FULL content; do not lean on the summarised analysis.
        contents = (
            f"Deck title: {(req.title or '').strip() or 'Presentation'}\n"
            f"Audience: {getattr(intent, 'audience', 'executives')}\n\n"
            f"USER CONTENT TO LAY OUT FAITHFULLY:\n\"\"\"\n{req.prompt}\n\"\"\""
        )
    else:
        system_instruction = SYSTEM.format(sections=sections_str)
        contents = (
            f"User prompt: {req.prompt}\n\n"
            f"Deck type: {req.deck_type}\n"
            f"{count_line}"
            f"{intent_block}\n"
            f"Analysis:\n{json.dumps(analysis, indent=2)}"
        )

    try:
        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_orchestrator,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        raw = response.text or ""
    except Exception:
        return _mock_deck(req, analysis)

    # Tolerant parse + guarded build — a malformed plan degrades to the mock deck
    # rather than 500-ing the whole request.
    from utils.jsonsafe import loads_tolerant
    data = loads_tolerant(raw)
    if not isinstance(data, dict) or not data.get("slides"):
        return _mock_deck(req, analysis)
    try:
        deck = _parse_deck(data, req)
        return deck if deck.slides else _mock_deck(req, analysis)
    except Exception:
        return _mock_deck(req, analysis)


def _parse_deck(data: dict, req) -> DeckSpec:
    slides = []
    for pos, s in enumerate(data.get("slides", [])):
        visual = None
        if v := s.get("visual"):
            visual = VisualSpec(**v)
        slides.append(SlideSpec(
            index=pos,   # normalise: index == array position (identity == position)
            section=s.get("section", ""),
            layout=s.get("layout", "findings"),
            copy=s.get("copy", {}),
            visual=visual,
            speaker_notes=s.get("speaker_notes", ""),
        ))
    return DeckSpec(
        brand_id="unilever-2026",
        deck_type=req.deck_type,
        title=data.get("title", "Unilever Deck"),
        slide_count=len(slides),
        slides=slides,
    )


def _mock_deck(req, analysis: dict) -> DeckSpec:
    """Deterministic mock deck used when no API key is set."""
    narrative = analysis.get("narrative", "")
    metrics = analysis.get("key_metrics", [])
    m_str = "  ·  ".join(f"{m['label']}: {m['value']}" for m in metrics[:3])

    slides = [
        SlideSpec(index=0, section="Cover", layout="cover",
                  copy={"headline": req.prompt[:60], "body": "Unilever · 2026"}),
        SlideSpec(index=1, section="Agenda", layout="agenda",
                  copy={"headline": "Agenda", "body": "Context · Findings · Recommendations · Next steps"}),
        SlideSpec(index=2, section="Context & goals", layout="context",
                  copy={"headline": "Context & goals", "body": narrative}),
        SlideSpec(index=3, section="Findings & data", layout="chart",
                  copy={"headline": "Revenue by quarter", "body": m_str},
                  visual=VisualSpec(type="bar_chart", source_ref="Q3_Financials.xlsx",
                                    data={"labels":["Q1","Q2","Q3","Q4e"],
                                          "series":[{"name":"Enterprise","values":[2.1,2.7,3.5,4.2]},
                                                    {"name":"Mid-market","values":[1.1,1.4,1.9,2.5]}]},
                                    caption="Revenue $M")),
        SlideSpec(index=4, section="Findings & data", layout="metrics",
                  copy={"headline": "Key metrics", "body": m_str}),
        SlideSpec(index=5, section="Findings & data", layout="diagram",
                  copy={"headline": "Go-to-market flow", "body": ""},
                  visual=VisualSpec(type="flow", data={"nodes":["Research","Build","Launch","Measure","Scale"]})),
        SlideSpec(index=6, section="Findings & data", layout="findings",
                  copy={"headline": "Three core findings", "body": narrative}),
        SlideSpec(index=7, section="Recommendation", layout="recommendation",
                  copy={"headline": "Recommended path forward", "body": "Double down on enterprise · Stabilise mid-market · Launch Q4 campaign"}),
        SlideSpec(index=8, section="Recommendation", layout="chart",
                  copy={"headline": "Revenue by segment", "body": ""},
                  visual=VisualSpec(type="donut_chart", data={"segments":[{"label":"Enterprise","value":68},{"label":"Mid-market","value":32}]})),
        SlideSpec(index=9, section="Next steps & close", layout="roadmap",
                  copy={"headline": "Roadmap — H2 2026", "body": "Q3 · Q4 · Q1 2027"}),
        SlideSpec(index=10, section="Next steps & close", layout="findings",
                  copy={"headline": "Risks & mitigations", "body": "Competition · Churn · Macro headwinds"}),
        SlideSpec(index=11, section="Next steps & close", layout="close",
                  copy={"headline": "Thank you", "body": "Appendix available on request"}),
    ]

    return DeckSpec(
        brand_id="unilever-2026",
        deck_type=req.deck_type,
        title="Q3 Board Review — Unilever",
        slide_count=len(slides),
        slides=slides,
    )
