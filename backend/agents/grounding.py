"""
Grounding layer (Copilot architecture 3.3).

Turns the raw parsed sources from stage 01 into normalised, cited datasets that
downstream specialists SELECT from — instead of inventing numbers.

A dataset carries its own provenance (`source_ref`) so a chart can point back to
the exact file + sheet it came from. This is what separates an evidence-based
deck from a plausible-looking hallucination.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _short(name: str) -> str:
    """Human-readable file label from a stored upload path (drops the UUID)."""
    stem = Path(name).name
    return stem


def extract_datasets(parsed_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalise Excel/CSV sources into a list of tabular datasets:
        {source_ref, columns: [...], rows: [[...], ...], n_rows}

    Only structured tabular sources yield datasets. PDFs/DOCX/text/images do not
    (their content still reaches the analysis agent as text) — we only ground
    *numeric charts* against real tables.
    """
    datasets: list[dict[str, Any]] = []

    for s in parsed_sources:
        stype = s.get("type")
        label = _short(s.get("path", "source"))

        if stype == "excel":
            for sheet_name, records in (s.get("sheets") or {}).items():
                ds = _records_to_dataset(records, f"{label} · {sheet_name}")
                if ds:
                    datasets.append(ds)

        elif stype == "csv":
            ds = _records_to_dataset(s.get("rows") or [], label)
            if ds:
                datasets.append(ds)

    return datasets


def _records_to_dataset(records: list[dict], source_ref: str, max_rows: int = 40) -> dict | None:
    if not records:
        return None
    columns = list(records[0].keys())
    rows = [[rec.get(c) for c in columns] for rec in records[:max_rows]]
    return {
        "source_ref": source_ref,
        "columns": columns,
        "rows": rows,
        "n_rows": len(records),
    }


def format_datasets_for_llm(datasets: list[dict[str, Any]], max_chars: int = 6000) -> str:
    """Compact, token-bounded rendering of the real datasets for a prompt."""
    if not datasets:
        return "(no structured data uploaded — chart figures may be illustrative)"

    parts: list[str] = []
    for i, ds in enumerate(datasets):
        header = f"DATASET #{i} — source_ref=\"{ds['source_ref']}\" ({ds['n_rows']} rows)"
        cols = " | ".join(str(c) for c in ds["columns"])
        sample = "\n".join(
            " | ".join("" if v is None else str(v) for v in row)
            for row in ds["rows"][:12]
        )
        parts.append(f"{header}\nCOLUMNS: {cols}\n{sample}")

    text = "\n\n".join(parts)
    return text[:max_chars]


def has_grounding(datasets: list[dict[str, Any]]) -> bool:
    return bool(datasets)
