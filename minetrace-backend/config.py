"""Central configuration for MineTrace.

Everything a judge might ask about ("why that threshold?") lives here,
so the rules stay explainable and easy to tune.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Absolute path, so the API finds the database no matter where it is started from.
DB_PATH = Path(os.environ.get("MINETRACE_DB", BASE_DIR / "minetrace.db"))
COUNTRIES_CSV = DATA_DIR / "countries.csv"

# --------------------------------------------------
# Minerals and the HS codes that carry them
# --------------------------------------------------
# A mineral moves through trade under several product codes (ore, intermediate,
# refined). Tracking only the ore code misses most of the volume: for example,
# most cobalt from the DR Congo is shipped as cobalt hydroxide (HS 2822).

MINERALS = {
    "cobalt": {
        "label": "Cobalt",
        "hs_codes": {
            "260500": "Cobalt ores and concentrates",
            "282200": "Cobalt oxides and hydroxides",
            "810520": "Cobalt mattes, intermediates, unwrought cobalt and powders",
        },
    },
    "lithium": {
        "label": "Lithium",
        "hs_codes": {
            "282520": "Lithium oxide and hydroxide",
            "283691": "Lithium carbonates",
        },
    },
    "nickel": {
        "label": "Nickel",
        "hs_codes": {
            "260400": "Nickel ores and concentrates",
            "750110": "Nickel mattes",
        },
    },
    "graphite": {
        "label": "Graphite",
        "hs_codes": {
            "250410": "Natural graphite in powder or flakes",
        },
    },
}


def mineral_for_hs(hs_code):
    for key, mineral in MINERALS.items():
        if hs_code in mineral["hs_codes"]:
            return key
    return None


# --------------------------------------------------
# Rule thresholds (all explainable, all adjustable)
# --------------------------------------------------

THRESHOLDS = {
    # Routes smaller than this are shown but not assessed: tiny flows are noisy,
    # and screening them would bury the routes that matter.
    "min_route_value_usd": 100_000,

    # R1 Mirror gap: exporter-reported vs importer-reported value of the same flow.
    # Importers report CIF (incl. freight/insurance), exporters FOB, so a gap of
    # roughly 5-10% is normal. Larger gaps are worth a closer look.
    "mirror_caution": 0.25,
    "mirror_risk": 0.50,
    "mirror_min_value_usd": 10_000,

    # R2 Volume spike: selected year vs median of earlier years.
    "spike_caution": 2.0,
    "spike_risk": 3.0,
    "spike_min_history_years": 2,
    "spike_min_value_usd": 50_000,

    # R3 Route concentration: share of the importer's total imports of this
    # mineral that come through this single route.
    "concentration_caution": 0.50,
    "concentration_risk": 0.80,
    "concentration_min_total_usd": 100_000,

    # R4 Unit value: price per kg compared with the median for the same product
    # code and year across all routes.
    "unit_value_caution": 4.0,   # 4x above or below median
    "unit_value_risk": 10.0,     # 10x above or below median
    "unit_value_min_routes": 6,
    "unit_value_min_value_usd": 10_000,

    # R5 Jurisdiction exposure: sanctioned entities whose names match
    # mining/metals keywords, linked to the EXPORTING country (the origin of
    # the mineral, which is what sourcing due diligence is about).
    "sanctions_caution": 10,
    "sanctions_risk": 50,
}

RULES = {
    "R1": {"name": "Mirror gap", "summary": "Exporter and importer report different values for the same flow."},
    "R2": {"name": "Volume spike", "summary": "Trade value jumped sharply compared with earlier years."},
    "R3": {"name": "Route concentration", "summary": "The importer depends heavily on this one route."},
    "R4": {"name": "Unusual price per kg", "summary": "Declared value per kg is far from the typical price for this product."},
    "R5": {"name": "Jurisdiction exposure", "summary": "Many sanctioned mining or metals entities are linked to the exporting country."},
}

# --------------------------------------------------
# Local LLM (Ollama)
# --------------------------------------------------

OLLAMA_URL = os.environ.get("MINETRACE_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("MINETRACE_OLLAMA_MODEL", "llama3.2")
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("MINETRACE_OLLAMA_TIMEOUT", "45"))

# --------------------------------------------------
# Frontend origins allowed to call the API
# --------------------------------------------------

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
