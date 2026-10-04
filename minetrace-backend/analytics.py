"""MineTrace analytics: routes, trade network and explainable risk rules.

Pipeline for one mineral and year:

1. Load raw flows. Every country reports its own exports (X) and imports (M),
   so the same shipment can appear twice: once from each side.
2. Merge both sides into one route per exporter -> importer pair, keeping
   both values so they can be compared (the "mirror").
3. Build a NetworkX directed graph (countries = nodes, routes = edges).
4. Run five rules on every route. Each rule either flags, passes, or is
   skipped with a stated reason. Nothing is scored by a black box.
"""

import json
import statistics
from functools import lru_cache

import networkx as nx

import countries
from config import MINERALS, RULES, THRESHOLDS
from db import connect, db_signature

SEVERITY_ORDER = {"risk": 2, "caution": 1}


# --------------------------------------------------
# Loading and merging
# --------------------------------------------------

def _load_flows(conn, mineral):
    return conn.execute(
        """
        SELECT hs_code, year, reporter_iso, partner_iso, flow,
               value_usd, net_weight_kg, is_reported
        FROM trade_flows
        WHERE mineral = ?
        """,
        (mineral,),
    ).fetchall()


def build_routes(rows):
    """Merge exporter- and importer-reported records into routes.

    Returns {year: {(exporter, importer): route}}.

    For each product code the route keeps both reports. The headline value
    prefers the importer's report, because imports usually pass stricter
    customs control; if the importer did not report, the exporter's figure is
    used. The basis is always shown to the user.
    """
    years = {}

    for row in rows:
        if row["flow"] == "X":
            exporter, importer, side = row["reporter_iso"], row["partner_iso"], "exporter"
        else:
            exporter, importer, side = row["partner_iso"], row["reporter_iso"], "importer"

        if exporter == importer:
            continue

        route = years.setdefault(row["year"], {}).setdefault(
            (exporter, importer),
            {"exporter": exporter, "importer": importer, "year": row["year"], "products": {}},
        )
        product = route["products"].setdefault(row["hs_code"], {"exporter": None, "importer": None})
        product[side] = {
            "value_usd": row["value_usd"],
            "net_weight_kg": row["net_weight_kg"],
            "is_reported": bool(row["is_reported"]) if row["is_reported"] is not None else None,
        }

    for routes in years.values():
        for route in routes.values():
            _finalise_route(route)

    return years


def _finalise_route(route):
    total_value, total_weight = 0.0, 0.0
    bases = set()

    for product in route["products"].values():
        best = product["importer"] or product["exporter"]
        product["basis"] = "importer" if product["importer"] else "exporter"
        product["value_usd"] = best["value_usd"] or 0.0
        product["net_weight_kg"] = best["net_weight_kg"]
        bases.add(product["basis"])
        total_value += product["value_usd"]
        if best["net_weight_kg"]:
            total_weight += best["net_weight_kg"]

    route["value_usd"] = total_value
    route["net_weight_kg"] = total_weight or None
    route["basis"] = bases.pop() if len(bases) == 1 else "mixed"


def build_graph(routes):
    graph = nx.DiGraph()
    for (exporter, importer), route in routes.items():
        if route["value_usd"] > 0:
            graph.add_edge(exporter, importer, weight=route["value_usd"])
    return graph


# --------------------------------------------------
# Year context (shared by every route in a year)
# --------------------------------------------------

@lru_cache(maxsize=32)
def _context_cached(mineral, signature):
    conn = connect()
    try:
        rows = _load_flows(conn, mineral)
        sanctions = {
            row["iso3"]: {
                "mining_linked": row["mining_linked_entities"],
                "total": row["sanctioned_entities"],
                "samples": json.loads(row["sample_entities"] or "[]"),
            }
            for row in conn.execute("SELECT * FROM sanctions_exposure")
        }
    finally:
        conn.close()

    by_year = build_routes(rows)
    graphs = {year: build_graph(routes) for year, routes in by_year.items()}
    return {"by_year": by_year, "graphs": graphs, "sanctions": sanctions}


def load_context(mineral):
    return _context_cached(mineral, db_signature())


def unit_value_medians(routes):
    """Median USD per kg for each product code across all routes in a year."""
    samples = {}
    for route in routes.values():
        for hs_code, product in route["products"].items():
            value, weight = product["value_usd"], product["net_weight_kg"]
            if weight and weight > 0 and value >= THRESHOLDS["unit_value_min_value_usd"]:
                samples.setdefault(hs_code, []).append(value / weight)

    return {
        hs: {"median": statistics.median(values), "routes": len(values)}
        for hs, values in samples.items()
        if len(values) >= THRESHOLDS["unit_value_min_routes"]
    }


# --------------------------------------------------
# Formatting helpers (used in evidence shown to users)
# --------------------------------------------------

def usd(value):
    if value is None:
        return "n/a"
    if value >= 1e9:
        return f"${value / 1e9:,.2f} billion"
    if value >= 1e6:
        return f"${value / 1e6:,.2f} million"
    return f"${value:,.0f}"


def kg(value):
    if not value:
        return "n/a"
    if value >= 1e6:
        return f"{value / 1e3:,.0f} t"
    return f"{value:,.0f} kg"


def pct(value):
    return f"{value * 100:.0f}%"


def _hs_label(mineral, hs_code):
    return MINERALS.get(mineral, {}).get("hs_codes", {}).get(hs_code, f"HS {hs_code}")


def _flag(rule, severity, title, explanation, evidence, threshold):
    return {
        "rule": rule,
        "name": RULES[rule]["name"],
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "evidence": evidence,
        "threshold": threshold,
    }


def _check(rule, status, note):
    return {"rule": rule, "name": RULES[rule]["name"], "status": status, "note": note}


# --------------------------------------------------
# Rules
# --------------------------------------------------

def rule_mirror_gap(route, mineral):
    """R1: compare what the exporter and the importer each reported."""
    t = THRESHOLDS
    flags, compared, small, one_sided = [], 0, 0, 0

    for hs_code, product in route["products"].items():
        exp, imp = product["exporter"], product["importer"]
        if not exp or not imp:
            one_sided += 1
            continue

        x, m = exp["value_usd"] or 0, imp["value_usd"] or 0
        if min(x, m) < t["mirror_min_value_usd"]:
            small += 1
            continue

        compared += 1
        gap = abs(m - x) / max(m, x)
        if gap < t["mirror_caution"]:
            continue

        severity = "risk" if gap >= t["mirror_risk"] else "caution"
        higher = "importer" if m > x else "exporter"
        flags.append(_flag(
            "R1", severity,
            f"Reports differ by {pct(gap)}",
            (f"For {_hs_label(mineral, hs_code).lower()}, the {higher} reports a higher value. "
             f"Importers normally report 5–10% more because their figure includes freight and "
             f"insurance, so a gap of {pct(gap)} is worth checking."),
            [
                {"label": f"Exporter reported ({countries.name(route['exporter'])})", "value": usd(x)},
                {"label": f"Importer reported ({countries.name(route['importer'])})", "value": usd(m)},
                {"label": "Gap", "value": pct(gap)},
                {"label": "Product", "value": f"HS {hs_code}"},
            ],
            f"Caution from {pct(t['mirror_caution'])}, risk from {pct(t['mirror_risk'])}",
        ))

    if flags:
        check = _check("R1", "flagged", f"Compared {compared} product report pair(s).")
    elif compared:
        check = _check("R1", "passed", f"Both sides agree within {pct(t['mirror_caution'])}.")
    elif small:
        check = _check("R1", "skipped", "Both sides reported, but values are too small to compare reliably.")
    else:
        check = _check("R1", "skipped", "Only one country reported this flow, so there is nothing to compare.")

    return flags, check


def rule_volume_spike(route, history):
    """R2: selected year against the median of earlier years."""
    t = THRESHOLDS
    earlier = [h for h in history if h["year"] < route["year"] and h["value_usd"] > 0]

    if len(earlier) < t["spike_min_history_years"]:
        return [], _check(
            "R2", "skipped",
            f"Needs at least {t['spike_min_history_years']} earlier years of data; "
            f"{len(earlier)} available.",
        )

    current = route["value_usd"]
    baseline = statistics.median(h["value_usd"] for h in earlier)

    if current < t["spike_min_value_usd"] or baseline <= 0:
        return [], _check("R2", "passed", "Value is too small for a meaningful spike test.")

    ratio = current / baseline
    if ratio < t["spike_caution"]:
        return [], _check("R2", "passed", f"{route['year']} value is {ratio:.1f}x the earlier median.")

    severity = "risk" if ratio >= t["spike_risk"] else "caution"
    years_used = ", ".join(str(h["year"]) for h in earlier)
    flag = _flag(
        "R2", severity,
        f"Value jumped {ratio:.1f}x",
        (f"In {route['year']} this route carried {usd(current)}, against a median of "
         f"{usd(baseline)} in earlier years. Sudden jumps can signal new sourcing or re-routing."),
        [
            {"label": f"{route['year']} value", "value": usd(current)},
            {"label": "Earlier median", "value": usd(baseline)},
            {"label": "Years compared", "value": years_used},
            {"label": "Change", "value": f"{ratio:.1f}x"},
        ],
        f"Caution from {t['spike_caution']:.0f}x, risk from {t['spike_risk']:.0f}x",
    )
    return [flag], _check("R2", "flagged", f"Compared with {len(earlier)} earlier year(s).")


def rule_concentration(route, graph):
    """R3: how much of the importer's supply comes through this one route (NetworkX)."""
    t = THRESHOLDS
    importer = route["importer"]
    total = graph.in_degree(importer, weight="weight") if importer in graph else 0

    if total < t["concentration_min_total_usd"]:
        return [], _check("R3", "skipped", "The importer's total recorded imports are too small to judge dependence.")

    share = route["value_usd"] / total
    suppliers = graph.in_degree(importer)

    if share < t["concentration_caution"]:
        return [], _check("R3", "passed", f"This route is {pct(share)} of the importer's supply.")

    severity = "risk" if share >= t["concentration_risk"] else "caution"
    flag = _flag(
        "R3", severity,
        f"{pct(share)} of supply from one route",
        (f"{countries.name(importer)} gets {pct(share)} of its recorded imports of this mineral from "
         f"{countries.name(route['exporter'])}. Heavy dependence on one route means a disruption "
         f"there hits the whole supply."),
        [
            {"label": "This route", "value": usd(route["value_usd"])},
            {"label": f"All imports into {countries.name(importer)}", "value": usd(total)},
            {"label": "Share", "value": pct(share)},
            {"label": "Supplier countries", "value": str(suppliers)},
        ],
        f"Caution from {pct(t['concentration_caution'])}, risk from {pct(t['concentration_risk'])}",
    )
    return [flag], _check("R3", "flagged", "Measured on the trade network graph.")


def rule_unit_value(route, medians, mineral):
    """R4: declared price per kg far from the typical price for the product."""
    t = THRESHOLDS
    flags, tested = [], 0

    for hs_code, product in route["products"].items():
        weight, value = product["net_weight_kg"], product["value_usd"]
        reference = medians.get(hs_code)
        if not reference or not weight or weight <= 0 or value < t["unit_value_min_value_usd"]:
            continue

        tested += 1
        unit = value / weight
        ratio = unit / reference["median"]
        deviation = max(ratio, 1 / ratio) if ratio > 0 else float("inf")
        if deviation < t["unit_value_caution"]:
            continue

        severity = "risk" if deviation >= t["unit_value_risk"] else "caution"
        direction = "above" if ratio > 1 else "below"
        flags.append(_flag(
            "R4", severity,
            f"Price {deviation:.0f}x {direction} typical",
            (f"The declared value of {_hs_label(mineral, hs_code).lower()} on this route works out at "
             f"${unit:,.2f} per kg, {deviation:.0f}x {direction} the median of ${reference['median']:,.2f} "
             f"across {reference['routes']} routes. This can point to misclassified goods, "
             f"mis-declared quantities or a very different grade."),
            [
                {"label": "This route", "value": f"${unit:,.2f} per kg"},
                {"label": "Typical (median)", "value": f"${reference['median']:,.2f} per kg"},
                {"label": "Routes compared", "value": str(reference["routes"])},
                {"label": "Product", "value": f"HS {hs_code}"},
            ],
            f"Caution from {t['unit_value_caution']:.0f}x, risk from {t['unit_value_risk']:.0f}x off the median",
        ))

    if flags:
        return flags, _check("R4", "flagged", f"Tested {tested} product price(s).")
    if tested:
        return [], _check("R4", "passed", "Price per kg is within the normal range.")
    return [], _check("R4", "skipped", "Not enough weight data or comparable routes to judge price per kg.")


def _entities(count):
    return f"{count} sanctioned mining {'entity' if count == 1 else 'entities'}"


def rule_jurisdiction(route, sanctions):
    """R5: sanctioned mining/metals entities linked to the exporting country (OpenSanctions)."""
    t = THRESHOLDS
    if not sanctions:
        return [], _check("R5", "skipped", "Sanctions data not loaded yet. Run ingest_opensanctions.py.")

    iso3 = route["exporter"]
    info = sanctions.get(iso3)
    count = info["mining_linked"] if info else 0

    if count < t["sanctions_caution"]:
        note = (f"{countries.name(iso3)} has {_entities(count)} listed, "
                f"below the threshold of {t['sanctions_caution']}.")
        return [], _check("R5", "passed", note)

    severity = "risk" if count >= t["sanctions_risk"] else "caution"
    samples = ", ".join(s["name"] for s in info["samples"][:3]) or "n/a"
    flag = _flag(
        "R5", severity,
        f"{_entities(count)} in {countries.name(iso3)}",
        (f"OpenSanctions lists {_entities(count)} linked to {countries.name(iso3)}, where this mineral "
         f"comes from on this route. This does not mean this trade involves them; it means buyers "
         f"should check who they are dealing with."),
        [
            {"label": "Exporting country", "value": countries.name(iso3)},
            {"label": "Mining-linked sanctioned entities", "value": str(count)},
            {"label": "All sanctioned entities", "value": str(info["total"])},
            {"label": "Examples", "value": samples},
        ],
        f"Caution from {t['sanctions_caution']}, risk from {t['sanctions_risk']} entities",
    )
    return [flag], _check("R5", "flagged", "Matched against OpenSanctions.")


# --------------------------------------------------
# Assessment
# --------------------------------------------------

def route_history(context, exporter, importer):
    history = []
    for year in sorted(context["by_year"]):
        route = context["by_year"][year].get((exporter, importer))
        if route:
            history.append({"year": year, "value_usd": route["value_usd"], "basis": route["basis"]})
    return history


def _small_route(route, history):
    floor = THRESHOLDS["min_route_value_usd"]
    note = f"Route value is below {usd(floor)}, too small to assess reliably."
    return {
        "level": "minor",
        "coverage": "limited",
        "checks_run": 0,
        "checks_total": len(RULES),
        "flags": [],
        "checks": [_check(rule, "skipped", note) for rule in RULES],
        "notes": [note],
        "history": history,
    }


def assess_route(route, context, mineral, medians=None):
    year = route["year"]
    if route["value_usd"] < THRESHOLDS["min_route_value_usd"]:
        return _small_route(route, route_history(context, route["exporter"], route["importer"]))

    graph = context["graphs"][year]
    if medians is None:
        medians = unit_value_medians(context["by_year"][year])

    history = route_history(context, route["exporter"], route["importer"])

    flags, checks = [], []
    for result in (
        rule_mirror_gap(route, mineral),
        rule_volume_spike(route, history),
        rule_concentration(route, graph),
        rule_unit_value(route, medians, mineral),
        rule_jurisdiction(route, context["sanctions"]),
    ):
        flags.extend(result[0])
        checks.append(result[1])

    flags.sort(key=lambda f: -SEVERITY_ORDER[f["severity"]])
    ran = sum(1 for c in checks if c["status"] != "skipped")

    if any(f["severity"] == "risk" for f in flags):
        level = "risk"
    elif flags:
        level = "caution"
    elif ran >= 2:
        level = "clear"
    else:
        level = "limited"

    if ran >= 4:
        coverage = "good"
    elif ran >= 2:
        coverage = "partial"
    else:
        coverage = "limited"

    notes = []
    for hs_code, product in route["products"].items():
        for side in ("exporter", "importer"):
            if product[side] and product[side]["is_reported"] is False:
                notes.append(f"The {side}'s HS {hs_code} figure is a UN estimate, not a country report.")

    return {
        "level": level,
        "coverage": coverage,
        "checks_run": ran,
        "checks_total": len(checks),
        "flags": flags,
        "checks": checks,
        "notes": notes,
        "history": history,
    }


@lru_cache(maxsize=64)
def _assess_year_cached(mineral, year, signature):
    context = load_context(mineral)
    routes = context["by_year"].get(year, {})
    medians = unit_value_medians(routes)
    return {key: assess_route(route, context, mineral, medians) for key, route in routes.items()}


def assess_year(mineral, year):
    return _assess_year_cached(mineral, year, db_signature())


# --------------------------------------------------
# Network insights (NetworkX)
# --------------------------------------------------

def network_summary(graph):
    total = sum(d["weight"] for _, _, d in graph.edges(data=True))
    if not total:
        return {"total_value_usd": 0, "countries": 0, "routes": 0,
                "top_exporters": [], "top_importers": [], "hubs": [], "exporter_hhi": None}

    def ranked(strengths):
        items = sorted(((n, v) for n, v in strengths if v > 0), key=lambda x: -x[1])
        return [
            {"iso3": n, "name": countries.name(n), "value_usd": v, "share": v / total}
            for n, v in items
        ]

    exporters = ranked(graph.out_degree(weight="weight"))
    importers = ranked(graph.in_degree(weight="weight"))

    # Herfindahl-Hirschman Index of exporter shares (0-10,000).
    hhi = round(sum((e["share"] * 100) ** 2 for e in exporters))
    if hhi >= 2500:
        hhi_label = "highly concentrated"
    elif hhi >= 1500:
        hhi_label = "moderately concentrated"
    else:
        hhi_label = "diversified"

    # Hubs: countries that both import and re-export, ranked by how central
    # they are to the network (betweenness centrality).
    betweenness = nx.betweenness_centrality(graph) if graph.number_of_nodes() > 2 else {}
    hubs = []
    for node in graph.nodes:
        inflow = graph.in_degree(node, weight="weight")
        outflow = graph.out_degree(node, weight="weight")
        if inflow > 0 and outflow > 0:
            hubs.append({
                "iso3": node,
                "name": countries.name(node),
                "imports_usd": inflow,
                "exports_usd": outflow,
                "centrality": round(betweenness.get(node, 0), 3),
            })
    hubs.sort(key=lambda h: (-h["centrality"], -min(h["imports_usd"], h["exports_usd"])))

    return {
        "total_value_usd": total,
        "countries": graph.number_of_nodes(),
        "routes": graph.number_of_edges(),
        "top_exporters": exporters[:5],
        "top_importers": importers[:5],
        "exporter_hhi": hhi,
        "exporter_hhi_label": hhi_label,
        "hubs": hubs[:4],
    }
