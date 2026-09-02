"""Normalized records shared by every external-data adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class SecurityRecord:
    symbol: str
    name: str
    cik: str | None = None
    exchange: str | None = None
    asset_class: str = "stock"
    active: bool = True
    source: str = "unknown"
    observed_at: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("security symbol is required")
        object.__setattr__(self, "symbol", symbol)
        if self.cik:
            digits = str(self.cik).strip()
            if not digits.isdigit():
                raise ValueError("CIK must contain digits only")
            object.__setattr__(self, "cik", digits.zfill(10))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: float | None = None
    vwap: float | None = None
    currency: str = "USD"
    feed: str = "unknown"
    provider: str = "unknown"
    observed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if not self.symbol:
            raise ValueError("bar symbol is required")
        datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("bar values must be finite")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC values are internally inconsistent")
        if self.high < self.low or self.volume < 0:
            raise ValueError("high must exceed low and volume must be non-negative")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HoldingRecord:
    symbol: str
    name: str
    collection: str
    as_of: str
    weight: float | None = None
    identifier: str | None = None
    currency: str | None = None
    source: str = "unknown"
    observed_at: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper().replace(".", "-")
        if not symbol:
            raise ValueError("holding symbol is required")
        object.__setattr__(self, "symbol", symbol)
        if self.weight is not None and not isfinite(float(self.weight)):
            raise ValueError("holding weight must be finite")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
