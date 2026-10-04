"""Download critical-mineral trade data from UN Comtrade into the local database.

Why both directions: every shipment can be reported twice, once as the
exporter's export and once as the importer's import. Having both is what makes
the mirror check (R1) possible, and it fills gaps when one country reports late.

Examples
  python ingest_comtrade.py                      # quick: key countries, all minerals, 2020-2024
  python ingest_comtrade.py --minerals cobalt    # one mineral
  python ingest_comtrade.py --years 2019-2024
  python ingest_comtrade.py --all                # every reporting country (slow, ~1h)
  python ingest_comtrade.py --reset              # forget progress and fetch again

Optional: set COMTRADE_API_KEY (free key from comtradeplus.un.org) for higher limits.
The script resumes where it stopped, so it is safe to interrupt and run again.
"""

import argparse
import os
import time
from datetime import date

import requests

import countries
from config import MINERALS, mineral_for_hs
from db import init_db, session, set_meta, upsert_flow

PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
KEYED_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
RECORD_CAP = 500          # the free preview endpoint returns at most 500 rows per call
REQUEST_DELAY = 2.0
MAX_RETRIES = 5
EMPTY_RETRIES = 2          # the free endpoint sometimes answers "OK" with no rows when busy
EMPTY_ATTEMPTS_LIMIT = 3   # after this many empty answers across runs, accept it as truly empty


class QuotaExceeded(Exception):
    """Comtrade's free allowance is used up; it resets after a while."""

# Producers, processors and big buyers across cobalt, lithium, nickel and graphite.
# Pulling their exports AND imports also captures countries that report late,
# through their partners' records.
KEY_COUNTRIES = [
    "COD", "ZMB", "ZAF", "MAR", "MDG", "MOZ", "TZA", "ZWE",       # Africa
    "CHN", "JPN", "KOR", "S19", "IND", "IDN", "PHL", "MYS", "VNM", "HKG",  # Asia
    "BEL", "FIN", "NOR", "DEU", "NLD", "FRA", "GBR", "ITA", "POL", "RUS", "TUR",  # Europe
    "USA", "CAN", "MEX", "BRA", "CHL", "ARG",                     # Americas
    "AUS", "NCL",                                                 # Oceania
]

# Comtrade's own reporter codes where they differ from UN M49.
COMTRADE_REPORTER_CODE = {"USA": 842, "FRA": 251, "IND": 699, "CHE": 757, "NOR": 579, "S19": 490}


def reporter_code(iso3):
    if iso3 in COMTRADE_REPORTER_CODE:
        return COMTRADE_REPORTER_CODE[iso3]
    return countries.m49_code(iso3)


def parse_years(text):
    if "-" in text:
        start, end = (int(x) for x in text.split("-"))
        return list(range(start, end + 1))
    return [int(x) for x in text.split(",")]


def fetch(params, api_key):
    url = KEYED_URL if api_key else PREVIEW_URL
    headers = {"Ocp-Apim-Subscription-Key": api_key} if api_key else {}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=40)
        except requests.RequestException as error:
            wait = 3 * (attempt + 1)
            print(f"    network error ({error.__class__.__name__}), retrying in {wait}s")
            time.sleep(wait)
            continue

        if response.status_code == 429:
            wait = min(60, 6 * (attempt + 1))
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        if response.status_code == 403 and "quota" in response.text.lower():
            raise QuotaExceeded()
        if response.status_code >= 500:
            wait = min(30, 4 * (attempt + 1))
            print(f"    server error {response.status_code}, waiting {wait}s")
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response.json().get("data") or []

    raise RuntimeError("Comtrade did not answer after several retries.")


def resolve_partner(row):
    code = row.get("partnerCode")
    if code in (0, None):           # 0 = World total
        return None
    country = countries.by_comtrade_code(code)
    if country:
        return country["iso3"]
    iso = (row.get("partnerISO") or "").upper()
    return iso if countries.by_iso3(iso) else None


def store_rows(conn, reporter_iso, rows):
    saved = unknown = 0
    for row in rows:
        # Note: "isAggregate" is NOT a world total. Countries that report finer than
        # 6-digit HS (e.g. Germany, France) have their 6-digit rows marked as
        # aggregated, so they must be kept. World totals are partner code 0,
        # which resolve_partner() already skips.
        if row.get("flowCode") not in ("X", "M"):
            continue  # skip re-exports/re-imports
        if row.get("partner2Code") not in (0, None) or row.get("motCode") not in (0, None):
            continue
        if row.get("customsCode") not in ("C00", None):
            continue

        hs_code = str(row.get("cmdCode") or "")
        mineral = mineral_for_hs(hs_code)
        partner_iso = resolve_partner(row)
        if not mineral or not partner_iso or partner_iso == reporter_iso:
            unknown += 1
            continue

        weight = row.get("netWgt")
        if not weight and row.get("qtyUnitCode") == 8:   # unit 8 = kilograms
            weight = row.get("qty")

        upsert_flow(
            conn,
            mineral=mineral,
            hs_code=hs_code,
            year=int(row.get("refYear") or row.get("period")),
            reporter_iso=reporter_iso,
            partner_iso=partner_iso,
            flow=row["flowCode"],
            value_usd=row.get("primaryValue"),
            net_weight_kg=weight or None,
            is_reported=1 if row.get("isReported") else 0,
        )
        saved += 1
    return saved, unknown


def ingest_one(conn, iso3, year, hs_codes, api_key):
    code = reporter_code(iso3)
    if code is None:
        raise RuntimeError(f"No Comtrade code known for {iso3}")

    base = {
        "reporterCode": code,
        "period": year,
        "flowCode": "X,M",
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
    }

    rows = fetch({**base, "cmdCode": ",".join(hs_codes)}, api_key)

    # An empty answer is often Comtrade being busy, not "no trade". Ask again.
    for attempt in range(EMPTY_RETRIES):
        if rows:
            break
        wait = 8 * (attempt + 1)
        print(f"    empty answer, asking again in {wait}s")
        time.sleep(wait)
        rows = fetch({**base, "cmdCode": ",".join(hs_codes)}, api_key)

    # If the free endpoint's row cap was hit, fetch one product code at a time.
    if len(rows) >= RECORD_CAP and len(hs_codes) > 1:
        rows = []
        for hs_code in hs_codes:
            time.sleep(REQUEST_DELAY)
            rows.extend(fetch({**base, "cmdCode": hs_code}, api_key))

    saved, unknown = store_rows(conn, iso3, rows)
    return len(rows), saved, unknown


def job_is_complete(state):
    """Finished jobs are skipped on the next run; empty answers are retried."""
    if not state:
        return False
    if state["status"] == "done":
        return (state["rows_saved"] or 0) > 0     # old runs marked empty answers as done
    if state["status"] == "no_relevant_rows":
        return True                                # Comtrade answered, nothing relevant
    # "nodata" came from an older version that wrongly dropped rows; retry those.
    if state["status"] == "empty":
        return int(state["message"] or 0) >= EMPTY_ATTEMPTS_LIMIT
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minerals", default=",".join(MINERALS), help="comma list, e.g. cobalt,lithium")
    parser.add_argument("--years", default="2020-2024", help="range 2020-2024 or list 2022,2023")
    parser.add_argument("--all", action="store_true", help="every reporting country, not just key ones")
    parser.add_argument("--reporters", help="comma list of ISO3 codes to fetch")
    parser.add_argument("--reset", action="store_true", help="ignore saved progress")
    args = parser.parse_args()

    minerals = [m.strip() for m in args.minerals.split(",") if m.strip()]
    for m in minerals:
        if m not in MINERALS:
            parser.error(f"Unknown mineral {m}. Choose from {', '.join(MINERALS)}.")

    hs_codes = [code for m in minerals for code in MINERALS[m]["hs_codes"]]
    years = parse_years(args.years)

    if args.reporters:
        reporters = [r.strip().upper() for r in args.reporters.split(",")]
    elif args.all:
        reporters = sorted({c["iso3"] for c in countries.all_countries()})
    else:
        reporters = KEY_COUNTRIES

    api_key = os.environ.get("COMTRADE_API_KEY")
    init_db()

    jobs = [(iso3, year) for iso3 in reporters for year in years]
    print("MineTrace | UN Comtrade ingestion")
    print(f"  minerals: {', '.join(minerals)}   HS codes: {', '.join(hs_codes)}")
    print(f"  years: {years[0]}-{years[-1]}   reporters: {len(reporters)}   requests: ~{len(jobs)}")
    print(f"  endpoint: {'keyed API' if api_key else 'free preview'}\n")

    tag = ",".join(hs_codes)
    total_saved = errors = empty_jobs = 0
    quota_hit = False

    with session() as conn:
        if args.reset:
            conn.execute("DELETE FROM ingestion_state WHERE job LIKE 'comtrade:%'")
            conn.commit()

        for index, (iso3, year) in enumerate(jobs, 1):
            job = f"comtrade:{iso3}:{year}:{tag}"
            state = conn.execute(
                "SELECT status, rows_saved, message FROM ingestion_state WHERE job = ?", (job,)
            ).fetchone()
            label = f"[{index}/{len(jobs)}] {countries.name(iso3)} {year}"

            if job_is_complete(state):
                print(f"{label}: already done")
                continue

            try:
                returned, saved, unknown = ingest_one(conn, iso3, year, hs_codes, api_key)

                if returned:
                    status, message = ("done" if saved else "no_relevant_rows"), None
                    note = f"{saved} records" + (f" ({unknown} skipped)" if unknown else "")
                else:
                    previous = int(state["message"] or 0) if state and state["status"] == "empty" else 0
                    status, message = "empty", str(previous + 1)
                    empty_jobs += 1
                    if previous + 1 >= EMPTY_ATTEMPTS_LIMIT:
                        note = "no data (confirmed after several tries)"
                    else:
                        note = "empty answer, will retry on the next run"

                conn.execute(
                    "INSERT OR REPLACE INTO ingestion_state (job, status, rows_saved, message, updated_at) "
                    "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (job, status, saved, message),
                )
                conn.commit()
                total_saved += saved
                print(f"{label}: {note}")
            except QuotaExceeded:
                print(f"{label}: Comtrade's free daily allowance is used up.")
                print("\nStopped early. Progress is saved. Run the same command again later")
                print("(usually after a few hours), and it continues from here.")
                print("Tip: a free API key from comtradedeveloper.un.org gives a much larger allowance.")
                quota_hit = True
                break
            except Exception as error:  # keep going; the job is retried next run
                errors += 1
                conn.execute(
                    "INSERT OR REPLACE INTO ingestion_state (job, status, message, updated_at) "
                    "VALUES (?, 'error', ?, CURRENT_TIMESTAMP)",
                    (job, str(error)[:300]),
                )
                conn.commit()
                print(f"{label}: ERROR {error}")

            time.sleep(REQUEST_DELAY)

        set_meta(conn, "comtrade_last_ingest", f"{date.today().isoformat()} ({years[0]}-{years[-1]})")

    if quota_hit:
        print(f"Saved {total_saved} new records before stopping.")
        return

    print(f"\nDone. {total_saved} records saved, {errors} failed, {empty_jobs} empty answers.")
    if errors or empty_jobs:
        print("Run the same command again to retry the failed and empty ones.")


if __name__ == "__main__":
    main()
