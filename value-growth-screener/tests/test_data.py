import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from vgs.data.alpaca import normalize_alpaca_pages
from vgs.data.cache import DataStore
from vgs.data.deep_dive import build_bigdata_queue
from vgs.data.factors import parse_ken_french_csv
from vgs.data.holdings import parse_ndx_holdings, parse_spy_holdings
from vgs.data.models import MarketBar, SecurityRecord
from vgs.data.sec import SecEdgarClient
from vgs.data.universe import build_universe, read_holdings_csv
from vgs.data.xbrl import normalize_companyfacts


def minimal_xlsx(rows):
    cells = []
    for row_number, row in enumerate(rows, 1):
        encoded = []
        for column, value in enumerate(row, 1):
            name, current = "", column
            while current:
                current, remainder = divmod(current - 1, 26)
                name = chr(65 + remainder) + name
            encoded.append(f'<c r="{name}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>')
        cells.append(f'<row r="{row_number}">{"".join(encoded)}</row>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(cells)}</sheetData></worksheet>')
    workbook = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    from io import BytesIO
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return stream.getvalue()


class DataLayerTests(unittest.TestCase):
    def test_security_normalizes_symbol_and_cik(self):
        record = SecurityRecord(symbol=" googl ", name="Alphabet", cik="1652044")
        self.assertEqual(record.symbol, "GOOGL")
        self.assertEqual(record.cik, "0001652044")

    def test_invalid_bar_is_rejected(self):
        with self.assertRaises(ValueError):
            MarketBar(symbol="X", timestamp="2026-09-01T00:00:00Z", open=10, high=9,
                      low=8, close=10, volume=100)

    def test_cache_round_trip_and_safe_path(self):
        with TemporaryDirectory() as temp:
            store = DataStore(temp)
            path = store.write_json("cache", "sample", {"ok": True})
            self.assertTrue(path.exists())
            self.assertEqual(store.read_json("cache", "sample"), {"ok": True})
            with self.assertRaises(ValueError):
                store.path("cache", "../escape")

    def test_sec_company_ticker_cache_normalization(self):
        with TemporaryDirectory() as temp:
            store = DataStore(temp)
            store.write_json("cache", "sec-company-tickers-exchange", {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"]]
            })
            test_contact = "test" + chr(64) + "example.com"
            client = SecEdgarClient(f"Researcher {test_contact}", store)
            records = client.company_tickers()
            self.assertEqual(records[0].symbol, "GOOGL")
            self.assertEqual(records[0].cik, "0001652044")

    def test_alpaca_page_normalization(self):
        pages = [{"bars": {"ADI": [{"t": "2026-09-01T04:00:00Z", "o": 350.0,
                                      "h": 355.0, "l": 348.0, "c": 352.0,
                                      "v": 1234, "n": 10, "vw": 351.5}]}}]
        rows = normalize_alpaca_pages(pages, feed="iex", observed_at="2026-09-02T00:00:00Z")
        self.assertEqual(rows[0].symbol, "ADI")
        self.assertEqual(rows[0].provider, "Alpaca")
        self.assertEqual(rows[0].feed, "iex")

    def test_universe_union_and_forced_holdings(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "holdings.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Ticker", "Name"])
                writer.writeheader()
                writer.writerow({"Ticker": "NVDA", "Name": "NVIDIA"})
                writer.writerow({"Ticker": "GOOGL", "Name": "Alphabet"})
            holdings = read_holdings_csv(path)
            master = [SecurityRecord(symbol="NVDA", name="NVIDIA Corp", cik="1045810", source="SEC")]
            universe = build_universe([holdings], master, forced_symbols=["MRVL"])
            by_symbol = {record.symbol: record for record in universe}
            self.assertEqual(set(by_symbol), {"GOOGL", "MRVL", "NVDA"})
            self.assertEqual(by_symbol["NVDA"].cik, "0001045810")
            self.assertEqual(by_symbol["MRVL"].source, "forced-holding")

    def test_official_holdings_parsers(self):
        spy = minimal_xlsx([["Fund Name", "SPY"], ["Holdings As of", "01-Sep-2026"],
                            ["Name", "Ticker", "Identifier", "Weight", "Local Currency"],
                            ["NVIDIA", "NVDA", "US67066G1040", "7.5", "USD"]])
        ndx = minimal_xlsx([["Report"], ["Company Name", "Security Symbol"], ["NVIDIA", "NVDA"]])
        self.assertEqual(parse_spy_holdings(spy)[0].weight, 7.5)
        self.assertEqual(parse_ndx_holdings(ndx, "2026-09-01")[0].symbol, "NVDA")

    def test_xbrl_point_in_time_q4_and_ttm(self):
        units = []
        for fp, start, end, value, filed in [
            ("Q1", "2025-01-01", "2025-03-31", 10, "2025-04-20"),
            ("Q2", "2025-04-01", "2025-06-30", 20, "2025-07-20"),
            ("Q3", "2025-07-01", "2025-09-30", 30, "2025-10-20"),
            ("FY", "2025-01-01", "2025-12-31", 100, "2026-02-15")]:
            units.append({"start": start, "end": end, "val": value, "filed": filed,
                          "form": "10-K" if fp == "FY" else "10-Q", "fy": 2025, "fp": fp})
        # Amendment after the requested as-of date must not leak into the snapshot.
        units.append({"start": "2025-01-01", "end": "2025-12-31", "val": 999,
                      "filed": "2026-04-01", "form": "10-K/A", "fy": 2025, "fp": "FY"})
        facts = {"cik": 1, "entityName": "Test", "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": units}}}}}
        result = normalize_companyfacts(facts, "2026-03-01")
        self.assertEqual(result["ttm"]["revenue"], 100)
        self.assertEqual(result["quarters"]["revenue"][-1]["value"], 40)
        self.assertTrue(result["quarters"]["revenue"][-1]["derived"])

    def test_ken_french_parser(self):
        text = "notes\n,Mkt-RF,SMB,HML,RF\n20260901,1.00,-0.50,0.25,0.01\nfooter"
        row = parse_ken_french_csv(text, "ff5_daily")[0]
        self.assertEqual(row["mkt_rf"], 0.01)
        self.assertEqual(row["smb"], -0.005)

    def test_bigdata_queue_tiers(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "ranking.csv"
            path.write_text("ticker,score\nNVDA,90\nADI,80\nQCOM,70\n", encoding="utf-8")
            rows = build_bigdata_queue(path, tier2=3, tier3=2, tier4=1)
            self.assertEqual([row["tier"] for row in rows], [4, 3, 2])
            forced = build_bigdata_queue(path, tier2=1, tier3=1, tier4=1, forced_symbols=["SNDK"])
            self.assertEqual(forced[-1]["reason"], "forced_current_holding")


if __name__ == "__main__":
    unittest.main()
