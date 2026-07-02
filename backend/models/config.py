from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_cloud_project: str = "my-first-project-org"
    google_cloud_location: str = "us-east5"
    google_application_credentials: str = ""
    brand_id: str = "unilever-2026"

    # ── Model registry (single source of truth) ─────────────────────────────
    # Every agent reads its model from here so config never drifts from code.
    # "flash" = quality/reasoning tier, "flash-lite" = cheap/fast tier.
    model_intent: str = "gemini-2.5-flash-lite"   # 3.2 intent understanding
    model_analysis: str = "gemini-2.5-flash"      # 3.3 grounding / insight extraction
    model_orchestrator: str = "gemini-2.5-flash"  # 3.4 planner
    model_data_viz: str = "gemini-2.5-flash"      # 3.5 chart data selection
    model_diagram: str = "gemini-2.5-flash-lite"  # 3.5 diagram nodes
    model_layout: str = "gemini-2.5-flash-lite"   # 3.5 copy refinement
    model_notes: str = "gemini-2.5-flash-lite"    # 3.5 speaker notes
    model_qa: str = "gemini-2.5-flash"            # 3.8 narrative QA
    model_critic: str = "gemini-2.5-flash"        # 3.8 rubric critic loop
    model_requirements: str = "gemini-2.5-flash"  # 3.8 requirements check

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = [
        "http://localhost:8000", "http://127.0.0.1:8000",   # backend-served frontend
        "http://localhost:3000", "http://127.0.0.1:3000",   # common dev port
        "http://localhost:5500", "http://127.0.0.1:5500",   # VS Code Live Server
    ]

    upload_dir: str = "./uploads"
    max_upload_mb: int = 25

    # ── Governance (Copilot layer 3.8) ──────────────────────────────────────
    persist_specs: bool = True    # write DeckSpec + audit sidecar per job
    critic_max_passes: int = 2    # bounded critique→regenerate loop
    quality_gate: float = 6.0     # min acceptable rubric score before warning
