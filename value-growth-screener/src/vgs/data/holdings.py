"""Official SPY and Nasdaq-100 constituent downloads without Excel dependencies."""

from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from .cache import DataStore
from .models import HoldingRecord, SecurityRecord

SPY_URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
NDX_URL = "https://indexes.nasdaqomx.com/Index/ExportWeightings/NDX"
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _column(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    value = 0
    for char in letters.group(0) if letters else "A":
        value = value * 26 + ord(char) - 64
    return value - 1


def read_first_sheet_xlsx(blob_or_path: bytes | str | Path) -> list[list[str]]:
    """Return the first worksheet as a rectangular-ish list of string rows."""
    source = io.BytesIO(blob_or_path) if isinstance(blob_or_path, bytes) else blob_or_path
    with zipfile.ZipFile(source) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in si.findall(".//m:t", _NS))
                      for si in root.findall("m:si", _NS)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find("m:sheets/m:sheet", _NS)
        if sheet is None:
            return []
        rel_id = sheet.attrib[f"{{{_NS['r']}}}id"]
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(rel.attrib["Target"] for rel in rels.findall("p:Relationship", _NS)
                      if rel.attrib["Id"] == rel_id)
        sheet_path = target.lstrip("/") if target.startswith("/xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(archive.read(sheet_path))
        output: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", _NS):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", _NS):
                index = _column(cell.attrib.get("r", "A1"))
                kind = cell.attrib.get("t")
                if kind == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//m:t", _NS))
                else:
                    node = cell.find("m:v", _NS)
                    raw = node.text if node is not None and node.text is not None else ""
                    value = shared[int(raw)] if kind == "s" and raw else raw
                values[index] = value.strip()
            if values:
                output.append([values.get(i, "") for i in range(max(values) + 1)])
        return output


def _number(value: str) -> float | None:
    try:
        return float(value.replace("%", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_spy_holdings(blob: bytes, observed_at: str | None = None) -> list[HoldingRecord]:
    rows = read_first_sheet_xlsx(blob)
    as_of_raw = next((row[1] for row in rows if row and row[0].rstrip(":") in {"Holdings", "Holdings As of"}), "")
    as_of = as_of_raw.removeprefix("As of ").strip()
    try:
        as_of = datetime.strptime(as_of, "%d-%b-%Y").date().isoformat()
    except ValueError:
        pass
    header_index = next(i for i, row in enumerate(rows) if "Ticker" in row and "Name" in row)
    headers = {name: idx for idx, name in enumerate(rows[header_index])}
    records = []
    for row in rows[header_index + 1:]:
        symbol = row[headers["Ticker"]].strip() if len(row) > headers["Ticker"] else ""
        # The fund sheet can contain cash, collateral, and CVR placeholders in
        # addition to index equities. Keep only valid US exchange ticker forms.
        if not re.fullmatch(r"[A-Z]{1,5}(?:[.-][A-Z])?", symbol):
            continue
        records.append(HoldingRecord(
            symbol=symbol, name=row[headers["Name"]], collection="SPY", as_of=as_of,
            weight=_number(row[headers["Weight"]]) if "Weight" in headers else None,
            identifier=row[headers["Identifier"]] if "Identifier" in headers else None,
            currency=row[headers["Local Currency"]] if "Local Currency" in headers else None,
            source="State Street SPY official holdings", observed_at=observed_at))
    return records


def parse_ndx_holdings(blob: bytes, as_of: str, observed_at: str | None = None) -> list[HoldingRecord]:
    rows = read_first_sheet_xlsx(blob)
    header_index = next(i for i, row in enumerate(rows) if "Security Symbol" in row)
    headers = {name: idx for idx, name in enumerate(rows[header_index])}
    return [HoldingRecord(
        symbol=row[headers["Security Symbol"]], name=row[headers["Company Name"]],
        collection="NDX", as_of=as_of, source="Nasdaq NDX official weightings",
        observed_at=observed_at)
        for row in rows[header_index + 1:]
        if len(row) > headers["Security Symbol"] and row[headers["Security Symbol"]].strip()]


class OfficialHoldingsClient:
    def __init__(self, store: DataStore, user_agent: str = "Value-Growth-Screener/1.0"):
        self.store = store
        self.user_agent = user_agent

    def _download(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"})
        with urllib.request.urlopen(request, timeout=45) as response:
            blob = response.read()
        if not blob.startswith(b"PK"):
            raise ValueError("official holdings response is not an XLSX file")
        return blob

    def current(self, trade_date: str | date, refresh: bool = False) -> list[HoldingRecord]:
        day = date.fromisoformat(trade_date) if isinstance(trade_date, str) else trade_date
        stamp = datetime.now(timezone.utc).isoformat()
        spy_name, ndx_name = f"spy-{day.isoformat()}", f"ndx-{day.isoformat()}"
        spy = None if refresh else self.store.read_bytes("raw", spy_name, ".xlsx")
        ndx = None if refresh else self.store.read_bytes("raw", ndx_name, ".xlsx")
        if spy is None:
            spy = self._download(SPY_URL)
            self.store.write_bytes("raw", spy_name, ".xlsx", spy)
        if ndx is None:
            query = urllib.parse.urlencode({"tradeDate": f"{day.isoformat()}T00:00:00", "timeOfDay": "SOD"})
            ndx = self._download(f"{NDX_URL}?{query}")
            self.store.write_bytes("raw", ndx_name, ".xlsx", ndx)
        spy_rows = parse_spy_holdings(spy, stamp)
        if not spy_rows or spy_rows[0].as_of != day.isoformat():
            actual = spy_rows[0].as_of if spy_rows else "missing"
            raise ValueError(f"SPY file as-of {actual} does not match requested trade date {day.isoformat()}")
        return spy_rows + parse_ndx_holdings(ndx, day.isoformat(), stamp)


def holdings_to_universe(rows: list[HoldingRecord]) -> list[SecurityRecord]:
    by_symbol: dict[str, SecurityRecord] = {}
    for row in rows:
        by_symbol[row.symbol] = SecurityRecord(row.symbol, row.name, source="official SPY/NDX", observed_at=row.observed_at)
    return [by_symbol[symbol] for symbol in sorted(by_symbol)]
