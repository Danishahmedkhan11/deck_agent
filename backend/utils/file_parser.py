"""Utility helpers shared across the pipeline."""
import re


def clean_text(text: str, max_chars: int = 4000) -> str:
    """Normalise whitespace and truncate to max_chars."""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def format_currency(value: float, symbol: str = "$") -> str:
    if value >= 1_000_000:
        return f"{symbol}{value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"{symbol}{value/1_000:.0f}K"
    return f"{symbol}{value:.0f}"


def truncate_headline(text: str, max_words: int = 8) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"
