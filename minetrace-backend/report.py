"""Printable evidence report for one route (open in browser, save as PDF)."""

from datetime import datetime, timezone
from html import escape

from config import RULES, THRESHOLDS

SEVERITY_LABEL = {"risk": "Risk", "caution": "Caution"}
LEVEL_LABEL = {
    "risk": "Risk flagged",
    "caution": "Caution flagged",
    "clear": "No flags raised",
    "limited": "Not enough data to assess",
    "minor": "Too small to assess",
}
STATUS_LABEL = {"flagged": "Flagged", "passed": "Passed", "skipped": "Could not run"}


def _rows(items):
    return "".join(
        f"<tr><th>{escape(str(i['label']))}</th><td>{escape(str(i['value']))}</td></tr>" for i in items
    )


def build_report(detail, narrative):
    route = detail["route"]
    assessment = detail["assessment"]
    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    title = f"{route['exporter_name']} to {route['importer_name']}, {detail['mineral']['label']} {route['year']}"

    flags_html = "".join(
        f"""
        <section class="flag {escape(f['severity'])}">
          <h3><span class="chip">{escape(SEVERITY_LABEL[f['severity']])}</span>
              {escape(f['rule'])} {escape(f['name'])}: {escape(f['title'])}</h3>
          <p>{escape(f['explanation'])}</p>
          <table>{_rows(f['evidence'])}</table>
          <p class="small">Threshold: {escape(f['threshold'])}</p>
        </section>"""
        for f in assessment["flags"]
    ) or "<p>None of the checks that could run raised a flag.</p>"

    checks_html = "".join(
        f"<tr><th>{escape(c['rule'])} {escape(c['name'])}</th>"
        f"<td>{escape(STATUS_LABEL[c['status']])}</td><td>{escape(c['note'])}</td></tr>"
        for c in assessment["checks"]
    )

    products_html = "".join(
        "<tr>"
        f"<th>HS {escape(p['hs_code'])}<br><span class='small'>{escape(p['label'])}</span></th>"
        f"<td>{_money(p['exporter_reported_usd'])}</td>"
        f"<td>{_money(p['importer_reported_usd'])}</td>"
        f"<td>{_weight(p['net_weight_kg'])}</td>"
        "</tr>"
        for p in detail["products"]
    )

    history_html = "".join(
        f"<tr><th>{h['year']}</th><td>{_money(h['value_usd'])}</td><td>{escape(h['basis'])}</td></tr>"
        for h in assessment["history"]
    )

    notes_html = "".join(f"<li>{escape(n)}</li>" for n in assessment["notes"] + detail["limitations"])

    rules_html = "".join(
        f"<li><strong>{k} {escape(v['name'])}.</strong> {escape(v['summary'])}</li>" for k, v in RULES.items()
    )

    sources = detail["sources"]
    sanctions_line = (
        f"OpenSanctions, version {escape(str(sources['sanctions_version']))}"
        if sources.get("sanctions_version") else "OpenSanctions data not loaded for this report"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MineTrace evidence report: {escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         color: #1d2422; max-width: 820px; margin: 40px auto; padding: 0 24px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; }}
  h2 {{ font-size: 18px; margin: 32px 0 10px; padding-top: 14px; border-top: 1px solid #d9dfdc; }}
  h3 {{ font-size: 15px; margin: 0 0 6px; }}
  .meta {{ color: #5b6662; margin: 0 0 18px; }}
  .verdict {{ display: inline-block; padding: 6px 14px; border-radius: 999px; font-weight: 600;
             background: #eef2ef; }}
  .verdict.risk {{ background: #f6e3de; color: #8a3b2a; }}
  .verdict.caution {{ background: #f6eedc; color: #7a5a1e; }}
  .verdict.clear {{ background: #e5efe6; color: #2f5c38; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ text-align: left; vertical-align: top; padding: 6px 10px 6px 0; border-bottom: 1px solid #eef1ef; }}
  th {{ font-weight: 600; width: 38%; }}
  .flag {{ padding: 14px 16px; border-radius: 12px; margin: 10px 0; background: #f7f8f7; }}
  .flag.risk {{ border-left: 4px solid #b9583f; }}
  .flag.caution {{ border-left: 4px solid #c39a45; }}
  .chip {{ font-size: 12px; padding: 2px 8px; border-radius: 999px; background: #fff; margin-right: 6px; }}
  .small {{ font-size: 13px; color: #5b6662; }}
  .narrative {{ background: #f3f6f4; padding: 14px 16px; border-radius: 12px; }}
  @media print {{ body {{ margin: 0; }} .flag {{ break-inside: avoid; }} }}
</style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p class="meta">MineTrace evidence report, generated {generated}</p>
  <p><span class="verdict {escape(assessment['level'])}">{escape(LEVEL_LABEL[assessment['level']])}</span>
     <span class="small">&nbsp; {assessment['checks_run']} of {assessment['checks_total']} checks could run</span></p>

  <h2>Summary</h2>
  <div class="narrative">
    <p>{escape(narrative['text'])}</p>
    <p class="small">{escape(narrative['note'])}</p>
  </div>

  <h2>Trade record</h2>
  <table>
    <tr><th>Route</th><td>{escape(route['exporter_name'])} (exporter) to {escape(route['importer_name'])} (importer)</td></tr>
    <tr><th>Year</th><td>{route['year']}</td></tr>
    <tr><th>Value</th><td>{escape(route['value_label'])}, based on the {escape(route['basis'])}'s report</td></tr>
    <tr><th>Net weight</th><td>{escape(route['weight_label'])}</td></tr>
  </table>
  <table>
    <tr><th>Product</th><th>Exporter reported</th><th>Importer reported</th><th>Weight used</th></tr>
    {products_html}
  </table>

  <h2>Flags</h2>
  {flags_html}

  <h2>Checks performed</h2>
  <table>{checks_html}</table>

  <h2>History of this route</h2>
  <table><tr><th>Year</th><th>Value</th><th>Reported by</th></tr>{history_html}</table>

  <h2>Limitations</h2>
  <ul>{notes_html}</ul>

  <h2>Method and sources</h2>
  <ul>{rules_html}</ul>
  <p class="small">Thresholds: mirror gap {THRESHOLDS['mirror_caution']:.0%}/{THRESHOLDS['mirror_risk']:.0%},
     volume spike {THRESHOLDS['spike_caution']:.0f}x/{THRESHOLDS['spike_risk']:.0f}x,
     concentration {THRESHOLDS['concentration_caution']:.0%}/{THRESHOLDS['concentration_risk']:.0%},
     price per kg {THRESHOLDS['unit_value_caution']:.0f}x/{THRESHOLDS['unit_value_risk']:.0f}x
     (caution/risk).</p>
  <p class="small">Trade data: {escape(sources['trade'])}. {sanctions_line}.
     This report supports supply-chain risk screening. It is not a legal or compliance determination.</p>
</body>
</html>"""


def _money(value):
    if value is None:
        return "not reported"
    return f"${value:,.0f}"


def _weight(value):
    if not value:
        return "n/a"
    return f"{value:,.0f} kg"
