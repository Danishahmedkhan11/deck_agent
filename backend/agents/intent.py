"""
Stage 02a — Intent Understanding (Copilot architecture 3.2).

Runs BEFORE planning. Classifies what the user actually wants so every
downstream agent (planner, copy, critic) adapts its behaviour: a board review
should read differently from an engineering deep-dive or a training deck.

Cheap, fast, and non-fatal — falls back to sensible defaults derived from the
requested deck_type if the model is unavailable.
"""
import json

from models.config import Settings
from models.schemas import IntentSpec


SYSTEM = """You are the intent-understanding step of a presentation generator.
Read the user's request and classify it. Return ONLY a JSON object:
{
  "audience":   "<who this is for, e.g. board, sales leadership, engineers, customers>",
  "tone":       "<voice the copy should use, e.g. confident and board-ready>",
  "purpose":    "<the single job this deck must accomplish, one sentence>",
  "deck_kind":  "<board_review|sales_qbr|project_plan|pitch|analysis|training>",
  "data_heavy": <true if the ask centres on numbers/charts/metrics, else false>,
  "key_topics": ["<specific topics the user named that MUST be covered>"],
  "constraints": ["<any branding, confidentiality, length or format constraints>"],
  "recommended_slides": <integer 5-16 — the RIGHT number of slides for this
     content and audience: a quick summary or exec update is 5-8, a standard
     review is 8-11, a detailed analysis with several topics is 12-16. Always
     include cover, agenda and close in the count.>,
  "source_mode": "<'provided_content' if the user has already WRITTEN the actual
     content to put on the slides — e.g. they pasted sections, achievements,
     bullet points, or detailed paragraphs to lay out faithfully. Use 'topic'
     only if they gave a short subject to research/expand.>",
  "visuals": "<'none' if the user said not to include charts/graphs/metrics/
     visuals; 'minimal' if they want few; otherwise 'auto'>"
}
No prose outside the JSON."""


async def run_intent(prompt: str, deck_type: str, settings: Settings) -> IntentSpec:
    try:
        from google.genai import types
        from utils.vertex import make_client

        client = make_client(settings)
        response = await client.aio.models.generate_content(
            model=settings.model_intent,
            contents=f"Requested deck_type: {deck_type}\n\nUser request:\n{prompt}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text.strip())
        return IntentSpec(
            audience=data.get("audience", "executives"),
            tone=data.get("tone", "confident, board-ready"),
            purpose=data.get("purpose", ""),
            deck_kind=data.get("deck_kind", deck_type),
            data_heavy=bool(data.get("data_heavy", False)),
            key_topics=[str(t) for t in data.get("key_topics", []) if t][:8],
            constraints=[str(c) for c in data.get("constraints", []) if c][:6],
            recommended_slides=_coerce_count(data.get("recommended_slides")),
            source_mode=_coerce_mode(data.get("source_mode"), prompt),
            visuals=_coerce_visuals(data.get("visuals"), prompt),
        )
    except Exception:
        return _fallback_intent(prompt, deck_type)


def _coerce_mode(v, prompt: str) -> str:
    if str(v).strip().lower() == "provided_content":
        return "provided_content"
    # Heuristic backstop: a long prompt with review-style structure is content.
    markers = ("what went well", "could have been better", "overview", "achievement", "h2 goal")
    if len(prompt) > 700 and sum(m in prompt.lower() for m in markers) >= 2:
        return "provided_content"
    return "topic"


def _coerce_visuals(v, prompt: str) -> str:
    s = str(v).strip().lower()
    if s in ("none", "minimal"):
        return s
    pl = prompt.lower()
    if any(p in pl for p in ("no chart", "no charts", "without chart", "no graph",
                             "don't need the metric", "no metric", "no visual", "no bar", "no pie")):
        return "none"
    return "auto"


def _coerce_count(v) -> int:
    """Clamp the model's recommendation into a sane 4-20 range (0 = unset)."""
    try:
        return max(4, min(20, int(v)))
    except (TypeError, ValueError):
        return 0


def _fallback_intent(prompt: str, deck_type: str) -> IntentSpec:
    """Deterministic default when the model is unavailable."""
    return IntentSpec(
        audience="executives",
        tone="confident, board-ready",
        purpose=prompt[:120],
        deck_kind=deck_type,
        data_heavy=any(w in prompt.lower() for w in
                       ("data", "chart", "metric", "revenue", "budget", "spend", "number", "trend")),
        key_topics=[],
        constraints=[],
        # Rough heuristic: longer / richer asks → more slides.
        recommended_slides=8 if len(prompt) < 200 else (11 if len(prompt) < 500 else 14),
        source_mode=_coerce_mode(None, prompt),
        visuals=_coerce_visuals(None, prompt),
    )
