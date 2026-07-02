"""
Master pipeline — orchestrates all stages and yields SSE StageEvents.

Two reusable phases (so the deck can optionally be reviewed as an outline first):
  • compute_outline()     — phase 1: ingest → intent → analysis → planner
  • build_from_context()  — phase 2: specialists → QA → notes → checks → render

run_pipeline() runs both back-to-back (the one-shot path). The /api/outline and
/api/build endpoints call the two phases separately with a user-edit step between.

Mapped to the Copilot reference architecture (see architecture doc §3):
  01    Ingest & parse          deterministic                         (3.1 sources)
  02a   Intent understanding    LLM — audience/tone/purpose/topics    (3.2)
  02    Analysis / grounding    LLM over real structured datasets     (3.3)
  03    Orchestrator (planner)  LLM — storyline + layout routing      (3.4)
  04    Specialist models       4 models, concurrent                  (3.5 / 3.6)
  04.5  Narrative QA            LLM critic — story flow               (3.8)
  04.7  Speaker notes           LLM — presenter script                (3.5)
  05.3  Requirements check      LLM critic — deck vs user prompt      (3.8)
  05.4  Deck validator          deterministic structural loop         (3.8)
  05.5  Critic loop             LLM — rubric score + rewrite loop     (3.8)
  05    Brand gate              hard lock (structure/order/layouts)   (3.8 governance)
  06    Render                  deterministic python-pptx             (3.7)
  --    Persist DeckSpec        governance/audit + faithful preview   (3.8)
"""
import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from models.schemas import DeckSpec, GenerateRequest, IntentSpec, StageEvent, StageStatus
from models.config import Settings

from agents.ingest import ingest_files
from agents.grounding import extract_datasets
from agents.intent import run_intent
from agents.analysis import run_analysis
from agents.orchestrator import run_orchestrator
from agents.specialists.data_viz import run_data_viz
from agents.specialists.diagram import run_diagram
from agents.specialists.layout_copy import run_layout_copy
from agents.specialists.visual_media import run_visual_media
from agents.qa import run_narrative_qa
from agents.speaker_notes import run_speaker_notes
from agents.requirements_check import run_requirements_check
from agents.deck_validator import run_deck_validation
from agents.critic import run_critic_loop
from agents.brand_gate import run_brand_gate
from agents.render import render_pptx


def _evt(stage: str, status: StageStatus, msg: str = "", pct: int = 0) -> StageEvent:
    return StageEvent(stage=stage, status=status, message=msg, progress=pct)


def _apply_patch(slide, patch: dict):
    """Merge one specialist patch into a slide. The additive icon patch
    (`copy_icon`) is handled specially so it never clobbers refined copy."""
    if "copy_icon" in patch:
        new_copy = dict(slide.copy)
        new_copy["icon"] = patch["copy_icon"]
        return slide.model_copy(update={"copy": new_copy})
    return slide.model_copy(update=patch)


# ── Phase 1: plan the outline ──────────────────────────────────────────────────

async def compute_outline(req: GenerateRequest, settings: Settings) -> dict[str, Any]:
    """Ingest → intent → analysis → planner. Returns a serialisable context dict
    that build_from_context() (and the /api/build endpoint) consumes."""
    parsed = await ingest_files(req.file_ids, settings.upload_dir)
    datasets = extract_datasets(parsed)
    intent = await run_intent(req.prompt, req.deck_type.value, settings)
    analysis = await run_analysis(req.prompt, parsed, settings, datasets=datasets)

    auto_count = req.slide_count is None
    target = max(4, min(20, intent.recommended_slides or 8)) if auto_count else req.slide_count

    deck_spec = await run_orchestrator(
        req, analysis, settings, intent=intent, slide_count=target, auto_count=auto_count
    )
    deck_spec.intent = intent
    user_title = (req.title or "").strip()
    if user_title:
        deck_spec.title = user_title

    return {
        "prompt": req.prompt,
        "title": user_title,
        "auto_count": auto_count,
        "generate_images": bool(getattr(req, "generate_images", False)),
        "intent": intent.model_dump(),
        "analysis": analysis,
        "datasets": datasets,
        "deck_spec": deck_spec.model_dump(),
    }


# ── Phase 2: build the deck from a (possibly edited) outline ────────────────────

def _normalize_section_order(slides):
    """Stable-sort slides into the brand's locked section order so a user's
    outline reorder can never violate the brand gate. Reordering WITHIN a
    section is preserved (stable). Indices are renumbered to match."""
    from brand.unilever_2026 import STRUCTURE_LOCK
    lock = [s.lower() for s in STRUCTURE_LOCK]

    def rank(section: str) -> int:
        sl = (section or "").lower()
        for i, name in enumerate(lock):
            if name in sl or (sl and sl in name):
                return i
        return len(lock)  # unknown sections sort to the end

    ordered = [s for _, s in sorted(enumerate(slides), key=lambda t: (rank(t[1].section), t[0]))]
    return [s.model_copy(update={"index": i}) for i, s in enumerate(ordered)]


async def build_from_context(
    context: dict[str, Any], job_id: str, settings: Settings
) -> AsyncIterator[StageEvent]:
    deck_spec = DeckSpec(**context["deck_spec"])
    intent = IntentSpec(**context["intent"]) if context.get("intent") else None
    analysis = context.get("analysis") or {}
    datasets = context.get("datasets") or []
    prompt = context.get("prompt", "")
    user_title = (context.get("title") or "").strip()

    fidelity = bool(intent and intent.source_mode == "provided_content")
    visuals_off = bool(intent and intent.visuals == "none")
    gen_images = bool(context.get("generate_images"))
    img_topic = user_title or prompt[:80]

    # Topic decks are normalised to the locked section order. Content-fidelity
    # decks keep the user's own structure, so we do NOT reorder them.
    if not fidelity:
        deck_spec.slides = _normalize_section_order(deck_spec.slides)

    # ── 04 Specialists ────────────────────────────────────────────────────────
    yield _evt("04 · Specialist models", StageStatus.active,
               "Preparing slide content…" if fidelity else "Running specialist models…", 46)
    slides = deck_spec.slides
    if fidelity:
        # Preserve the user's exact content — only add section icons / imagery.
        tasks = [run_visual_media(slides, settings, generate_images=gen_images, topic=img_topic)]
    else:
        tasks = []
        if not visuals_off:
            tasks.append(run_data_viz(slides, analysis, prompt, settings, datasets=datasets))
            tasks.append(run_diagram(slides, analysis, prompt, settings))
        tasks.append(run_layout_copy(slides, prompt, settings))
        tasks.append(run_visual_media(slides, settings, generate_images=gen_images, topic=img_topic))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"[pipeline] Specialist model execution failed: {result}")
        elif isinstance(result, list):
            for i, patch in enumerate(result):
                if patch and i < len(slides):
                    slides[i] = _apply_patch(slides[i], patch)
    grounded_charts = sum(1 for s in slides if s.visual and s.visual.grounded)
    if fidelity:
        spec_msg = "Your content preserved · faithful layout"
    elif visuals_off:
        spec_msg = "Copy refined · visuals off per your request"
    else:
        spec_msg = (f"{grounded_charts} chart(s) built from your data"
                    if grounded_charts else "Specialist content generated")
    yield _evt("04 · Specialist models", StageStatus.done, spec_msg, 62)

    # ── 04.5 Narrative QA (skipped in fidelity — don't reword the user) ────
    if fidelity:
        yield _evt("04.5 · Narrative QA", StageStatus.done, "Preserving your wording", 68)
    else:
        yield _evt("04.5 · Narrative QA", StageStatus.active, "Reviewing story flow…", 64)
        deck_spec.slides = await run_narrative_qa(deck_spec.slides, settings)
        yield _evt("04.5 · Narrative QA", StageStatus.done, "Narrative coherence confirmed", 68)

    # ── 04.7 Speaker notes (safe — additive) ──────────────────────────────
    yield _evt("04.7 · Speaker notes", StageStatus.active, "Writing presenter script…", 70)
    deck_spec.slides = await run_speaker_notes(deck_spec.slides, intent, settings)
    n_notes = sum(1 for s in deck_spec.slides if s.speaker_notes)
    notes_msg = (f"{n_notes}/{len(deck_spec.slides)} slides annotated"
                 if n_notes else "No speaker notes generated")
    yield _evt("04.7 · Speaker notes", StageStatus.done, notes_msg, 74)

    # ── 05.3 Requirements check (skipped in fidelity — content is authoritative) ─
    if fidelity:
        yield _evt("05.3 · Requirements check", StageStatus.done,
                   "Using your content as provided", 80)
    else:
        yield _evt("05.3 · Requirements check", StageStatus.active,
                   "Validating deck against your request…", 76)
        rqa = await run_requirements_check(deck_spec.slides, prompt, settings)
        deck_spec.slides = rqa.slides
        rqa_msg = (f"{rqa.applied} gap(s) patched · completeness {rqa.score}/10"
                   if rqa.applied else f"All requirements met · completeness {rqa.score}/10")
        yield _evt("05.3 · Requirements check", StageStatus.done, rqa_msg, 80)

    # ── 05.4 Deck validator (structural — safe in both modes) ──────────────
    yield _evt("05.4 · Deck validator", StageStatus.active, "Checking layout structure…", 82)
    deck_spec.slides, val_fixes = run_deck_validation(deck_spec.slides)
    val_msg = (f"{len(val_fixes)} structural fix(es) applied"
               if val_fixes else "Structure validated — no issues")
    yield _evt("05.4 · Deck validator", StageStatus.done, val_msg, 84)

    # ── 05.5 Quality critic (skipped in fidelity — don't rewrite the user) ─
    if fidelity:
        deck_spec.quality_score = None
        deck_spec.quality_notes = ""
        yield _evt("05.5 · Quality critic", StageStatus.done,
                   "Skipped — your authored content", 87)
    else:
        yield _evt("05.5 · Quality critic", StageStatus.active,
                   "Scoring against executive rubric…", 85)
        deck_spec.slides, q_score, q_notes = await run_critic_loop(
            deck_spec.slides, prompt, settings
        )
        deck_spec.quality_score = q_score
        deck_spec.quality_notes = q_notes
        if q_score is not None:
            gate = "✓" if q_score >= settings.quality_gate else "⚠ below gate"
            crit_msg = f"Quality {q_score:.1f}/10 {gate}"
        else:
            crit_msg = "Critic review complete (unscored)"
        yield _evt("05.5 · Quality critic", StageStatus.done, crit_msg, 87)

    # Re-assert the user's title on the cover AFTER all copy stages.
    if user_title and deck_spec.slides:
        cover = deck_spec.slides[0]
        deck_spec.slides[0] = cover.model_copy(
            update={"copy": {**cover.copy, "headline": user_title}}
        )

    # ── 05 Brand gate ─────────────────────────────────────────────────────
    yield _evt("05 · Brand gate", StageStatus.active, "Enforcing Unilever brand rules…", 88)
    deck_spec.grounded = any(s.visual and s.visual.grounded for s in deck_spec.slides)
    await run_brand_gate(deck_spec)
    yield _evt("05 · Brand gate", StageStatus.done, "Brand check passed ✓", 90)

    # ── 06 Render ─────────────────────────────────────────────────────────
    yield _evt("06 · Render", StageStatus.active, "Building PPTX…", 92)
    out_path = await render_pptx(deck_spec, job_id, settings.upload_dir)
    _persist_spec(deck_spec, job_id, settings)
    yield _evt("06 · Render", StageStatus.done, f"Saved to {out_path}", 100)


# ── One-shot path: plan + build in a single stream ─────────────────────────────

async def run_pipeline(
    req: GenerateRequest, job_id: str, settings: Settings
) -> AsyncIterator[StageEvent]:
    # Phase 1 with granular progress events.
    yield _evt("01 · Ingest & parse", StageStatus.active, "Reading uploaded files…", 4)
    parsed = await ingest_files(req.file_ids, settings.upload_dir)
    datasets = extract_datasets(parsed)
    grounded_msg = (f"{len(parsed)} source(s) · {len(datasets)} dataset(s) grounded"
                    if datasets else f"{len(parsed)} source(s) parsed")
    yield _evt("01 · Ingest & parse", StageStatus.done, grounded_msg, 10)

    yield _evt("02a · Intent understanding", StageStatus.active,
               "Reading audience, tone and goal…", 12)
    intent = await run_intent(req.prompt, req.deck_type.value, settings)
    yield _evt("02a · Intent understanding", StageStatus.done,
               f"{intent.deck_kind} for {intent.audience}", 18)

    yield _evt("02 · Analysis & grounding", StageStatus.active,
               "Extracting insights from your data…", 20)
    analysis = await run_analysis(req.prompt, parsed, settings, datasets=datasets)
    yield _evt("02 · Analysis & grounding", StageStatus.done,
               "Key metrics identified from source data", 30)

    auto_count = req.slide_count is None
    if auto_count:
        target = max(4, min(20, intent.recommended_slides or 8))
        plan_msg = f"Auto: agent chose ~{target} slides"
    else:
        target = req.slide_count
        plan_msg = f"Planning {target} slides…"
    yield _evt("03 · Orchestrator", StageStatus.active, plan_msg, 32)
    deck_spec = await run_orchestrator(
        req, analysis, settings, intent=intent, slide_count=target, auto_count=auto_count
    )
    deck_spec.intent = intent
    user_title = (req.title or "").strip()
    if user_title:
        deck_spec.title = user_title
    done_msg = (f"{len(deck_spec.slides)} slides planned (auto)"
                if auto_count else f"{len(deck_spec.slides)} slides planned")
    yield _evt("03 · Orchestrator", StageStatus.done, done_msg, 42)

    # Phase 2 (shared with the outline-review path).
    context = {
        "prompt": req.prompt,
        "title": user_title,
        "auto_count": auto_count,
        "generate_images": bool(getattr(req, "generate_images", False)),
        "intent": intent.model_dump(),
        "analysis": analysis,
        "datasets": datasets,
        "deck_spec": deck_spec.model_dump(),
    }
    async for ev in build_from_context(context, job_id, settings):
        yield ev


def _persist_spec(deck: DeckSpec, job_id: str, settings: Settings) -> None:
    """Write the full DeckSpec sidecar for faithful preview + audit (governance)."""
    if not settings.persist_specs:
        return
    try:
        path = Path(settings.upload_dir) / f"{job_id}.spec.json"
        path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[pipeline] failed to persist deck spec: {exc}")
