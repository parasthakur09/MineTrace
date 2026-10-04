"""Tests for MineTrace rules, explanations, reports and ingestion parsing.

Run from the backend folder:  python -m unittest discover tests -v

The numbers below are synthetic test fixtures, chosen to sit just above or
below each threshold. They are never shown in the app.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "minetrace_test.db"
os.environ["MINETRACE_DB"] = str(TEST_DB)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analytics  # noqa: E402
import narrative  # noqa: E402
import report  # noqa: E402
import service  # noqa: E402
from db import init_db, session, upsert_flow  # noqa: E402
from ingest_comtrade import store_rows  # noqa: E402


def add(conn, reporter, partner, flow, value, weight, year=2024, hs="282200", reported=1):
    upsert_flow(conn, mineral="cobalt", hs_code=hs, year=year, reporter_iso=reporter,
                partner_iso=partner, flow=flow, value_usd=value, net_weight_kg=weight,
                is_reported=reported)


def build_fixture(with_sanctions=True):
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()
    with session() as conn:
        # Mirror gap: DR Congo says $400k, China says $1m for the same flow.
        add(conn, "COD", "CHN", "X", 400_000, 40_000)
        add(conn, "CHN", "COD", "M", 1_000_000, 100_000)

        # Agreeing mirror (within 10%): Zambia -> China.
        add(conn, "ZMB", "CHN", "X", 950_000, 95_000)
        add(conn, "CHN", "ZMB", "M", 1_000_000, 100_000)

        # One-sided route: Morocco -> Finland, only Finland reported.
        add(conn, "FIN", "MAR", "M", 300_000, 30_000)

        # Volume spike on South Africa -> Japan.
        for year, value in ((2021, 1_000_000), (2022, 1_100_000), (2023, 900_000)):
            add(conn, "JPN", "ZAF", "M", value, value / 10, year=year)
        add(conn, "JPN", "ZAF", "M", 3_500_000, 350_000)

        # Concentration: Belgium gets 90% from one supplier.
        add(conn, "BEL", "COD", "M", 900_000, 90_000)
        add(conn, "BEL", "ZMB", "M", 100_000, 10_000)

        # Unit value outlier: Korea pays $150/kg while typical is ~$10/kg.
        add(conn, "KOR", "CHN", "M", 1_500_000, 10_000)

        if with_sanctions:
            conn.execute(
                "INSERT INTO sanctions_exposure (iso3, sanctioned_entities, mining_linked_entities, sample_entities) "
                "VALUES ('RUS', 900, 60, ?)",
                (json.dumps([{"id": "x1", "name": "Example Mining Co"}]),),
            )
            conn.execute(
                "INSERT INTO sanctions_exposure (iso3, sanctioned_entities, mining_linked_entities, sample_entities) "
                "VALUES ('COD', 40, 12, ?)",
                (json.dumps([{"id": "x2", "name": "Example Minerals SARL"}]),),
            )
            # Russia -> China route so R5 can reach risk level.
            add(conn, "CHN", "RUS", "M", 200_000, 20_000)


def flags_for(exporter, importer, year=2024):
    return service.route_detail("cobalt", year, exporter, importer)["assessment"]


class RuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_fixture()

    def rules(self, assessment):
        return {f["rule"]: f for f in assessment["flags"]}

    def test_mirror_gap_flags_large_difference(self):
        flag = self.rules(flags_for("COD", "CHN"))["R1"]
        self.assertEqual(flag["severity"], "risk")
        self.assertIn("60%", flag["title"])

    def test_mirror_gap_passes_normal_difference(self):
        a = flags_for("ZMB", "CHN")
        self.assertNotIn("R1", self.rules(a))
        self.assertEqual(next(c for c in a["checks"] if c["rule"] == "R1")["status"], "passed")

    def test_mirror_gap_skipped_when_one_sided(self):
        check = next(c for c in flags_for("MAR", "FIN")["checks"] if c["rule"] == "R1")
        self.assertEqual(check["status"], "skipped")
        self.assertIn("Only one country", check["note"])

    def test_volume_spike(self):
        flag = self.rules(flags_for("ZAF", "JPN"))["R2"]
        self.assertEqual(flag["severity"], "risk")
        self.assertIn("3.5x", flag["title"])

    def test_volume_spike_skipped_without_history(self):
        check = next(c for c in flags_for("COD", "CHN")["checks"] if c["rule"] == "R2")
        self.assertEqual(check["status"], "skipped")

    def test_concentration_uses_network(self):
        flag = self.rules(flags_for("COD", "BEL"))["R3"]
        self.assertEqual(flag["severity"], "risk")
        self.assertIn("90%", flag["title"])

    def test_unit_value_outlier(self):
        flag = self.rules(flags_for("CHN", "KOR"))["R4"]
        self.assertEqual(flag["severity"], "risk")
        self.assertIn("above", flag["title"])

    def test_jurisdiction_exposure(self):
        self.assertEqual(self.rules(flags_for("RUS", "CHN"))["R5"]["severity"], "risk")
        self.assertEqual(self.rules(flags_for("COD", "CHN"))["R5"]["severity"], "caution")

    def test_r5_ignores_importer_side(self):
        # China imports from Russia; China itself has no sanctions entry in the fixture.
        a = flags_for("ZMB", "CHN")
        self.assertNotIn("R5", self.rules(a))

    def test_small_routes_are_not_assessed(self):
        with session() as conn:
            add(conn, "ITA", "GHA", "M", 8_694, 75)
        analytics._context_cached.cache_clear()
        analytics._assess_year_cached.cache_clear()
        a = flags_for("GHA", "ITA")
        self.assertEqual(a["level"], "minor")
        self.assertEqual(a["flags"], [])
        self.assertEqual(a["checks_run"], 0)

    def test_level_and_coverage(self):
        a = flags_for("COD", "CHN")
        self.assertEqual(a["level"], "risk")
        self.assertIn(a["coverage"], ("good", "partial", "limited"))
        self.assertEqual(a["checks_total"], 5)

    def test_list_routes_summary(self):
        data = service.list_routes("cobalt", 2024)
        self.assertGreater(data["summary"]["risk"], 0)
        self.assertEqual(len(data["routes"]), data["summary"]["routes"])
        self.assertTrue(all(r["from_iso"] and r["to_iso"] for r in data["routes"]))
        self.assertIn("top_exporters", data["network"])

    def test_unknown_mineral(self):
        with self.assertRaises(service.NotFound):
            service.list_routes("unobtainium")


class SanctionsMissingTest(unittest.TestCase):
    def test_r5_skipped_without_data(self):
        build_fixture(with_sanctions=False)
        analytics._context_cached.cache_clear()
        analytics._assess_year_cached.cache_clear()
        check = next(c for c in flags_for("COD", "CHN")["checks"] if c["rule"] == "R5")
        self.assertEqual(check["status"], "skipped")
        build_fixture()
        analytics._context_cached.cache_clear()
        analytics._assess_year_cached.cache_clear()


class NarrativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_fixture()
        analytics._context_cached.cache_clear()
        cls.detail = service.route_detail("cobalt", 2024, "COD", "CHN")
        cls.facts = narrative.build_facts(cls.detail)

    def test_template_cites_rules(self):
        text = narrative.template_narrative(self.facts)
        for flag in self.facts["flags"]:
            self.assertIn(f"[{flag['rule']}]", text)
        ok, _ = narrative.validate_llm_text(text, self.facts)
        self.assertTrue(ok)

    def test_rejects_invented_number(self):
        text = ("DR Congo shipped cobalt worth $7,777,777 to China in 2024 [R1]. "
                "The reports differ [R1]. Sanctioned firms exist [R5].")
        ok, reason = narrative.validate_llm_text(text, self.facts)
        self.assertFalse(ok)
        self.assertIn("7777777", reason.replace(",", ""))

    def test_rejects_rule_that_did_not_flag(self):
        text = "The route shows a sharp volume spike in 2024 [R2]. Reports also differ by 60% [R1]."
        ok, reason = narrative.validate_llm_text(text, self.facts)
        self.assertFalse(ok)
        self.assertIn("R2", reason)

    def test_rejects_missing_citations(self):
        text = "The exporter and importer report different values for this route in 2024, by 60%."
        ok, _ = narrative.validate_llm_text(text, self.facts)
        self.assertFalse(ok)

    def test_accepts_grounded_text(self):
        text = ("In 2024 the importer reported a higher value than the exporter, a gap of 60% [R1]. "
                "OpenSanctions lists 12 sanctioned mining-linked entities in the Democratic Republic "
                "of the Congo [R5]. This is a screening result, not proof of wrongdoing.")
        ok, reason = narrative.validate_llm_text(text, self.facts)
        self.assertTrue(ok, reason)

    def test_explain_falls_back_without_ollama(self):
        os.environ["MINETRACE_OLLAMA_URL"] = "http://127.0.0.1:9"
        narrative.OLLAMA_URL = "http://127.0.0.1:9"
        result = narrative.explain(self.detail)
        self.assertEqual(result["generator"], "template")
        self.assertIn("not running", result["note"])

    def test_report_html(self):
        html = report.build_report(self.detail, narrative.explain(self.detail, use_llm=False))
        self.assertIn("<!doctype html>", html)
        self.assertIn("Mirror gap", html)
        self.assertIn("not a legal or compliance determination", html)


class IngestionParsingTests(unittest.TestCase):
    def test_store_rows_maps_codes_and_filters(self):
        build_fixture(with_sanctions=False)
        rows = [
            # Comtrade uses 842 for the USA; must map to USA, not be dropped.
            {"flowCode": "M", "partnerCode": 842, "cmdCode": "282200", "refYear": 2023,
             "primaryValue": 1000.0, "netWgt": 10.0, "isReported": True, "isAggregate": False,
             "partner2Code": 0, "motCode": 0, "customsCode": "C00"},
            # World total, must be skipped.
            {"flowCode": "M", "partnerCode": 0, "cmdCode": "282200", "refYear": 2023,
             "primaryValue": 5000.0, "partner2Code": 0, "motCode": 0, "customsCode": "C00"},
            # Re-export, must be skipped.
            {"flowCode": "RX", "partnerCode": 156, "cmdCode": "282200", "refYear": 2023,
             "primaryValue": 5000.0, "partner2Code": 0, "motCode": 0, "customsCode": "C00"},
            # Weight given only as quantity in kg.
            {"flowCode": "X", "partnerCode": 156, "cmdCode": "260500", "refYear": 2023,
             "primaryValue": 2000.0, "netWgt": None, "qty": 50.0, "qtyUnitCode": 8,
             "isReported": True, "partner2Code": 0, "motCode": 0, "customsCode": "C00"},
        ]
        with session() as conn:
            saved, _ = store_rows(conn, "JPN", rows)
            stored = conn.execute(
                "SELECT partner_iso, flow, net_weight_kg FROM trade_flows "
                "WHERE reporter_iso='JPN' AND year=2023 AND partner_iso IN ('USA','CHN') ORDER BY flow DESC"
            ).fetchall()
        self.assertEqual(saved, 2)
        self.assertEqual([(r["partner_iso"], r["flow"]) for r in stored], [("CHN", "X"), ("USA", "M")])
        self.assertEqual(stored[0]["net_weight_kg"], 50.0)


if __name__ == "__main__":
    unittest.main()


class IngestionRetryTests(unittest.TestCase):
    """Comtrade's free endpoint sometimes answers OK with no rows when busy."""

    def setUp(self):
        build_fixture(with_sanctions=False)
        import ingest_comtrade
        self.ic = ingest_comtrade
        self._saved = (ingest_comtrade.fetch, ingest_comtrade.requests.get, ingest_comtrade.time.sleep)
        self.ic.time.sleep = lambda s: None      # no real waiting in tests
        self.row = {"flowCode": "M", "partnerCode": 156, "cmdCode": "282200", "refYear": 2022,
                    "primaryValue": 1000.0, "netWgt": 10.0, "isReported": True,
                    "partner2Code": 0, "motCode": 0, "customsCode": "C00"}

    def tearDown(self):
        self.ic.fetch, self.ic.requests.get, self.ic.time.sleep = self._saved

    def test_empty_answer_is_retried_within_a_run(self):
        answers = [[], [self.row]]
        self.ic.fetch = lambda params, key: answers.pop(0)
        with session() as conn:
            returned, saved, _ = self.ic.ingest_one(conn, "DEU", 2022, ["282200"], None)
        self.assertEqual((returned, saved), (1, 1))

    def test_aggregated_rows_are_kept(self):
        row = dict(self.row, isAggregate=True)   # how Germany's 6-digit rows arrive
        with session() as conn:
            saved, _ = self.ic.store_rows(conn, "DEU", [row])
        self.assertEqual(saved, 1)

    def test_quota_stops_cleanly(self):
        class Response:
            status_code = 403
            text = '{"statusCode": 403, "message": "Out of call volume quota."}'
        self.ic.requests.get = lambda *a, **k: Response()
        with self.assertRaises(self.ic.QuotaExceeded):
            self.ic.fetch({}, None)

    def test_job_completion_rules(self):
        done = self.ic.job_is_complete
        self.assertFalse(done(None))
        self.assertFalse(done({"status": "done", "rows_saved": 0, "message": None}))   # old empty runs retried
        self.assertTrue(done({"status": "done", "rows_saved": 12, "message": None}))
        self.assertFalse(done({"status": "nodata", "rows_saved": 0, "message": None}))  # old filter bug, retry
        self.assertTrue(done({"status": "no_relevant_rows", "rows_saved": 0, "message": None}))
        self.assertFalse(done({"status": "empty", "rows_saved": 0, "message": "2"}))
        self.assertTrue(done({"status": "empty", "rows_saved": 0, "message": "3"}))
