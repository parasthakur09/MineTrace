"""Load sanctions exposure per country from OpenSanctions.

For each country we count:
  * all sanctioned entities linked to it, and
  * sanctioned companies/organisations whose names match mining or metals terms.

These counts feed rule R5 (jurisdiction exposure). The keyword match is a
transparent heuristic and is described as such in the app.

Licence: OpenSanctions data is free for non-commercial use (CC BY-NC 4.0).
Commercial users need a licence from OpenSanctions. See README.

Examples
  python ingest_opensanctions.py                  # download latest and load
  python ingest_opensanctions.py --file targets.simple.csv   # load a file you downloaded
"""

import argparse
import csv
import json
import re
import sys
from datetime import date

import requests

import countries
from config import DATA_DIR
from db import init_db, session, set_meta

URL = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"
LOCAL_FILE = DATA_DIR / "opensanctions_targets.simple.csv"

LEGAL_ENTITY_SCHEMAS = {"company", "organization", "legalentity", "publicbody"}

MINING_TERMS = re.compile(
    r"\b(mining|mine|mines|minerals?|metals?|metallurg\w*|smelt\w*|refiner(y|ies)|"
    r"ores|cobalt|lithium|nickel|copper|graphite|tantalum|tungsten|tin|gold|coltan|"
    r"rare earths?|alumin(i)?um)\b",
    re.IGNORECASE,
)


def download(path):
    print(f"Downloading {URL}")
    with requests.get(URL, stream=True, timeout=120) as response:
        response.raise_for_status()
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return response.headers.get("Last-Modified") or date.today().isoformat()


def load(path):
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    totals, mining, samples = {}, {}, {}

    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = {name.lower(): name for name in reader.fieldnames or []}
        required = ("schema", "name", "countries")
        missing = [r for r in required if r not in fields]
        if missing:
            raise SystemExit(f"Unexpected file format, missing columns: {', '.join(missing)}")

        for row in reader:
            iso2_list = [c.strip() for c in (row[fields["countries"]] or "").split(";") if c.strip()]
            iso3_list = {c["iso3"] for c in map(countries.by_iso2, iso2_list) if c}
            if not iso3_list:
                continue

            schema = (row[fields["schema"]] or "").lower()
            name = row[fields["name"]] or ""
            aliases = row[fields["aliases"]] if "aliases" in fields else ""
            is_mining = schema in LEGAL_ENTITY_SCHEMAS and bool(MINING_TERMS.search(f"{name} {aliases}"))

            for iso3 in iso3_list:
                totals[iso3] = totals.get(iso3, 0) + 1
                if is_mining:
                    mining[iso3] = mining.get(iso3, 0) + 1
                    bucket = samples.setdefault(iso3, [])
                    if len(bucket) < 5:
                        bucket.append({"id": row.get(fields.get("id", "id"), ""), "name": name})

    return totals, mining, samples


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="use an already downloaded targets.simple.csv")
    args = parser.parse_args()

    init_db()

    if args.file:
        path, version = args.file, f"local file, loaded {date.today().isoformat()}"
    else:
        DATA_DIR.mkdir(exist_ok=True)
        path = LOCAL_FILE
        version = download(path)

    totals, mining, samples = load(path)

    with session() as conn:
        conn.execute("DELETE FROM sanctions_exposure")
        for iso3, total in totals.items():
            conn.execute(
                "INSERT INTO sanctions_exposure (iso3, sanctioned_entities, mining_linked_entities, sample_entities) "
                "VALUES (?, ?, ?, ?)",
                (iso3, total, mining.get(iso3, 0), json.dumps(samples.get(iso3, []), ensure_ascii=False)),
            )
        set_meta(conn, "opensanctions_version", version)

    top = sorted(mining.items(), key=lambda kv: -kv[1])[:8]
    print(f"Loaded {len(totals)} countries. Most mining-linked sanctioned entities:")
    for iso3, count in top:
        print(f"  {countries.name(iso3)}: {count}")


if __name__ == "__main__":
    main()
