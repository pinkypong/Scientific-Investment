"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .data.alpaca import AlpacaMarketDataClient
from .data.cache import DataStore
from .data.deep_dive import build_bigdata_queue
from .data.factors import DEFAULT_FRED_SERIES, FredClient, KenFrenchClient
from .data.holdings import OfficialHoldingsClient, holdings_to_universe
from .data.models import SecurityRecord
from .data.sec import SecEdgarClient
from .data.universe import DEFAULT_FORCED_SYMBOLS, build_universe, read_holdings_csv
from .data.xbrl import normalize_companyfacts
from .engine import analyze_security, rank_results
from .report import render_markdown, render_ranking_csv


def _load(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_or_print(content: str, output: str | None) -> None:
    if output:
        Path(output).write_text(content, encoding="utf-8")
    else:
        print(content)


def _read_jsonl_records(path: str | Path) -> list[SecurityRecord]:
    records: list[SecurityRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(SecurityRecord(**json.loads(line)))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vgs", description="Value Growth Screener")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Analyze one normalized JSON input")
    analyze.add_argument("input")
    analyze.add_argument("--config")
    analyze.add_argument("--output")
    screen = sub.add_parser("screen", help="Rank multiple normalized JSON inputs")
    screen.add_argument("inputs", nargs="+")
    screen.add_argument("--config")
    screen.add_argument("--output")
    sec = sub.add_parser("sec-security-master", help="Download/cache the SEC ticker-to-CIK map")
    sec.add_argument("--data-root", default="data")
    sec.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"))
    sec.add_argument("--refresh", action="store_true")
    sec.add_argument("--output-name", default="security-master-sec")
    bars = sub.add_parser("alpaca-bars", help="Download/cache normalized Alpaca daily bars")
    bars.add_argument("symbols", nargs="+")
    bars.add_argument("--start", required=True)
    bars.add_argument("--end", required=True)
    bars.add_argument("--feed", choices=("iex", "sip", "delayed_sip"), default="iex")
    bars.add_argument("--data-root", default="data")
    bars.add_argument("--refresh", action="store_true")
    bars.add_argument("--output-name", default="market-bars-alpaca")
    universe = sub.add_parser("build-universe", help="Union holdings CSV files and force current holdings")
    universe.add_argument("holdings", nargs="+")
    universe.add_argument("--security-master")
    universe.add_argument("--forced", nargs="*", default=list(DEFAULT_FORCED_SYMBOLS))
    universe.add_argument("--data-root", default="data")
    universe.add_argument("--output-name", default="universe-us-large-cap")
    official = sub.add_parser("official-us-universe", help="Download official SPY and Nasdaq-100 holdings")
    official.add_argument("--trade-date", required=True)
    official.add_argument("--data-root", default="data")
    official.add_argument("--refresh", action="store_true")
    snapshot = sub.add_parser("sec-snapshot", help="Build a point-in-time SEC XBRL TTM snapshot")
    snapshot.add_argument("cik")
    snapshot.add_argument("--as-of", required=True)
    snapshot.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT"))
    snapshot.add_argument("--data-root", default="data")
    snapshot.add_argument("--refresh", action="store_true")
    factors = sub.add_parser("ken-french", help="Cache normalized daily factor returns")
    factors.add_argument("datasets", nargs="*", default=["ff5_daily", "momentum_daily"])
    factors.add_argument("--data-root", default="data")
    factors.add_argument("--refresh", action="store_true")
    fred = sub.add_parser("fred", help="Cache vintage-aware FRED/ALFRED macro observations")
    fred.add_argument("--series", nargs="*", default=list(DEFAULT_FRED_SERIES))
    fred.add_argument("--start", required=True)
    fred.add_argument("--end", required=True)
    fred.add_argument("--vintage-date", required=True)
    fred.add_argument("--data-root", default="data")
    fred.add_argument("--refresh", action="store_true")
    queue = sub.add_parser("bigdata-queue", help="Create a tiered deep-dive queue from ranked CSV")
    queue.add_argument("ranking")
    queue.add_argument("--tier2", type=int, default=50)
    queue.add_argument("--tier3", type=int, default=20)
    queue.add_argument("--tier4", type=int, default=15)
    queue.add_argument("--forced", nargs="*", default=list(DEFAULT_FORCED_SYMBOLS))
    queue.add_argument("--data-root", default="data")
    queue.add_argument("--output-name", default="bigdata-deep-dive-queue")
    args = parser.parse_args(argv)
    if args.command == "analyze":
        config = _load(args.config) if args.config else None
        _write_or_print(render_markdown(analyze_security(_load(args.input), config)), args.output)
        return 0
    if args.command == "screen":
        config = _load(args.config) if args.config else None
        ranked = rank_results(analyze_security(_load(path), config) for path in args.inputs)
        _write_or_print(render_ranking_csv(ranked), args.output)
        return 0
    store = DataStore(args.data_root)
    if args.command == "official-us-universe":
        holdings = OfficialHoldingsClient(store).current(args.trade_date, refresh=args.refresh)
        holding_path = store.write_jsonl("normalized", f"official-holdings-{args.trade_date}",
                                         (record.as_dict() for record in holdings))
        universe_path = store.write_jsonl("normalized", f"official-universe-{args.trade_date}",
                                          (record.as_dict() for record in holdings_to_universe(holdings)))
        print(json.dumps({"holdings": str(holding_path), "universe": str(universe_path),
                          "holding_rows": len(holdings), "unique_symbols": len(holdings_to_universe(holdings))}))
        return 0
    if args.command == "sec-snapshot":
        if not args.user_agent:
            parser.error("sec-snapshot requires --user-agent or SEC_USER_AGENT")
        facts = SecEdgarClient(args.user_agent, store).companyfacts(args.cik, refresh=args.refresh)
        output = store.write_json("normalized", f"sec-snapshot-CIK{str(args.cik).zfill(10)}-{args.as_of}",
                                  normalize_companyfacts(facts, args.as_of))
        print(output)
        return 0
    if args.command == "ken-french":
        client = KenFrenchClient(store)
        outputs = {}
        for dataset in args.datasets:
            rows = client.dataset(dataset, refresh=args.refresh)
            outputs[dataset] = str(store.write_jsonl("normalized", f"ken-french-{dataset}", rows))
        print(json.dumps(outputs))
        return 0
    if args.command == "fred":
        client = FredClient(store)
        outputs = {}
        for series in args.series:
            rows = client.observations(series, args.start, args.end, args.vintage_date, refresh=args.refresh)
            outputs[series] = str(store.write_jsonl("normalized", f"fred-{series}-{args.vintage_date}", rows))
        print(json.dumps(outputs))
        return 0
    if args.command == "bigdata-queue":
        rows = build_bigdata_queue(args.ranking, args.tier2, args.tier3, args.tier4, args.forced)
        output = store.write_jsonl("reports", args.output_name, rows)
        print(json.dumps({"path": str(output), "candidates": len(rows)}))
        return 0
    if args.command == "sec-security-master":
        if not args.user_agent:
            parser.error("sec-security-master requires --user-agent or SEC_USER_AGENT")
        records = SecEdgarClient(args.user_agent, store).company_tickers(refresh=args.refresh)
        output = store.write_jsonl("normalized", args.output_name, (record.as_dict() for record in records))
        print(output)
        return 0
    if args.command == "alpaca-bars":
        records = AlpacaMarketDataClient(store).daily_bars(args.symbols, args.start, args.end,
                                                            feed=args.feed, refresh=args.refresh)
        output = store.write_jsonl("normalized", args.output_name, (record.as_dict() for record in records))
        print(output)
        return 0
    master = _read_jsonl_records(args.security_master) if args.security_master else []
    groups = [read_holdings_csv(path) for path in args.holdings]
    records = build_universe(groups, master, args.forced)
    output = store.write_jsonl("normalized", args.output_name, (record.as_dict() for record in records))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
