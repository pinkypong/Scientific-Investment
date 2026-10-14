from copy import deepcopy
import json
from pathlib import Path
import unittest

from vgs.engine import analyze_security, rank_results
from vgs.report import DISCLAIMER, render_markdown, render_ranking_csv


ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((ROOT / "examples" / "synthetic_compounder.json").read_text(encoding="utf-8"))
        cls.config = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))

    def test_analysis_preserves_objective_and_assumptions(self):
        before = deepcopy(self.payload)
        result = analyze_security(self.payload, self.config)
        self.assertEqual(self.payload, before)
        self.assertEqual(result["objective"], self.payload["objective"])
        self.assertEqual(result["assumptions"], self.payload["assumptions"])
        self.assertEqual(len(result["computed"]["scenario_valuation"]), 3)
        self.assertAlmostEqual(result["computed"]["data_completeness"], 1.0)
        self.assertAlmostEqual(result["computed"]["provenance_coverage"], 1.0)
        self.assertIsNotNone(result["computed"]["wacc_build"])
        self.assertEqual(result["computed"]["relative_cross_check"]["method"], "pe")
        self.assertGreater(result["computed"]["risk_adjusted_opportunity_score"], 0)

    def test_bad_probability_is_critical(self):
        payload = deepcopy(self.payload)
        payload["assumptions"]["scenarios"]["bull"]["probability"] = 0.10
        result = analyze_security(payload, self.config)
        self.assertIn("BAD_PROBABILITIES", {flag["code"] for flag in result["flags"]})
        self.assertEqual(result["computed"]["decision"], "WATCH_OR_REJECT")

    def test_accrual_flag_and_missing_data_reduce_gate(self):
        payload = deepcopy(self.payload)
        payload["objective"]["ratios"]["accrual_ratio"] = 0.15
        del payload["objective"]["risk"]["beta"]
        result = analyze_security(payload, self.config)
        self.assertIn("HIGH_ACCRUALS", {flag["code"] for flag in result["flags"]})
        self.assertLess(result["computed"]["data_completeness"], 1.0)

    def test_rank_and_render(self):
        first = analyze_security(self.payload, self.config)
        second_payload = deepcopy(self.payload)
        second_payload["security"]["ticker"] = "DEMO2"
        second_payload["objective"]["market"]["price"] = 400.0
        second = analyze_security(second_payload, self.config)
        ranked = rank_results([second, first])
        self.assertEqual(ranked[0]["security"]["ticker"], "DEMO")
        self.assertIn("Powered by Bigdata.com", render_markdown(first))
        self.assertIn("objective_score", render_ranking_csv(ranked))
        self.assertIn("## Disclaimer", DISCLAIMER)

    def test_wacc_must_exceed_terminal_growth(self):
        payload = deepcopy(self.payload)
        payload["assumptions"]["scenarios"]["base"]["wacc"] = 0.02
        result = analyze_security(payload, self.config)
        self.assertIn("VALUATION_INPUT", {flag["code"] for flag in result["flags"]})

    def test_analyst_consensus_is_ignored_and_flagged(self):
        clean = analyze_security(self.payload, self.config)
        payload = deepcopy(self.payload)
        payload["objective"]["consensus"] = {"forward_eps": 99.0, "revenue_growth_3y": 0.90,
                                             "eps_growth_3y": 0.90, "revision_90d": 0.50,
                                             "target_median": 999.0}
        dirty = analyze_security(payload, self.config)
        self.assertIn("ANALYST_INPUT_EXCLUDED", {flag["code"] for flag in dirty["flags"]})
        # Forecasts must not move the objective score, completeness, provenance or valuation.
        self.assertEqual(clean["computed"]["objective_score"], dirty["computed"]["objective_score"])
        self.assertEqual(clean["computed"]["data_completeness"], dirty["computed"]["data_completeness"])
        self.assertEqual(clean["computed"]["provenance_coverage"], dirty["computed"]["provenance_coverage"])
        self.assertEqual(clean["computed"]["relative_cross_check"]["fair_value_per_share"],
                         dirty["computed"]["relative_cross_check"]["fair_value_per_share"])

    def test_pe_cross_check_uses_reported_eps(self):
        result = analyze_security(self.payload, self.config)
        expected = self.payload["objective"]["financials"]["eps_ttm"] * 18.0
        self.assertAlmostEqual(result["computed"]["relative_cross_check"]["fair_value_per_share"], expected)

    def test_growth_score_uses_reported_history(self):
        payload = deepcopy(self.payload)
        payload["objective"]["history"] = {"revenue_cagr_3y": 0.18, "revenue_yoy_ttm": 0.25,
                                           "ebit_margin_change_3y": 0.05}
        best = analyze_security(payload, self.config)["computed"]["objective_score"]["growth_actual"]
        payload["objective"]["history"] = {"revenue_cagr_3y": -0.03, "revenue_yoy_ttm": -0.10,
                                           "ebit_margin_change_3y": -0.05}
        worst = analyze_security(payload, self.config)["computed"]["objective_score"]["growth_actual"]
        self.assertAlmostEqual(best, 20.0)
        self.assertAlmostEqual(worst, 0.0)

    def test_unverified_facts_fail_gate(self):
        payload = deepcopy(self.payload)
        payload["sources"] = []
        result = analyze_security(payload, self.config)
        self.assertEqual(result["computed"]["provenance_coverage"], 0.0)
        self.assertEqual(result["computed"]["decision"], "WATCH_OR_REJECT")


if __name__ == "__main__":
    unittest.main()
