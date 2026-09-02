"""SEC EDGAR read-only adapter using official JSON endpoints."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from .cache import DataStore
from .models import SecurityRecord


SEC_BASE = "https://data.sec.gov"
SEC_FILES = "https://www.sec.gov/files"


class SecEdgarClient:
    def __init__(self, user_agent: str, store: DataStore, minimum_interval: float = 0.12):
        if "@" not in user_agent:
            raise ValueError("SEC user_agent must identify the requester and include an email address")
        self.user_agent = user_agent
        self.store = store
        self.minimum_interval = max(minimum_interval, 0.10)
        self._last_request = 0.0

    def _get_json(self, url: str) -> Any:
        wait = self.minimum_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        with urlopen(request, timeout=60) as response:
            payload = response.read()
        self._last_request = time.monotonic()
        return json.loads(payload.decode("utf-8"))

    def company_tickers(self, refresh: bool = False) -> list[SecurityRecord]:
        cache_name = "sec-company-tickers-exchange"
        raw = None if refresh else self.store.read_json("cache", cache_name)
        if raw is None:
            raw = self._get_json(f"{SEC_FILES}/company_tickers_exchange.json")
            self.store.write_json("cache", cache_name, raw)
        fields = raw["fields"]
        observed = datetime.now(timezone.utc).isoformat()
        records: list[SecurityRecord] = []
        for values in raw["data"]:
            row = dict(zip(fields, values, strict=True))
            records.append(SecurityRecord(symbol=row["ticker"], name=row["name"], cik=str(row["cik"]),
                                          exchange=row.get("exchange"), source="SEC",
                                          observed_at=observed))
        return records

    def submissions(self, cik: str, refresh: bool = False) -> dict[str, Any]:
        cik10 = str(cik).zfill(10)
        name = f"sec-submissions-CIK{cik10}"
        cached = None if refresh else self.store.read_json("raw", name)
        if cached is not None:
            return cached
        payload = self._get_json(f"{SEC_BASE}/submissions/CIK{cik10}.json")
        self.store.write_json("raw", name, payload)
        return payload

    def companyfacts(self, cik: str, refresh: bool = False) -> dict[str, Any]:
        cik10 = str(cik).zfill(10)
        name = f"sec-companyfacts-CIK{cik10}"
        cached = None if refresh else self.store.read_json("raw", name)
        if cached is not None:
            return cached
        payload = self._get_json(f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik10}.json")
        self.store.write_json("raw", name, payload)
        return payload
