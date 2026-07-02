# Deck Agent — Unilever AI Presentation Generator

Turns a prompt (plus optional Excel/CSV/PDF/DOCX files) into a fully-designed,
on-brand PowerPoint deck. Built as a **multi-agent pipeline** on **Google Gemini
via Vertex AI**, rendered deterministically with **python-pptx**.

It implements the Copilot-assisted PPT reference architecture end-to-end:
understand intent → ground in real data → plan the storyline → generate slide
content with specialist agents → review against a quality rubric → enforce brand
governance → render. FastAPI backend + a zero-build HTML/JS frontend.

---

## Architecture at a glance

Every LLM stage runs on Gemini via Vertex AI. Models are configured in **one
place** — the model registry in `models/config.py` — so config never drifts from
code. Stage numbers map to the reference architecture doc §3.

```
01    Ingest & parse         deterministic — PDF/XLSX/CSV/DOCX/images        (3.1)
02a   Intent understanding   audience / tone / purpose / key topics          (3.2)
02    Analysis & grounding   insights over REAL structured tables            (3.3)
03    Orchestrator (planner) storyline + layout routing (intent-aware)       (3.4)
04    Specialist models      4 agents, run concurrently                      (3.5/3.6)
      ├── Data viz           selects real figures + cites source_ref
      ├── Diagram engine     flow / timeline / funnel node labels
      ├── Layout & copy      headline/body refinement
      └── Visual media       section-icon assignment (additive patch)
04.5  Narrative QA           story-coherence critic                          (3.8)
04.7  Speaker notes          per-slide presenter script                      (3.5)
05.3  Requirements check     deck vs. user prompt, gap patching              (3.8)
05.4  Deck validator         deterministic structural fix loop               (3.8)
05.5  Quality critic         rubric score 0-10 + bounded rewrite loop        (3.8)
05    Brand gate             hard lock — structure ORDER + layouts + count   (3.8)
06    Render                 python-pptx — charts, tables, notes, captions   (3.7)
--    Persist DeckSpec       {job_id}.spec.json → faithful preview + audit   (3.8)
```

### Grounding — why the deck uses *your* numbers

When you upload Excel/CSV, `agents/grounding.py` normalises every sheet into a
**cited dataset** (`source_ref = file · sheet`). The analysis and data-viz agents
**select** from these real figures instead of inventing them; grounded charts
render a `Source: …` caption and carry `grounded=true`. Figures are only invented
when **no** structured data is uploaded — and those are flagged `grounded=false`.

### Quality & governance

- **Rubric critic (05.5)** scores each deck 0-10 on storyline · density ·
  factuality · visual quality · exec-readiness, and rewrites the weakest slides
  in a bounded loop (`critic_max_passes`). The score surfaces in the UI and the
  persisted spec; `quality_gate` marks decks that fall short.
- **Brand gate (05)** is a hard lock: it enforces the locked section **order**,
  the allowed layout set, and a minimum slide count — raising `BrandViolationError`
  rather than rendering a non-compliant deck.
- **Audit trail** — the full `DeckSpec` (intent, per-slide copy, provenance,
  score) is persisted as `{job_id}.spec.json` for preview and review.
- **Resilient parsing** — `utils/jsonsafe.py` salvages truncated LLM JSON so a
  stage that hits the token limit still returns usable output instead of failing
  silently. Stage messages report *real* counts (e.g. `8/8 slides annotated`).

---

## Project layout

```
deck_agent/
├── frontend/
│   ├── landing.html          Marketing landing page
│   └── generator.html        Generator UI (prompt, upload, live SSE, preview, export)
└── backend/
    ├── main.py               FastAPI entry point (also serves the frontend)
    ├── requirements.txt
    ├── .env.example          Copy to .env — Vertex/GCP config (no Anthropic key)
    ├── api/routes/
    │   ├── generate.py       /api/upload · /api/generate (SSE) · /download · /preview
    │   └── health.py         /api/health
    ├── agents/
    │   ├── pipeline.py        Master pipeline — orchestrates every stage
    │   ├── ingest.py          01 · Parse PDF/XLSX/CSV/DOCX/images
    │   ├── grounding.py       Normalises uploads into cited datasets
    │   ├── intent.py          02a · Intent understanding
    │   ├── analysis.py        02 · Analysis over grounded data
    │   ├── orchestrator.py    03 · Planner (storyline + layout routing)
    │   ├── specialists/
    │   │   ├── data_viz.py     04 · Real chart/table data + provenance
    │   │   ├── diagram.py      04 · Diagram node labels
    │   │   ├── layout_copy.py  04 · Headline/body refinement
    │   │   └── visual_media.py 04 · Section icons
    │   ├── qa.py              04.5 · Narrative QA
    │   ├── speaker_notes.py   04.7 · Presenter script
    │   ├── requirements_check.py 05.3 · Deck-vs-prompt gap check
    │   ├── deck_validator.py  05.4 · Deterministic structural fixes
    │   ├── critic.py          05.5 · Rubric score + rewrite loop
    │   ├── brand_gate.py      05 · Hard brand/governance lock
    │   └── render.py          06 · python-pptx renderer
    ├── brand/
    │   └── unilever_2026.py   Single source of truth for brand rules
    ├── template/
    │   └── GDT DECK.pptx      Base template (master, theme, fonts)
    ├── utils/
    │   ├── vertex.py          Shared Vertex AI (google-genai) client
    │   └── jsonsafe.py        Tolerant JSON parser for truncated LLM output
    └── models/
        ├── schemas.py        Data contract (DeckSpec, SlideSpec, IntentSpec, …)
        └── config.py         Settings + model registry (reads .env)
```

---

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env (see Configuration below)
python main.py                     # → http://localhost:8000
```

This app uses **Google Vertex AI**, not the Anthropic API. Authenticate with a
GCP service account or Application Default Credentials — see Configuration.

The backend also serves the frontend at `/`, so opening `http://localhost:8000`
shows the landing page and `http://localhost:8000/generator.html` the generator.

### 2. Frontend (standalone, optional)

Serve `frontend/` with any static server (`python -m http.server`, VS Code Live
Server, …). The generator calls the backend at `http://localhost:8000/api/…`;
change `API_BASE` at the top of `generator.html` to point elsewhere.

---

## Configuration (`.env` / `models/config.py`)

| Setting | Purpose |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project id |
| `GOOGLE_CLOUD_LOCATION` | Vertex region (e.g. `global`, `us-east5`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the service-account JSON (or use ADC / Workload Identity) |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | Local file storage + upload cap |
| `CORS_ORIGINS` | Allowed browser origins |

**Model registry** (all Gemini via Vertex) lives in `config.py` — `model_intent`,
`model_analysis`, `model_orchestrator`, `model_data_viz`, `model_diagram`,
`model_layout`, `model_notes`, `model_qa`, `model_critic`, `model_requirements`.
Every agent reads its model from here — change tiers in one place.

**Governance knobs:** `persist_specs` (write the DeckSpec sidecar),
`critic_max_passes` (bounded rewrite loop), `quality_gate` (min acceptable score).

> **Secrets:** never commit `.env` or the GCP service-account JSON — both are in
> `.gitignore`. Rotate any key that has been shared, and prefer
> `GOOGLE_APPLICATION_CREDENTIALS` / Workload Identity over a key file in the repo.

---

## Generator UI

`generator.html` is a single full-width layout:

- **Composer** — prompt textarea, file attachments, deck-type selector, slide-count stepper, Generate.
- **Running** — live SSE step log, one row per pipeline stage.
- **Done** — badges (**Brand check passed** · **Quality X/10** · **Grounded in your
  data**), a slide-thumbnail grid with a green **DATA** chip on grounded slides,
  a **Preview** modal (headline, body, speaker notes, provenance), and **Export PPTX**.

Brand rules are enforced server-side only; they aren't shown as an editable panel.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/health` | Health check |
| POST | `/api/upload` | Multipart file upload → `{file_id}` |
| POST | `/api/generate` | SSE stream of pipeline events → download URL |
| GET  | `/api/download/{job_id}` | Download the rendered `.pptx` |
| GET  | `/api/preview/{job_id}` | Slide data from the persisted DeckSpec (title, quality, grounded, per-slide notes) |
| GET  | `/api/jobs/{job_id}` | Poll job status |

### SSE events

`/api/generate` streams `text/event-stream`:

```
event: stage
data: {"stage":"04.7 · Speaker notes","status":"done","message":"8/8 slides annotated","progress":74}

event: done
data: {"stage":"complete","status":"done","message":"/api/download/abc123","progress":100}
```

---

## Brand system (`brand/unilever_2026.py`)

Single source of truth, enforced server-side. Editing it propagates to every
rendered slide.

| Agent | Uses |
|-------|------|
| `brand_gate.py` | `STRUCTURE_LOCK`, `ALLOWED_LAYOUTS` |
| `orchestrator.py` | `STRUCTURE_LOCK`, `LAYOUT_MAP` |
| `render.py` | `BRAND` (colours + fonts), `TEMPLATE_LAYOUT_MAP` |

- **Palette:** `#0066CC` (primary) · `#133061` (navy) · `#8651DF` · `#E13491` ·
  `#008090` · `#2B911C` · `#DA5700`, on `#F6F7F0` / white — from the GDT DECK theme.
- **Fonts:** Century Gothic (headline + body), Courier New (mono).
- **Locked structure:** Cover → Agenda → Context & Goals → Findings & Data →
  Recommendation → Next Steps & Close (order enforced by the brand gate).
- **Allowed layouts:** cover, agenda, context, findings, chart, metrics, diagram,
  recommendation, roadmap, close, left, right.

---

## No credentials? (graceful degradation)

If Vertex is unreachable, the LLM stages fall back to deterministic mock data
(intent defaults, a mock analysis and mock deck plan, copy/QA/critic no-ops) and
the renderer still produces a real, on-brand `.pptx`. This lets you exercise the
full pipeline and rendering path locally without any API calls — grounded charts
just won't appear because there's no analysis to select real data with.
