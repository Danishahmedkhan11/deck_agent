"""Shared Pydantic schemas — the core data contract."""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── deck types ──────────────────────────────────────────────────────────────

class DeckType(str, Enum):
    board_review = "board_review"
    sales_qbr = "sales_qbr"
    project_plan = "project_plan"
    pitch = "pitch"
    analysis = "analysis"


# ── intent understanding (Copilot layer 3.2) ────────────────────────────────

class IntentSpec(BaseModel):
    """Structured read of what the user actually wants, produced before planning."""
    audience: str = "executives"          # who the deck is for
    tone: str = "confident, board-ready"  # voice the copy should adopt
    purpose: str = ""                     # the job the deck must do
    deck_kind: str = "board_review"       # classified deck archetype
    data_heavy: bool = False              # does the ask centre on data/charts?
    key_topics: list[str] = Field(default_factory=list)  # must-cover topics
    constraints: list[str] = Field(default_factory=list)  # branding/confidentiality/etc.
    recommended_slides: int = 0           # agent's suggested count when user picks "Auto" (0 = unset)
    # Content mode: "topic" → expand/research a short prompt; "provided_content" →
    # the user pasted finished, structured content we must lay out FAITHFULLY.
    source_mode: str = "topic"
    # Visual preference derived from the prompt: "auto" | "none" | "minimal".
    visuals: str = "auto"


# ── pipeline stage events (SSE) ─────────────────────────────────────────────

class StageStatus(str, Enum):
    pending = "pending"
    active = "active"
    done = "done"
    error = "error"


class StageEvent(BaseModel):
    stage: str
    status: StageStatus
    message: str = ""
    progress: int = 0          # 0-100


# ── visual spec emitted by specialist models ─────────────────────────────────

class VisualSpec(BaseModel):
    type: str                   # "bar_chart" | "flow" | "image" | "icon_grid" | "donut" etc.
    source_ref: str = ""        # original data ref (filename + sheet + range) — provenance
    grounded: bool = False      # True if data was taken from an uploaded source, not invented
    data: dict[str, Any] = {}   # structured chart / diagram data
    caption: str = ""


# ── single slide spec ────────────────────────────────────────────────────────

class SlideSpec(BaseModel):
    index: int
    section: str                # "Cover" | "Agenda" | "Context" | ...
    layout: str                 # "cover" | "agenda" | "findings" | "chart" | "metrics" | "roadmap"
    copy: dict[str, str] = {}   # {"headline": "...", "body": "...", "label": "..."}
    visual: VisualSpec | None = None
    speaker_notes: str = ""


# ── full deck spec ───────────────────────────────────────────────────────────

class DeckSpec(BaseModel):
    brand_id: str = "unilever-2026"
    deck_type: DeckType = DeckType.board_review
    title: str = ""
    slide_count: int = 12
    slides: list[SlideSpec] = Field(default_factory=list)
    intent: IntentSpec | None = None                 # Copilot layer 3.2 output
    quality_score: float | None = None               # rubric score 0-10 (Copilot layer 3.8)
    quality_notes: str = ""                           # critic's one-line assessment
    grounded: bool = False                            # True if any slide used uploaded data


# ── request / response shapes ────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str
    title: str | None = None          # optional user title → cover headline + file name
    deck_type: DeckType = DeckType.board_review
    # None → "auto": the agent decides the count from the content/intent.
    slide_count: int | None = Field(default=None, ge=4, le=20)
    file_ids: list[str] = Field(default_factory=list)
    generate_images: bool = False     # opt-in AI imagery (Nano Banana / Gemini image)


class GenerateResponse(BaseModel):
    job_id: str
    status: str = "queued"
    download_url: str = ""
    deck_spec: DeckSpec | None = None
