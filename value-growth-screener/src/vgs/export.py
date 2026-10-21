"""Export engine results as the JSON files a viewer (the dashboard) reads.

Two kinds of file, matching the screen layout:

  screen.json           one row per security — reported facts and the rule-based objective
                        score only. Nothing here depends on a valuation assumption (Step 1).
  detail/<TICKER>.json  everything for one security: Step 1 facts, Step 2 assumption-based
                        valuation, and Step 3 links (Step 3 never carries numbers).

The files are deterministic (sorted keys, no timestamps) so an unchanged input gives an
identical file, and each detail file records a hash of the facts it was computed from.
Analyst forecasts (``objective.consensus``) are dropped on the way out.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .engine import ASSUMPTION_FLAG_CODES, EXCLUDED_OBJECTIVE_GROUPS, _get, _number

SCHEMA_SCREEN = "vgs.screen/1"
SCHEMA_DETAIL = "vgs.detail/1"

# (key, label, kind, objective path). The path is shown to the viewer so every column says
# where its numbers come from.
SCREEN_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("price", "주가", "num", "market.price"),
    ("market_cap", "시가총액", "num", "market.market_cap"),
    ("revenue_ttm", "매출(TTM)", "num", "financials.revenue_ttm"),
    ("ebit_margin_ttm", "영업이익률(TTM)", "pct", "financials.ebit_margin_ttm"),
    ("roic", "ROIC", "pct", "ratios.roic"),
    ("ocf_to_net_income", "영업CF/순이익", "ratio", "ratios.ocf_to_net_income"),
    ("accrual_ratio", "발생액비율", "ratio", "ratios.accrual_ratio"),
    ("debt_to_ebitda", "부채/EBITDA", "ratio", "ratios.debt_to_ebitda"),
    ("interest_coverage", "이자보상배율", "ratio", "ratios.interest_coverage"),
    ("revenue_cagr_3y", "매출 3년 CAGR", "pct", "history.revenue_cagr_3y"),
    ("revenue_yoy_ttm", "매출 YoY(TTM)", "pct", "history.revenue_yoy_ttm"),
    ("ebit_margin_change_3y", "영업이익률 3년 변화", "pct", "history.ebit_margin_change_3y"),
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _facts(objective: dict[str, Any]) -> dict[str, float | None]:
    return {key: _number(_get(objective, path)) for key, _, _, path in SCREEN_COLUMNS}


def _public_objective(objective: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(objective)
    for group in EXCLUDED_OBJECTIVE_GROUPS:
        cleaned.pop(group, None)
    return cleaned


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _data_flags(flags: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [flag for flag in flags if flag["code"] not in ASSUMPTION_FLAG_CODES]


def _flag_counts(flags: list[dict[str, str]]) -> dict[str, int]:
    return {"critical": sum(f["severity"] == "critical" for f in flags),
            "warning": sum(f["severity"] == "warning" for f in flags)}


def ticker_of(result: dict[str, Any]) -> str:
    ticker = str(result.get("security", {}).get("ticker") or "").strip()
    if not ticker:
        raise ValueError("security.ticker is required to export a result")
    return ticker


def step3_links(result: dict[str, Any]) -> list[dict[str, str]]:
    """Links only. Built from the CIK and from URLs already present in ``sources``;
    no news or analyst URL is ever constructed here."""
    links: list[dict[str, str]] = []
    cik = str(result.get("security", {}).get("cik") or "").strip()
    if cik.isdigit():
        links.append({"kind": "sec_filings", "label": "SEC 공시 목록 (10-K · 10-Q · 8-K)",
                      "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK="
                             f"{quote(cik.zfill(10))}&owner=include&count=40"})
    for source in result.get("sources", []):
        url = str(source.get("url") or "")
        if url.startswith(("https://", "http://")):  # never javascript: or data:
            links.append({"kind": "source", "label": str(source.get("provider") or "source"), "url": url})
    return links


def build_detail(result: dict[str, Any]) -> dict[str, Any]:
    """One security's full record. Pure: ``result`` is not modified."""
    computed = result["computed"]
    flags = result.get("flags", [])
    objective = _public_objective(result.get("objective", {}))
    data_flags = _data_flags(flags)
    return {
        "schema": SCHEMA_DETAIL,
        "security": deepcopy(result.get("security", {})),
        "as_of": result.get("as_of"),
        "step1": {
            "label": "rule_based",
            "facts": _facts(objective),
            "objective_score": deepcopy(computed["objective_score"]),
            "data_completeness": computed["data_completeness"],
            "provenance_coverage": computed["provenance_coverage"],
            "flags": data_flags,
        },
        "step2": {
            "label": "assumption_based",
            "assumptions": deepcopy(result.get("assumptions", {})),
            "scenario_valuation": deepcopy(computed["scenario_valuation"]),
            "probability_weighted_fair_value": computed["probability_weighted_fair_value"],
            "base_fair_value": computed["base_fair_value"],
            "upside": computed["upside"],
            "margin_of_safety": computed["margin_of_safety"],
            "reverse_dcf_implied_initial_growth": computed["reverse_dcf_implied_initial_growth"],
            "relative_cross_check": deepcopy(computed["relative_cross_check"]),
            "wacc_build": deepcopy(computed["wacc_build"]),
            "cycle_comparison": deepcopy(computed.get("cycle_comparison", [])),
            "risk_adjusted_opportunity_score": computed["risk_adjusted_opportunity_score"],
            "decision": computed["decision"],
            "flags": [flag for flag in flags if flag["code"] in ASSUMPTION_FLAG_CODES],
        },
        "step3": {"label": "links_only", "links": step3_links(result)},
        "objective": objective,
        "sources": deepcopy(result.get("sources", [])),
        "integrity": {"objective_sha256": hashlib.sha256(_canonical(objective).encode("utf-8")).hexdigest()},
    }


def build_screen(results: Iterable[dict[str, Any]], universe: str | None = None) -> dict[str, Any]:
    """Step 1 table. Only reported facts and the rule-based objective score."""
    rows = []
    for result in results:
        detail = build_detail(result)
        step1 = detail["step1"]
        rows.append({
            "ticker": ticker_of(result),
            "name": result.get("security", {}).get("name"),
            "sector": result.get("security", {}).get("sector"),
            "as_of": result.get("as_of"),
            "facts": step1["facts"],
            "objective_score": step1["objective_score"]["total"],
            "data_completeness": step1["data_completeness"],
            "provenance_coverage": step1["provenance_coverage"],
            "flags": _flag_counts(step1["flags"]),
            "detail": f"detail/{_SAFE_NAME.sub('_', ticker_of(result))}.json",
        })
    rows.sort(key=lambda row: (-row["objective_score"], row["ticker"]))
    return {
        "schema": SCHEMA_SCREEN,
        "meta": {"universe": universe, "count": len(rows),
                 "score_label": "rule_based",
                 "note": "공시 숫자와 규칙 기반 점수만 담는다. 가치평가 가정에 의존하는 값은 detail 파일의 step2에 있다."},
        "columns": [{"key": k, "label": label, "kind": kind, "path": f"objective.{path}"}
                    for k, label, kind, path in SCREEN_COLUMNS],
        "rows": rows,
    }


def write_export(results: list[dict[str, Any]], out_dir: str | Path, universe: str | None = None) -> list[Path]:
    """Write screen.json and detail/<TICKER>.json. Returns the written paths."""
    out = Path(out_dir)
    names: dict[str, str] = {}
    for result in results:
        ticker = ticker_of(result)
        safe = _SAFE_NAME.sub("_", ticker)
        if safe in names:
            raise ValueError(f"tickers {names[safe]!r} and {ticker!r} map to the same file name")
        names[safe] = ticker
    (out / "detail").mkdir(parents=True, exist_ok=True)
    written = []
    for result in results:
        path = out / "detail" / f"{_SAFE_NAME.sub('_', ticker_of(result))}.json"
        path.write_text(json.dumps(build_detail(result), sort_keys=True, ensure_ascii=False, indent=1,
                                   allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    screen_path = out / "screen.json"
    screen_path.write_text(json.dumps(build_screen(results, universe), sort_keys=True, ensure_ascii=False,
                                      indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return [screen_path, *written]
