"""Shows exactly what UN Comtrade returns for a few test queries."""
import time
import requests

URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
ALL = "260500,282200,810520,282520,283691,260400,750110,250410"
FILTERS = {"partner2Code": 0, "customsCode": "C00", "motCode": 0}

TESTS = [
    ("Germany 2022, same as setup", {"reporterCode": 276, "period": 2022, "flowCode": "X,M", "cmdCode": ALL, **FILTERS}),
    ("Germany 2022, imports only, one code", {"reporterCode": 276, "period": 2022, "flowCode": "M", "cmdCode": "282200", **FILTERS}),
    ("Germany 2022, one code, no filters", {"reporterCode": 276, "period": 2022, "flowCode": "M", "cmdCode": "282200"}),
    ("France 2022, imports only, one code", {"reporterCode": 251, "period": 2022, "flowCode": "M", "cmdCode": "282200", **FILTERS}),
    ("Zambia 2022, same as setup", {"reporterCode": 894, "period": 2022, "flowCode": "X,M", "cmdCode": ALL, **FILTERS}),
    ("Zambia 2022, exports only, one code", {"reporterCode": 894, "period": 2022, "flowCode": "X", "cmdCode": "810520", **FILTERS}),
]

for name, params in TESTS:
    r = requests.get(URL, params=params, timeout=40)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    rows = body.get("data") or []
    print(f"\n=== {name}")
    print(f"HTTP {r.status_code} | rows: {len(rows)} | keys: {list(body.keys())}")
    for key in ("error", "message", "count", "statusCode", "raw"):
        if key in body:
            print(f"  {key}: {str(body[key])[:300]}")
    if rows:
        first = rows[0]
        print("  first row:", {k: first.get(k) for k in ("flowCode", "cmdCode", "partnerCode", "primaryValue")})
    time.sleep(6)