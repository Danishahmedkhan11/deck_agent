"""
Stage 01 — Ingest & parse (deterministic).

Supports: PDF, XLSX, CSV, DOCX, plain text, images.
Returns a list of ParsedSource dicts consumed downstream.
"""
import asyncio
import io
import os
from pathlib import Path
from typing import Any


async def ingest_files(file_ids: list[str], upload_dir: str) -> list[dict[str, Any]]:
    tasks = [_parse_one(fid, upload_dir) for fid in file_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    parsed = []
    for r in results:
        if isinstance(r, Exception):
            print(f"[ingest] skipping file due to error: {r}")
        elif r:
            parsed.append(r)
    # if no files, return empty context — orchestrator will work from prompt alone
    return parsed


async def _parse_one(file_id: str, upload_dir: str) -> dict[str, Any] | None:
    # find file regardless of extension
    upload_path = Path(upload_dir)
    matches = list(upload_path.glob(f"{file_id}*"))
    if not matches:
        return None

    path = matches[0]
    ext = path.suffix.lower()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _parse_sync, path, ext)


def _parse_sync(path: Path, ext: str) -> dict[str, Any]:
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext in (".xlsx", ".xls"):
        return _parse_excel(path)
    if ext == ".csv":
        return _parse_csv(path)
    if ext in (".docx", ".doc"):
        return _parse_docx(path)
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return {"type": "image", "path": str(path), "text": ""}
    # fallback: read as plain text
    return {"type": "text", "path": str(path), "text": path.read_text(errors="replace")}


def _parse_pdf(path: Path) -> dict[str, Any]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        return {"type": "pdf", "path": str(path), "pages": pages, "text": "\n".join(pages)}
    except ImportError:
        return {"type": "pdf", "path": str(path), "text": "(PyMuPDF not installed)"}


def _parse_excel(path: Path) -> dict[str, Any]:
    try:
        import pandas as pd
        sheets = pd.read_excel(path, sheet_name=None)
        tables = {}
        combined_text = []
        for name, df in sheets.items():
            tables[name] = df.to_dict(orient="records")
            combined_text.append(f"Sheet: {name}\n{df.to_string(index=False)}")
        return {"type": "excel", "path": str(path), "sheets": tables, "text": "\n\n".join(combined_text)}
    except ImportError:
        return {"type": "excel", "path": str(path), "text": "(pandas not installed)"}


def _parse_csv(path: Path) -> dict[str, Any]:
    try:
        import pandas as pd
        df = pd.read_csv(path)
        return {"type": "csv", "path": str(path), "rows": df.to_dict(orient="records"), "text": df.to_string(index=False)}
    except ImportError:
        return {"type": "csv", "path": str(path), "text": path.read_text(errors="replace")}


def _parse_docx(path: Path) -> dict[str, Any]:
    try:
        from docx import Document
        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return {"type": "docx", "path": str(path), "text": text}
    except ImportError:
        return {"type": "docx", "path": str(path), "text": "(python-docx not installed)"}
