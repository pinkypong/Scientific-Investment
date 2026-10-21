from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vgs.cli import main
from vgs.engine import analyze_security
from vgs.export import SCREEN_COLUMNS, build_detail, build_screen, step3_links, write_export


ROOT = Path(__file__).resolve().parents[1]
ASSUMPTION_ONLY_KEYS = {"fair_value", "upside", "margin_of_safety", "decision", "scenario_valuation",
                        "risk_adjusted_opportunity_score", "probability_weighted_fair_value"}


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((ROOT / "examples" / "synthetic_compounder.json").read_text(encoding="utf-8"))
        cls.config = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))

    def analyze(self, payload=None):
        return analyze_security(payload or self.payload, self.config)

    def test_screen_rows_carry_no_assumption_dependent_values(self):
        screen = build_screen([self.analyze()], universe="demo")
        row = screen["rows"][0]
        self.assertEqual(screen["schema"], "vgs.screen/1")
        self.assertEqual(screen["meta"]["score_label"], "rule_based")
        self.assertFalse(ASSUMPTION_ONLY_KEYS & set(row), "Step 1 row leaked a Step 2 key")
        self.assertEqual(set(row["facts"]), {key for key, *_ in SCREEN_COLUMNS})
        self.assertEqual(row["detail"], "detail/DEMO.json")

    def test_every_column_path_exists_in_the_data_contract_example(self):
        row = build_screen([self.analyze()])["rows"][0]
        for column in build_screen([self.analyze()])["columns"]:
            self.assertTrue(column["path"].startswith("objective."))
            self.assertIsNotNone(row["facts"][column["key"]], column["key"])

    def test_objective_score_does_not_move_with_valuation_assumptions(self):
        baseline = build_screen([self.analyze()])["rows"][0]
        broken = deepcopy(self.payload)
        broken["assumptions"]["scenarios"]["bull"]["probability"] = 0.10  # critical BAD_PROBABILITIES
        result = self.analyze(broken)
        self.assertIn("BAD_PROBABILITIES", {flag["code"] for flag in result["flags"]})
        row = build_screen([result])["rows"][0]
        self.assertEqual(row["objective_score"], baseline["objective_score"])
        self.assertEqual(row["flags"], {"critical": 0, "warning": 0})  # valuation flags stay in step2
        detail = build_detail(result)
        self.assertIn("BAD_PROBABILITIES", {flag["code"] for flag in detail["step2"]["flags"]})
        self.assertNotIn("BAD_PROBABILITIES", {flag["code"] for flag in detail["step1"]["flags"]})

    def test_data_quality_critical_still_zeroes_auxiliary_score(self):
        payload = deepcopy(self.payload)
        payload["objective"]["market"]["price"] = 0.0  # BAD_PRICE is a data problem, not an assumption
        score = build_screen([self.analyze(payload)])["rows"][0]
        self.assertEqual(score["flags"]["critical"], 1)
        self.assertEqual(self.analyze(payload)["computed"]["objective_score"]["auxiliary_signals"], 0.0)

    def test_analyst_consensus_never_leaves_the_engine(self):
        payload = deepcopy(self.payload)
        payload["objective"]["consensus"] = {"eps_next_year": 99.0, "target_price": 999.0}
        result = self.analyze(payload)
        detail = build_detail(result)
        self.assertNotIn("consensus", detail["objective"])
        with TemporaryDirectory() as tmp:
            for path in write_export([result], tmp):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("target_price", text)
                self.assertNotIn("eps_next_year", text)

    def test_detail_is_pure_and_deterministic(self):
        result = self.analyze()
        before = deepcopy(result)
        first = json.dumps(build_detail(result), sort_keys=True)
        self.assertEqual(result, before)
        self.assertEqual(first, json.dumps(build_detail(self.analyze()), sort_keys=True))

    def test_integrity_hash_tracks_facts_not_assumptions(self):
        base = build_detail(self.analyze())["integrity"]["objective_sha256"]
        changed_assumption = deepcopy(self.payload)
        changed_assumption["assumptions"]["scenarios"]["base"]["wacc"] = 0.10
        self.assertEqual(build_detail(self.analyze(changed_assumption))["integrity"]["objective_sha256"], base)
        changed_fact = deepcopy(self.payload)
        changed_fact["objective"]["financials"]["revenue_ttm"] = 10001.0
        self.assertNotEqual(build_detail(self.analyze(changed_fact))["integrity"]["objective_sha256"], base)

    def test_step3_links_are_links_only_and_safe(self):
        payload = deepcopy(self.payload)
        payload["security"]["cik"] = "320193"
        payload["sources"] = [
            {"provider": "SEC", "url": "https://www.sec.gov/Archives/example", "fields": ["objective.*"]},
            {"provider": "evil", "url": "javascript:alert(1)", "fields": []},
            {"provider": "no url", "fields": []},
        ]
        links = step3_links(self.analyze(payload))
        self.assertEqual([link["kind"] for link in links], ["sec_filings", "source"])
        self.assertIn("CIK=0000320193", links[0]["url"])
        self.assertTrue(all(link["url"].startswith("https://") for link in links))
        self.assertEqual(set(links[0]), {"kind", "label", "url"})  # no numbers ride along
        self.assertEqual(step3_links(self.analyze()), [])  # nothing is invented without a CIK or URL

    def test_write_export_files_are_utf8_stable_and_strict_json(self):
        with TemporaryDirectory() as one, TemporaryDirectory() as two:
            paths = write_export([self.analyze()], one, "demo")
            write_export([self.analyze()], two, "demo")
            self.assertEqual([p.relative_to(one).as_posix() for p in paths], ["screen.json", "detail/DEMO.json"])
            for name in ("screen.json", "detail/DEMO.json"):
                self.assertEqual((Path(one) / name).read_bytes(), (Path(two) / name).read_bytes())
            screen = json.loads((Path(one) / "screen.json").read_text(encoding="utf-8"))
            self.assertIn("공시 숫자", screen["meta"]["note"])

    def test_nan_is_refused_instead_of_written_as_invalid_json(self):
        payload = deepcopy(self.payload)
        payload["objective"]["history"]["revenue_cagr_3y"] = float("nan")
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            write_export([self.analyze(payload)], tmp)

    def test_unsafe_or_duplicate_ticker_file_names(self):
        odd = deepcopy(self.payload)
        odd["security"]["ticker"] = "../EVIL"
        with TemporaryDirectory() as tmp:
            write_export([self.analyze(odd)], tmp)
            self.assertTrue((Path(tmp) / "detail" / ".._EVIL.json").exists())
            self.assertFalse((Path(tmp).parent / "EVIL.json").exists())
        a, b = deepcopy(self.payload), deepcopy(self.payload)
        a["security"]["ticker"], b["security"]["ticker"] = "A/B", "A_B"
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            write_export([self.analyze(a), self.analyze(b)], tmp)

    def test_cli_export(self):
        with TemporaryDirectory() as tmp:
            code = main(["export", str(ROOT / "examples" / "synthetic_compounder.json"),
                         "--config", str(ROOT / "config" / "default.json"), "--out", tmp, "--universe", "demo"])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "screen.json").exists())
            self.assertTrue((Path(tmp) / "detail" / "DEMO.json").exists())


if __name__ == "__main__":
    unittest.main()
