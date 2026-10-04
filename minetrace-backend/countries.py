"""Country reference: names, ISO codes, map coordinates and Comtrade codes."""

import csv
from functools import lru_cache

from config import COUNTRIES_CSV


@lru_cache(maxsize=1)
def _load():
    by_iso3, by_iso2, by_code = {}, {}, {}

    with COUNTRIES_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country = {
                "iso3": row["iso3"],
                "iso2": row["iso2"],
                "name": row["name"],
                "short_name": row["short_name"] or row["name"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }
            by_iso3[country["iso3"]] = country
            by_iso2[country["iso2"].upper()] = country
            by_code[int(row["m49"])] = country

            # Comtrade uses its own code for a few reporters (e.g. 842 for the USA).
            for alias in filter(None, (row.get("comtrade_aliases") or "").split(";")):
                by_code[int(alias)] = country

    m49_by_iso3 = {}
    with COUNTRIES_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m49_by_iso3[row["iso3"]] = int(row["m49"])

    return by_iso3, by_iso2, by_code, m49_by_iso3


def by_iso3(iso3):
    return _load()[0].get((iso3 or "").upper())


def by_iso2(iso2):
    return _load()[1].get((iso2 or "").upper())


def by_comtrade_code(code):
    try:
        return _load()[2].get(int(code))
    except (TypeError, ValueError):
        return None


def m49_code(iso3):
    return _load()[3].get((iso3 or "").upper())


def all_countries():
    return list(_load()[0].values())


def name(iso3):
    country = by_iso3(iso3)
    return country["name"] if country else iso3
