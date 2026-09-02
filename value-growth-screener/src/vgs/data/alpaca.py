"""Alpaca daily-bar adapter. Credentials are read only from environment variables."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cache import DataStore
from .models import MarketBar


class AlpacaMarketDataClient:
    def __init__(self, store: DataStore, key_id: str | None = None, secret_key: str | None = None):
        self.store = store
        self.key_id = key_id or os.getenv("ALPACA_API_KEY_ID")
        self.secret_key = secret_key or os.getenv("ALPACA_API_SECRET_KEY")
        if not self.key_id or not self.secret_key:
            raise ValueError("Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        url = "https://data.alpaca.markets/v2/stocks/bars?" + urlencode(params)
        request = Request(url, headers={"APCA-API-KEY-ID": self.key_id,
                                        "APCA-API-SECRET-KEY": self.secret_key,
                                        "Accept": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def daily_bars(self, symbols: Iterable[str], start: str, end: str, feed: str = "iex",
                   refresh: bool = False) -> list[MarketBar]:
        symbols_list = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
        params: dict[str, Any] = {"symbols": ",".join(symbols_list), "timeframe": "1Day",
                                  "start": start, "end": end, "adjustment": "all", "feed": feed,
                                  "limit": 10000, "sort": "asc"}
        key = self.store.cache_key("alpaca-bars", params)
        raw = None if refresh else self.store.read_json("cache", key)
        if raw is None:
            pages: list[dict[str, Any]] = []
            token: str | None = None
            while True:
                page_params = dict(params)
                if token:
                    page_params["page_token"] = token
                page = self._request(page_params)
                pages.append(page)
                token = page.get("next_page_token")
                if not token:
                    break
            raw = {"pages": pages, "request": params,
                   "observed_at": datetime.now(timezone.utc).isoformat()}
            self.store.write_json("cache", key, raw)
        return normalize_alpaca_pages(raw["pages"], feed=feed, observed_at=raw.get("observed_at"))


def normalize_alpaca_pages(pages: list[dict[str, Any]], feed: str,
                           observed_at: str | None = None) -> list[MarketBar]:
    records: list[MarketBar] = []
    for page in pages:
        for symbol, bars in page.get("bars", {}).items():
            for bar in bars:
                records.append(MarketBar(symbol=symbol, timestamp=bar["t"], open=float(bar["o"]),
                                         high=float(bar["h"]), low=float(bar["l"]), close=float(bar["c"]),
                                         volume=float(bar["v"]), trade_count=bar.get("n"), vwap=bar.get("vw"),
                                         feed=feed, provider="Alpaca", observed_at=observed_at))
    return sorted(records, key=lambda record: (record.symbol, record.timestamp))
