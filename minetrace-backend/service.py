"""Plain functions behind every API endpoint.

Kept separate from FastAPI so they can be tested and reused (CLI, reports).
"""

import networkx as nx

import countries
from analytics import assess_route, assess_year, kg, load_context, network_summary, unit_value_medians, usd
from config import MINERALS, RULES, THRESHOLDS
from db import connect, get_meta


class NotFound(Exception):
    pass


def _mineral(mineral):
    if mineral not in MINERALS:
        raise NotFound(f"Unknown mineral '{mineral}'. Choose one of: {', '.join(MINERALS)}.")
    return MINERALS[mineral]


def _country(iso3):
    c = countries.by_iso3(iso3)
    if c:
        return c
    return {"iso3": iso3, "name": iso3, "short_name": iso3, "lat": None, "lon": None}


# --------------------------------------------------
# Minerals and years
# --------------------------------------------------

def list_minerals():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT mineral, year, COUNT(*) AS n FROM trade_flows GROUP BY mineral, year ORDER BY year"
        ).fetchall()
    finally:
        conn.close()

    years = {}
    for row in rows:
        years.setdefault(row["mineral"], []).append(row["year"])

    return [
        {
            "key": key,
            "label": info["label"],
            "hs_codes": [{"code": c, "label": l} for c, l in info["hs_codes"].items()],
            "years": years.get(key, []),
            "default_year": years.get(key, [None])[-1],
        }
        for key, info in MINERALS.items()
    ]


def _resolve_year(mineral, year):
    context = load_context(mineral)
    available = sorted(context["by_year"])
    if not available:
        return None, available
    if year is None or year not in context["by_year"]:
        return available[-1], available
    return year, available


# --------------------------------------------------
# Routes for the globe
# --------------------------------------------------

def list_routes(mineral, year=None):
    info = _mineral(mineral)
    year, years = _resolve_year(mineral, year)

    empty = {
        "mineral": {"key": mineral, "label": info["label"]},
        "year": year, "years": years, "routes": [], "countries": [],
        "summary": {"routes": 0, "risk": 0, "caution": 0, "clear": 0, "limited": 0, "minor": 0},
        "network": network_summary(nx.DiGraph()),
    }
    if year is None:
        return empty

    context = load_context(mineral)
    routes = context["by_year"][year]
    assessments = assess_year(mineral, year)

    out, used, skipped = [], {}, 0
    for key, route in routes.items():
        exporter, importer = _country(route["exporter"]), _country(route["importer"])
        if exporter["lat"] is None or importer["lat"] is None or route["value_usd"] <= 0:
            skipped += 1
            continue

        assessment = assessments[key]
        used[exporter["iso3"]] = exporter
        used[importer["iso3"]] = importer
        out.append({
            "from_iso": exporter["iso3"],
            "to_iso": importer["iso3"],
            "from_country": exporter["name"],
            "to_country": importer["name"],
            "from_short": exporter["short_name"],
            "to_short": importer["short_name"],
            "value_usd": route["value_usd"],
            "net_weight_kg": route["net_weight_kg"],
            "basis": route["basis"],
            "level": assessment["level"],
            "coverage": assessment["coverage"],
            "flag_count": len(assessment["flags"]),
            "flags": [{"rule": f["rule"], "severity": f["severity"], "title": f["title"]} for f in assessment["flags"]],
        })

    out.sort(key=lambda r: -r["value_usd"])
    summary = {"routes": len(out), "risk": 0, "caution": 0, "clear": 0, "limited": 0, "minor": 0,
               "not_mapped": skipped}
    for r in out:
        summary[r["level"]] += 1

    return {
        "mineral": {"key": mineral, "label": info["label"]},
        "year": year,
        "years": years,
        "routes": out,
        "countries": [
            {"iso3": c["iso3"], "name": c["name"], "short_name": c["short_name"], "lat": c["lat"], "lon": c["lon"]}
            for c in used.values()
        ],
        "summary": summary,
        "network": network_summary(context["graphs"][year]),
    }


# --------------------------------------------------
# One route in detail
# --------------------------------------------------

def route_detail(mineral, year, exporter, importer):
    info = _mineral(mineral)
    context = load_context(mineral)
    route = context["by_year"].get(year, {}).get((exporter, importer))
    if not route:
        raise NotFound(f"No {info['label'].lower()} trade recorded from {exporter} to {importer} in {year}.")

    assessment = assess_route(route, context, mineral, unit_value_medians(context["by_year"][year]))

    products = []
    for hs_code, p in sorted(route["products"].items()):
        products.append({
            "hs_code": hs_code,
            "label": info["hs_codes"].get(hs_code, f"HS {hs_code}"),
            "value_usd": p["value_usd"],
            "net_weight_kg": p["net_weight_kg"],
            "basis": p["basis"],
            "exporter_reported_usd": p["exporter"]["value_usd"] if p["exporter"] else None,
            "importer_reported_usd": p["importer"]["value_usd"] if p["importer"] else None,
        })

    e, i = _country(exporter), _country(importer)
    conn = connect()
    try:
        data_note = get_meta(conn, "comtrade_last_ingest")
        sanctions_note = get_meta(conn, "opensanctions_version")
    finally:
        conn.close()

    return {
        "mineral": {"key": mineral, "label": info["label"]},
        "route": {
            "year": year,
            "exporter": exporter,
            "importer": importer,
            "exporter_name": e["name"],
            "importer_name": i["name"],
            "value_usd": route["value_usd"],
            "value_label": usd(route["value_usd"]),
            "net_weight_kg": route["net_weight_kg"],
            "weight_label": kg(route["net_weight_kg"]),
            "basis": route["basis"],
        },
        "products": products,
        "assessment": assessment,
        "sources": {
            "trade": "UN Comtrade (country-reported annual trade, values in US dollars)",
            "trade_ingested": data_note,
            "sanctions": "OpenSanctions" if sanctions_note else None,
            "sanctions_version": sanctions_note,
        },
        "limitations": [
            "Country-level trade data shows which countries trade a mineral, not which mines or companies.",
            "A flag means the record deserves a closer look. It is not proof of wrongdoing.",
            "Recent years may be incomplete until all countries have reported.",
        ],
    }


# --------------------------------------------------
# Status and rules
# --------------------------------------------------

def health():
    conn = connect()
    try:
        flows = conn.execute("SELECT COUNT(*) FROM trade_flows").fetchone()[0]
        sanctions = conn.execute("SELECT COUNT(*) FROM sanctions_exposure").fetchone()[0]
        last = get_meta(conn, "comtrade_last_ingest")
    finally:
        conn.close()

    from narrative import ollama_available

    return {
        "status": "ok",
        "trade_records": flows,
        "sanctions_countries": sanctions,
        "last_trade_ingest": last,
        "ollama": ollama_available(),
    }


def rules():
    return {
        "rules": [{"rule": k, **v} for k, v in RULES.items()],
        "thresholds": THRESHOLDS,
    }
