"""
Unilever 2026 brand constants.
Colors derived from the GDT DECK.pptx template theme.
"""

# ── Template layout index → our deck layout names ───────────────────────────
# Master 0 layouts:
#   0:'1: Welcome'  1:'1_1: Welcome'  2:'2_1: Welcome'
#   3:'1: Cover'    4:'1_1: Cover'
#   5:'2: Section - Sky'   6:'2: Section - Earth'
#   7:'3: Title'    8:'3: Left'   9:'3: Right'
#   10:'3: Left - Image'   11:'3: Blank'
#   12:'3: Statement - Earth'   13:'3: Statement - Sky'
TEMPLATE_LAYOUT_MAP: dict[str, int] = {
    "cover":          3,   # 1: Cover          CENTER_TITLE(0), SUBTITLE(1), BODY(14)
    "agenda":         5,   # 2: Section - Sky  TITLE(0), BODY(1)
    "context":        7,   # 3: Title          TITLE(0), BODY(15), SLIDE_NUMBER(16)
    "findings":       7,   # 3: Title
    "chart":          7,   # 3: Title + programmatic chart below title
    "recommendation": 7,   # 3: Title
    "metrics":        7,   # 3: Title + metric boxes
    "diagram":        7,   # 3: Title + flow diagram shapes
    "roadmap":        7,   # 3: Title + phase boxes
    "achievement":    7,   # 3: Title + Overview / Went well / Could be better blocks
    "close":          6,   # 2: Section - Earth TITLE(0), BODY(1)
    # Split-column layouts — visual variety
    "left":           8,   # 3: Left   TITLE(0) left + OBJECT(13) left + free right
    "right":          9,   # 3: Right  TITLE(0) right + OBJECT(13) right + free left
}

# For the orchestrator / brand gate
LAYOUT_MAP = TEMPLATE_LAYOUT_MAP  # re-exported alias used by orchestrator

ALLOWED_LAYOUTS: frozenset[str] = frozenset(TEMPLATE_LAYOUT_MAP.keys())

# Locked section order for orchestrator prompt
STRUCTURE_LOCK: list[str] = [
    "Cover",
    "Agenda",
    "Context & Goals",
    "Findings & Data",
    "Recommendation",
    "Next Steps & Close",
]

# ── Brand colours (from theme + Unilever identity) ───────────────────────────
BRAND: dict[str, str] = {
    # Primary palette (template theme)
    "primary":   "#0066CC",   # dk1 / Unilever blue
    "dark":      "#133061",   # accent1 / dark navy
    "purple":    "#8651DF",   # accent2
    "pink":      "#E13491",   # accent3
    "teal":      "#008090",   # accent4
    "green":     "#2B911C",   # accent5
    "orange":    "#DA5700",   # accent6
    "white":     "#FFFFFF",   # lt1
    "light":     "#F6F7F0",   # lt2 (very light grey)
    # Derived / utility
    "secondary": "#1A50D6",   # mid blue
    "surface":   "#EEF2F8",   # card background
    "border":    "#C8D4E8",   # subtle border
    "muted":     "#7A8AA0",   # secondary text
    # Typography
    "font_headline": "Century Gothic",
    "font_body":     "Century Gothic",
    "font_mono":     "Courier New",
}

# Backwards-compat alias
BRAND_COLORS: dict[str, str] = BRAND
