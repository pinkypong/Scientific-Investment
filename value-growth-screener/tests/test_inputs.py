from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vgs.cli import main
from vgs.engine import analyze_security
from vgs.export import build_detail
from vgs.inputs import load_payload, merge_assumptions, split_payload


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.combined = json.loads((EXAMPLES / "synthetic_compounder.json").read_text(encoding="utf-8"))
        cls.config = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))

    def test_committed_split_example_matches_combined_example(self):
        merged = load_payload(EXAMPLES / "facts" / "DEMO.json", EXAMPLES / "assumptions")
        self.assertEqual(merged, self.combined)

    def test_split_then_merge_round_trips(self):
        facts, document = split_payload(self.combined)
        self.assertNotIn("assumptions", facts)
        self.assertEqual(document["ticker"], "DEMO")
        self.assertEqual(merge_assumptions(facts, document), self.combined)

    def test_facts_file_with_assumptions_is_refused(self):
        with self.assertRaises(ValueError):
            merge_assumptions(self.combined, None)

    def test_assumptions_for_another_ticker_are_refused(self):
        facts, document = split_payload(self.combined)
        document["ticker"] = "OTHER"
        with self.assertRaises(ValueError):
            merge_assumptions(facts, document)

    def test_missing_assumptions_file_still_screens(self):
        with TemporaryDirectory() as empty:
            payload = load_payload(EXAMPLES / "facts" / "DEMO.json", empty)
        self.assertEqual(payload["assumptions"], {})
        bare = build_detail(analyze_security(payload, self.config))
        full = build_detail(analyze_security(self.combined, self.config))
        self.assertEqual(bare["step1"], full["step1"])  # Step 1 does not need assumptions
        self.assertEqual(bare["step2"]["scenario_valuation"], [])
        self.assertIn("NO_SCENARIOS", {flag["code"] for flag in bare["step2"]["flags"]})

    def test_regenerating_facts_never_touches_assumptions(self):
        with TemporaryDirectory() as tmp:
            facts_dir, assumptions_dir = Path(tmp) / "facts", Path(tmp) / "assumptions"
            source = Path(tmp) / "combined.json"
            source.write_text(json.dumps(self.combined), encoding="utf-8")
            args = ["split-input", str(source), "--facts-dir", str(facts_dir), "--assumptions-dir", str(assumptions_dir)]
            self.assertEqual(main(args), 0)
            edited = json.loads((assumptions_dir / "DEMO.json").read_text(encoding="utf-8"))
            edited["assumptions"]["scenarios"]["base"]["wacc"] = 0.123  # a person's edit
            (assumptions_dir / "DEMO.json").write_text(json.dumps(edited), encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(args)
            kept = json.loads((assumptions_dir / "DEMO.json").read_text(encoding="utf-8"))
            self.assertEqual(kept["assumptions"]["scenarios"]["base"]["wacc"], 0.123)

    def test_cli_screen_and_export_accept_assumptions_dir(self):
        with TemporaryDirectory() as tmp:
            code = main(["export", str(EXAMPLES / "facts" / "DEMO.json"), "--assumptions-dir",
                         str(EXAMPLES / "assumptions"), "--config", str(ROOT / "config" / "default.json"),
                         "--out", tmp])
            self.assertEqual(code, 0)
            detail = json.loads((Path(tmp) / "detail" / "DEMO.json").read_text(encoding="utf-8"))
            self.assertEqual(len(detail["step2"]["scenario_valuation"]), 3)


if __name__ == "__main__":
    unittest.main()
