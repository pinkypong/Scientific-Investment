from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import unittest

from vgs.cli import main
from vgs.data.cache import DataStore
from vgs.data.models import SecurityRecord
from vgs.data.sectors import (annotation_lines, classify, collect_sector_rows, load_overrides, load_sector_map,
                              render_summary_markdown, sic_from_submissions, summarize)
from vgs.engine import analyze_security
from vgs.export import attach_classification, build_detail, build_screen


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "config" / "sectors.json"


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class SectorMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map = load_sector_map(MAP_PATH)

    def test_committed_table_loads_with_twelve_sectors(self):
        self.assertEqual(len(self.map.sectors), 12)
        self.assertEqual(self.map.sectors[0]["key"], "semiconductors")
        self.assertEqual(sum(len(s["industries"]) for s in self.map.catalog()), len(self.map.industries))

    def test_representative_sic_codes(self):
        expected = {
            3674: ("semiconductors", "semiconductors"), 3559: ("semiconductors", "semi_equipment"),
            3572: ("hardware", "computers_storage"), 3576: ("hardware", "computers_storage"),
            7372: ("software", "software_services"), 7370: ("software", "software_services"),
            4841: ("communication", "telecom"), 2834: ("healthcare", "pharma_biotech"),
            3841: ("healthcare", "medical_devices"), 6324: ("healthcare", "managed_care"),
            5122: ("healthcare", "health_distribution"), 6021: ("financials", "banks"),
            6211: ("financials", "capital_markets"), 6331: ("financials", "insurance"),
            6798: ("real_estate", "reit"), 1311: ("energy", "oil_gas"), 2911: ("energy", "refining"),
            4911: ("utilities", "utilities"), 4953: ("industrials", "environmental_services"),
            3812: ("industrials", "aerospace_defense"), 3711: ("consumer", "autos"),
            5961: ("consumer", "retail"), 5812: ("consumer", "restaurants"), 3021: ("consumer", "apparel"),
            2844: ("consumer", "household_personal"), 3411: ("materials", "paper_packaging"),
            1040: ("materials", "mining"),
        }
        for sic, (sector, industry) in expected.items():
            result = classify("X", sic, None, self.map)
            self.assertEqual((result["sector"], result["industry"], result["source"]), (sector, industry, "sec_sic"), sic)

    def test_narrow_rules_beat_wide_ranges(self):
        self.assertEqual(self.map.industry_for(6324), "managed_care")       # not insurance 6300-6411
        self.assertEqual(self.map.industry_for(6798), "reit")               # not investment_holding
        self.assertEqual(self.map.industry_for(7370), "software_services")  # not business_services
        self.assertEqual(self.map.industry_for(3674), "semiconductors")     # not electronic_components

    def test_uncovered_code_is_reported_not_guessed(self):
        result = classify("X", 9995, "Non-Operating Establishments", self.map)
        self.assertEqual(result["source"], "unclassified")
        self.assertIsNone(result["sector"])
        self.assertEqual(result["sic"], 9995)
        self.assertIsNone(classify("X", None, None, self.map)["sector"])

    def test_bad_tables_are_rejected(self):
        base = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cases = {
            "wide rule hides a narrow one": lambda d: d["rules"].insert(0, {"sic_from": 3600, "sic_to": 3699, "industry": "electrical_equipment"}),
            "unknown industry": lambda d: d["rules"].append({"sic_from": 9000, "sic_to": 9001, "industry": "nope"}),
            "unknown sector": lambda d: d["industries"].append({"key": "x", "label": "x", "sector": "nope"}),
            "reversed range": lambda d: d["rules"].append({"sic_from": 9100, "sic_to": 9000, "industry": "banks"}),
        }
        for name, mutate in cases.items():
            data = deepcopy(base)
            mutate(data)
            with TemporaryDirectory() as tmp, self.assertRaises(ValueError, msg=name):
                load_sector_map(write_json(Path(tmp) / "m.json", data))


class OverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map = load_sector_map(MAP_PATH)

    def test_committed_overrides_are_exactly_the_user_approved_ones(self):
        # Approved by the user on 2026-10-22 after the first live SEC run. GOOGL was kept on its SIC rule.
        overrides = load_overrides(ROOT / "config" / "sector_overrides.json", self.map)
        self.assertEqual({k: v["industry"] for k, v in overrides.items()},
                         {"QCOM": "semiconductors", "SNDK": "semiconductors"})
        self.assertTrue(all(v["decided_on"] == "2026-10-22" for v in overrides.values()))
        qcom = classify("QCOM", 3663, "Radio & Tv Broadcasting & Communications Equipment", self.map, overrides)
        self.assertEqual((qcom["sector"], qcom["source"], qcom["sic"], qcom["sic_industry"]),
                         ("semiconductors", "override", 3663, "comm_equipment"))

    def test_override_wins_and_keeps_the_sec_facts(self):
        with TemporaryDirectory() as tmp:
            path = write_json(Path(tmp) / "o.json", {"overrides": {"googl": {
                "industry": "media", "reason": "광고 매출 중심", "decided_on": "2026-10-22"}}})
            overrides = load_overrides(path, self.map)
        result = classify("GOOGL", 7370, "Services-Computer Programming", self.map, overrides)
        self.assertEqual((result["sector"], result["industry"], result["source"]), ("communication", "media", "override"))
        self.assertEqual((result["sic"], result["sic_industry"]), (7370, "software_services"))
        self.assertEqual(result["override_reason"], "광고 매출 중심")

    def test_bad_overrides_are_rejected(self):
        for item in ({"industry": "nope", "reason": "x"}, {"industry": "media", "reason": "  "}):
            with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                load_overrides(write_json(Path(tmp) / "o.json", {"overrides": {"ABC": item}}), self.map)

    def test_missing_override_file_means_none(self):
        self.assertEqual(load_overrides(ROOT / "config" / "does-not-exist.json", self.map), {})


class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map = load_sector_map(MAP_PATH)

    def test_sic_from_submissions(self):
        self.assertEqual(sic_from_submissions({"sic": "3674", "sicDescription": "Semiconductors"}), (3674, "Semiconductors"))
        self.assertEqual(sic_from_submissions({"sic": "", "sicDescription": ""}), (None, None))

    def test_every_record_is_listed_even_when_something_fails(self):
        def fetch(cik):  # SecurityRecord pads CIKs to 10 digits
            if int(cik) == 2:
                raise TimeoutError("slow")
            return {"sic": "3674" if int(cik) == 1 else "", "sicDescription": "Semiconductors"}
        records = [SecurityRecord("MU", "Micron", cik="1"), SecurityRecord("BAD", "Bad", cik="2"),
                   SecurityRecord("NOSIC", "No sic", cik="3"), SecurityRecord("NOCIK", "No cik")]
        rows = {r["symbol"]: r for r in collect_sector_rows(records, fetch, self.map, {}, "2026-10-22T00:00:00Z")}
        self.assertEqual(rows["MU"]["sector"], "semiconductors")
        self.assertEqual(rows["MU"]["url"], "https://data.sec.gov/submissions/CIK0000000001.json")
        self.assertEqual(rows["BAD"]["note"], "fetch_failed: TimeoutError")
        self.assertEqual(rows["NOSIC"]["note"], "sic_missing")
        self.assertEqual(rows["NOCIK"]["note"], "cik_not_found")
        for symbol in ("BAD", "NOSIC", "NOCIK"):
            self.assertEqual(rows[symbol]["source"], "unclassified")
        lines = summarize(list(rows.values()), self.map)
        self.assertIn("반도체: 1", lines)
        self.assertTrue(any(line.startswith("unclassified 3:") for line in lines))

    def test_cli_reads_cached_sec_submissions_without_network(self):
        with TemporaryDirectory() as tmp:
            store = DataStore(tmp)
            store.write_json("raw", "sec-submissions-CIK0000723125", {"sic": "3674", "sicDescription": "Semiconductors & Related Devices"})
            store.write_json("raw", "sec-submissions-CIK0001652044", {"sic": "7370", "sicDescription": "Services-Computer Programming"})
            universe = Path(tmp) / "universe.jsonl"
            universe.write_text("\n".join(json.dumps(r) for r in (
                {"symbol": "MU", "name": "Micron", "cik": "723125"},
                {"symbol": "GOOGL", "name": "Alphabet", "cik": "1652044"})) + "\n", encoding="utf-8")
            test_contact = "test" + chr(64) + "example.com"  # same pattern as test_data.py (keeps gitleaks quiet)
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
                code = main(["sec-sectors", "--universe", str(universe), "--data-root", tmp,
                             "--user-agent", f"VGS test runner {test_contact}"])
            self.assertEqual(code, 0)
            lines = (Path(tmp) / "normalized" / "sectors-sec.jsonl").read_text(encoding="utf-8").splitlines()
            rows = {json.loads(line)["symbol"]: json.loads(line) for line in lines}
        self.assertEqual(rows["MU"]["sector"], "semiconductors")
        self.assertEqual(rows["GOOGL"]["industry"], "software_services")
        self.assertEqual(rows["GOOGL"]["provider"], "SEC")


class RunSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map = load_sector_map(MAP_PATH)
        overrides = {"GOOGL": {"industry": "media", "reason": "광고 | 검색", "decided_on": "2026-10-22"}}

        def fetch(cik):
            if int(cik) == 2:
                raise TimeoutError("slow")
            return {"1": {"sic": "3674", "sicDescription": "Semiconductors & Related Devices"},
                    "3": {"sic": "", "sicDescription": ""},
                    "4": {"sic": "9995", "sicDescription": "Non-Operating | Establishments"},
                    "5": {"sic": "7370", "sicDescription": "Services-Computer Programming"}}[str(int(cik))]
        records = [SecurityRecord("MU", "Micron", cik="1"), SecurityRecord("BAD", "Bad", cik="2"),
                   SecurityRecord("NOSIC", "No sic", cik="3"), SecurityRecord("SHELL", "Shell", cik="4"),
                   SecurityRecord("GOOGL", "Alphabet", cik="5"), SecurityRecord("NOCIK", "No cik")]
        cls.rows = collect_sector_rows(records, fetch, cls.map, overrides, "2026-10-22T00:00:00Z")

    def test_markdown_table(self):
        markdown = render_summary_markdown(self.rows, self.map)
        lines = markdown.splitlines()
        self.assertEqual(lines[0], "### SEC 섹터 분류")
        self.assertIn(self.map.version, markdown)
        self.assertIn("2026-10-22T00:00:00Z", markdown)
        self.assertIn("섹터별: 반도체 1 · 통신·미디어 1", markdown)
        table = [line for line in lines if line.startswith("| ") and "---" not in line]
        self.assertEqual(table[0], "| 종목 | 분류 | 출처 | 비고 | SIC |")
        self.assertEqual([line.split(" | ")[0][2:] for line in table[1:]], ["MU", "BAD", "NOSIC", "SHELL", "GOOGL", "NOCIK"])
        self.assertEqual(table[1], "| MU | 반도체 | 규칙 |  | 3674 · Semiconductors & Related Devices |")
        self.assertEqual(table[2], "| BAD | - | 미분류 | fetch_failed: TimeoutError |  |")
        self.assertIn("| NOSIC | - | 미분류 | sic_missing |  |", table)
        self.assertIn("| SHELL | - | 미분류 |  | 9995 · Non-Operating \\| Establishments |", table)
        self.assertEqual(table[5], "| GOOGL | 통신·미디어 › 미디어·출판·엔터 | 예외 | 광고 \\| 검색 | 7370 · Services-Computer Programming |")
        self.assertIn("| NOCIK | - | 미분류 | cik_not_found |  |", table)
        for line in table:
            self.assertEqual(line.replace("\\|", "").count("|"), 6, line)  # 5 cells, escaping holds
        self.assertEqual(lines[-1], "전체 6개 · 미분류 4개 · 실패 2개")

    def test_annotations(self):
        self.assertEqual(annotation_lines(self.rows), [
            "::error title=SEC sectors::2개 종목 실패: BAD(fetch_failed: TimeoutError), NOCIK(cik_not_found)",
            "::warning title=SEC sectors::2개 종목 미분류: NOSIC(sic_missing), SHELL(9995)"])
        self.assertEqual(annotation_lines([r for r in self.rows if r["symbol"] == "MU"]), [])

    def _run_cli(self, tmp, env, *extra, with_failure=False):
        DataStore(tmp).write_json("raw", "sec-submissions-CIK0000723125", {"sic": "3674", "sicDescription": "Semiconductors & Related Devices"})
        records = [{"symbol": "MU", "name": "Micron", "cik": "723125"}]
        if with_failure:
            records.append({"symbol": "NOCIK", "name": "No cik"})
        universe = Path(tmp) / "universe.jsonl"
        universe.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        test_contact = "test" + chr(64) + "example.com"  # same pattern as test_data.py (keeps gitleaks quiet)
        argv = ["sec-sectors", "--universe", str(universe), "--data-root", tmp,
                "--user-agent", f"VGS test runner {test_contact}", *extra]
        output = io.StringIO()
        # Start from a clean GitHub env so the suite behaves the same locally and inside Actions.
        clean = {k: v for k, v in os.environ.items() if k not in ("GITHUB_STEP_SUMMARY", "GITHUB_ACTIONS")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")), \
                redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_cli_appends_to_github_step_summary(self):
        with TemporaryDirectory() as tmp:
            summary = Path(tmp) / "step_summary.md"
            summary.write_text("earlier step\n", encoding="utf-8")
            code, out = self._run_cli(tmp, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_ACTIONS": "true"}, with_failure=True)
            text = summary.read_text(encoding="utf-8")
        self.assertEqual(code, 0)  # failures stay visible but do not fail the step by default
        self.assertTrue(text.startswith("earlier step\n### SEC 섹터 분류"))
        self.assertIn("| MU | 반도체 | 규칙 |", text)
        self.assertIn("| NOCIK | - | 미분류 | cik_not_found |  |", text)
        self.assertIn("반도체: 1", out)  # existing stdout lines are kept
        self.assertIn("::error title=SEC sectors::1개 종목 실패: NOCIK(cik_not_found)", out)

    def test_cli_without_github_env_writes_nothing_extra(self):
        with TemporaryDirectory() as tmp:
            code, out = self._run_cli(tmp, {"GITHUB_STEP_SUMMARY": ""}, with_failure=True)
            files = sorted(p.name for p in Path(tmp).rglob("*.md"))
        self.assertEqual(code, 0)
        self.assertEqual(files, [])
        self.assertNotIn("::", out)

    def test_cli_summary_option_and_strict(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "summary.md"
            code, _ = self._run_cli(tmp, {}, "--summary", str(target), "--strict")
            self.assertEqual(code, 0)
            self.assertIn("| MU | 반도체 | 규칙 |", target.read_text(encoding="utf-8"))
        with TemporaryDirectory() as tmp:
            code, _ = self._run_cli(tmp, {}, "--strict", with_failure=True)
            self.assertEqual(code, 1)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map = load_sector_map(MAP_PATH)
        payload = json.loads((ROOT / "examples" / "synthetic_compounder.json").read_text(encoding="utf-8"))
        config = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
        cls.result = analyze_security(payload, config)
        cls.row = classify("DEMO", 3674, "Semiconductors & Related Devices", cls.map)
        cls.row.update({"provider": "SEC", "observed_at": "2026-10-22T00:00:00Z",
                        "url": "https://data.sec.gov/submissions/CIK0000000001.json"})

    def test_screen_rows_and_catalog(self):
        before = deepcopy(self.result)
        tagged = attach_classification(self.result, self.row)
        self.assertEqual(self.result, before)  # input untouched
        screen = build_screen([tagged], "demo", self.map.catalog())
        row = screen["rows"][0]
        self.assertEqual((row["sector"], row["industry"], row["sector_source"], row["sic"]),
                         ("semiconductors", "semiconductors", "sec_sic", 3674))
        self.assertEqual(row["sector_label"], "반도체")
        self.assertEqual([s["key"] for s in screen["meta"]["sectors"]][:3], ["semiconductors", "hardware", "software"])

    def test_detail_carries_classification_and_facts_hash_is_unchanged(self):
        tagged = build_detail(attach_classification(self.result, self.row))
        plain = build_detail(self.result)
        self.assertEqual(tagged["security"]["classification"]["sic_description"], "Semiconductors & Related Devices")
        self.assertEqual(tagged["security"]["classification"]["url"], "https://data.sec.gov/submissions/CIK0000000001.json")
        self.assertEqual(tagged["integrity"], plain["integrity"])  # classification is not part of the facts hash

    def test_cli_export_with_sectors(self):
        with TemporaryDirectory() as tmp:
            sectors = Path(tmp) / "sectors.jsonl"
            sectors.write_text(json.dumps(self.row, ensure_ascii=False) + "\n", encoding="utf-8")
            out = Path(tmp) / "out"
            code = main(["export", str(ROOT / "examples" / "synthetic_compounder.json"), "--config",
                         str(ROOT / "config" / "default.json"), "--out", str(out), "--sectors", str(sectors)])
            self.assertEqual(code, 0)
            screen = json.loads((out / "screen.json").read_text(encoding="utf-8"))
        self.assertEqual(screen["rows"][0]["industry_label"], "반도체")
        self.assertEqual(len(screen["meta"]["sectors"]), 12)

    def test_export_without_sectors_has_no_catalog(self):
        self.assertNotIn("sectors", build_screen([self.result])["meta"])


if __name__ == "__main__":
    unittest.main()
