"""Token-efficient Bigdata.com deep-dive queue built from screening ranks."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_bigdata_queue(ranking_csv: str | Path, tier2: int = 50, tier3: int = 20,
                        tier4: int = 15, forced_symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Escalate data cost only for candidates that survive the preceding rank gate."""
    with Path(ranking_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return []
    symbol_field = next((field for field in ("ticker", "symbol", "Ticker", "Symbol") if field in rows[0]), None)
    if symbol_field is None:
        raise ValueError("ranking CSV requires ticker or symbol column")
    stamp = datetime.now(timezone.utc).isoformat()
    queue = []
    for rank, row in enumerate(rows[:tier2], 1):
        symbol = row[symbol_field].strip().upper()
        if not symbol:
            continue
        tasks = ["tearsheet:overview,ratios,key_metrics,analyst_estimates,latest_earnings"]
        tier = 2
        if rank <= tier3:
            tier = 3
            tasks += ["tearsheet:financial_statements,analyst_ratings,fund_trends_history,hiring_trends",
                      "sentiment:30d"]
        if rank <= tier4:
            tier = 4
            tasks += ["primary_sources:latest_10k_10q_8k_and_earnings_call", "catalysts", "valuation_cross_check"]
        queue.append({"symbol": symbol, "rank": rank, "tier": tier, "status": "pending",
                      "tasks": tasks, "created_at": stamp,
                      "token_policy": "metadata/tearsheet first; full-text retrieval only for material discrepancies"})
    queued = {item["symbol"] for item in queue}
    for symbol in forced_symbols or []:
        normalized = symbol.strip().upper()
        if normalized and normalized not in queued:
            queue.append({"symbol": normalized, "rank": None, "tier": 4, "status": "pending",
                          "reason": "forced_current_holding", "tasks": [
                              "tearsheet:overview,ratios,key_metrics,analyst_estimates,latest_earnings,financial_statements,analyst_ratings,fund_trends_history,hiring_trends",
                              "sentiment:30d", "primary_sources:latest_10k_10q_8k_and_earnings_call",
                              "catalysts", "valuation_cross_check"], "created_at": stamp,
                          "token_policy": "metadata/tearsheet first; full-text retrieval only for material discrepancies"})
            queued.add(normalized)
    return queue
