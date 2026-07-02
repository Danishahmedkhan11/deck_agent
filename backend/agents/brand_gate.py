"""
Stage 05 — Brand gate (hard lock).

Validates the final DeckSpec against Unilever 2026 brand rules.
Raises BrandViolationError if any hard rule is broken — the pipeline
must not proceed to render with a failing spec.
"""
from models.schemas import DeckSpec
from brand.unilever_2026 import STRUCTURE_LOCK, ALLOWED_LAYOUTS, BRAND_COLORS


class BrandViolationError(Exception):
    """Raised when the deck violates a hard brand rule."""


async def run_brand_gate(deck: DeckSpec) -> None:
    _check_structure(deck)
    # Content-fidelity decks follow the user's own structure, not the locked
    # section order — so we skip the order check for them (cover/close, layout
    # set, and count are still enforced).
    if not (deck.intent and deck.intent.source_mode == "provided_content"):
        _check_section_order(deck)
    _check_layouts(deck)
    _check_slide_count(deck)


def _check_section_order(deck: DeckSpec) -> None:
    """
    Enforce the locked section order the orchestrator is prompted to follow.
    The deck's sections must appear as an in-order subsequence of STRUCTURE_LOCK
    (sections may repeat or be skipped, but must never appear out of order).
    """
    lock = [s.lower() for s in STRUCTURE_LOCK]
    cursor = 0
    for slide in deck.slides:
        sec = slide.section.lower().strip()
        if not sec:
            continue
        # find this section at or after the current cursor
        match = next((i for i in range(cursor, len(lock))
                      if lock[i] in sec or sec in lock[i]), None)
        if match is None:
            # allowed to stay on the same section; only fail on backward jumps
            earlier = next((i for i in range(0, cursor)
                            if lock[i] in sec or sec in lock[i]), None)
            if earlier is not None:
                raise BrandViolationError(
                    f"Slide {slide.index} section '{slide.section}' breaks the locked "
                    f"order {STRUCTURE_LOCK}"
                )
        else:
            cursor = match


def _check_structure(deck: DeckSpec) -> None:
    """First slide must be Cover, last must be close section."""
    if not deck.slides:
        raise BrandViolationError("Deck has no slides")

    first = deck.slides[0]
    if first.layout != "cover":
        raise BrandViolationError(
            f"First slide must use 'cover' layout, got '{first.layout}'"
        )

    last = deck.slides[-1]
    close_keywords = ("next steps", "close", "conclusion", "summary", "outlook", "thank")
    if not any(kw in last.section.lower() for kw in close_keywords):
        raise BrandViolationError(
            f"Last slide must be a closing section, got '{last.section}'"
        )


def _check_layouts(deck: DeckSpec) -> None:
    for slide in deck.slides:
        if slide.layout not in ALLOWED_LAYOUTS:
            raise BrandViolationError(
                f"Slide {slide.index} uses unknown layout '{slide.layout}'. "
                f"Allowed: {sorted(ALLOWED_LAYOUTS)}"
            )


def _check_slide_count(deck: DeckSpec) -> None:
    if len(deck.slides) < 4:
        raise BrandViolationError(
            f"Deck must have at least 4 slides (Cover → Close), got {len(deck.slides)}"
        )
