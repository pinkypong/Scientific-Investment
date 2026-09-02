"""Build a reproducible current US universe from provider holdings files."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import SecurityRecord


DEFAULT_FORCED_SYMBOLS = ("GOOGL", "MRVL", "MU", "SNDK", "ADI", "NVDA", "QCOM")


def read_holdings_csv(path: str | Path, symbol_columns: tuple[str, ...] = ("Ticker", "Symbol", "ticker", "symbol"),
                      name_columns: tuple[str, ...] = ("Name", "Company", "Security Name", "name")) -> list[SecurityRecord]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        records: list[SecurityRecord] = []
        for row in reader:
            symbol = next((row.get(column) for column in symbol_columns if row.get(column)), None)
            if not symbol or symbol.strip() in {"-", "N/A"}:
                continue
            name = next((row.get(column) for column in name_columns if row.get(column)), None) or symbol
            records.append(SecurityRecord(symbol=symbol, name=name, source=source.name,
                                          observed_at=datetime.now(timezone.utc).isoformat()))
        return records


def build_universe(groups: Iterable[Iterable[SecurityRecord]], security_master: Iterable[SecurityRecord] = (),
                   forced_symbols: Iterable[str] = DEFAULT_FORCED_SYMBOLS) -> list[SecurityRecord]:
    master = {record.symbol: record for record in security_master}
    selected: dict[str, SecurityRecord] = {}
    for group in groups:
        for record in group:
            selected[record.symbol] = master.get(record.symbol, record)
    for symbol in forced_symbols:
        normalized = symbol.strip().upper()
        selected[normalized] = master.get(normalized, SecurityRecord(symbol=normalized, name=normalized,
                                                                      source="forced-holding"))
    return sorted(selected.values(), key=lambda record: record.symbol)
