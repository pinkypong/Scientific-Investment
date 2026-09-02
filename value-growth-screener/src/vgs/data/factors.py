"""Ken French factor and FRED/ALFRED vintage-aware macro adapters."""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Any

from .cache import DataStore

KEN_FRENCH_URLS = {
    "ff5_daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "momentum_daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip",
}
DEFAULT_FRED_SERIES = ("DGS10", "DGS2", "FEDFUNDS", "CPIAUCSL", "UNRATE", "BAMLH0A0HYM2")


def parse_ken_french_csv(text: str, dataset: str) -> list[dict[str, Any]]:
    """Parse the dated block and convert reported percentages to decimal returns."""
    lines = text.replace("\ufeff", "").splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith(",")), None)
    if start is None:
        raise ValueError("Ken French header not found")
    header = [cell.strip() or "date" for cell in next(csv.reader([lines[start]]))]
    output = []
    for cells in csv.reader(lines[start + 1:]):
        if not cells or not cells[0].strip().isdigit() or len(cells[0].strip()) != 8:
            if output:
                break
            continue
        values: dict[str, Any] = {"date": datetime.strptime(cells[0].strip(), "%Y%m%d").date().isoformat(),
                                  "dataset": dataset, "provider": "Kenneth French Data Library"}
        for key, raw in zip(header[1:], cells[1:]):
            try:
                values[key.lower().replace("-", "_")] = float(raw.strip()) / 100.0
            except ValueError:
                values[key.lower().replace("-", "_")] = None
        output.append(values)
    return output


class KenFrenchClient:
    def __init__(self, store: DataStore):
        self.store = store

    def dataset(self, name: str, refresh: bool = False) -> list[dict[str, Any]]:
        if name not in KEN_FRENCH_URLS:
            raise ValueError(f"unknown Ken French dataset: {name}")
        cache_name = f"ken-french-{name}"
        if not refresh and (cached := self.store.read_json("cache", cache_name)) is not None:
            return cached
        request = urllib.request.Request(KEN_FRENCH_URLS[name], headers={"User-Agent": "Value-Growth-Screener/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            blob = response.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            member = next(path for path in archive.namelist() if path.lower().endswith(".csv"))
            text = archive.read(member).decode("utf-8-sig", errors="replace")
        rows = parse_ken_french_csv(text, name)
        self.store.write_json("cache", cache_name, rows)
        return rows


class FredClient:
    def __init__(self, store: DataStore, api_key: str | None = None):
        self.store = store
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ValueError("FRED API key is required via api_key or FRED_API_KEY")

    def observations(self, series_id: str, start: str, end: str, vintage_date: str,
                     refresh: bool = False) -> list[dict[str, Any]]:
        params = {"series_id": series_id, "observation_start": start, "observation_end": end,
                  "realtime_start": vintage_date, "realtime_end": vintage_date,
                  "api_key": self.api_key, "file_type": "json"}
        cache_name = DataStore.cache_key("fred", {key: value for key, value in params.items() if key != "api_key"})
        if not refresh and (cached := self.store.read_json("cache", cache_name)) is not None:
            return cached
        url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": "Value-Growth-Screener/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
        stamp = datetime.now(timezone.utc).isoformat()
        rows = [{"series_id": series_id, "date": item["date"],
                 "value": None if item["value"] == "." else float(item["value"]),
                 "vintage_date": vintage_date, "provider": "FRED/ALFRED", "observed_at": stamp}
                for item in payload.get("observations", [])]
        self.store.write_json("cache", cache_name, rows)
        return rows
